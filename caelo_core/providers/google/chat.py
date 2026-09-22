"""Streaming czatu Gemini przez REST ``streamGenerateContent``.

Adapter nie używa SDK Google. Tłumaczy neutralne wiadomości Caelo na ``Content``
Gemini, obsługuje obrazy i PDF-y inline, a odpowiedzi SSE mapuje na wspólny wynik
czatu używany przez WebSocket renderera.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, Optional

from caelo_core.providers.base import ChatCompletionResult
from caelo_core.providers.errors import ErrorCategory, ProviderError

from .client import GoogleClient


_SAFETY_OFF = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "OFF"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "OFF"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "OFF"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "OFF"},
]


def _data_uri(value: str, fallback_mime: str = "application/octet-stream") -> dict[str, str]:
    if not isinstance(value, str) or not value.startswith("data:") or "," not in value:
        raise ValueError("Google chat attachments must use an inline data URI")
    header, encoded = value.split(",", 1)
    if ";base64" not in header.lower():
        raise ValueError("Google chat attachments must be base64 encoded")
    mime = header[5:].split(";", 1)[0].strip().lower() or fallback_mime
    if not encoded:
        raise ValueError("Google chat attachment is empty")
    return {"mimeType": mime, "data": encoded}


def _message_parts(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"text": content}] if content else []
    if not isinstance(content, list):
        return []
    parts: list[dict[str, Any]] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind == "text" and item.get("text"):
            parts.append({"text": str(item["text"])})
        elif kind == "image_url":
            image = item.get("image_url") or {}
            parts.append({"inlineData": _data_uri(str(image.get("url") or ""), "image/png")})
        elif kind == "document":
            document = item.get("document") or {}
            mime = str(document.get("mime") or "application/octet-stream").lower()
            # Oficjalna ścieżka inline w Gemini obejmuje PDF. Pliki Office wymagają
            # wcześniejszej konwersji lub Files API, którego czat w tej fazie nie używa.
            if mime != "application/pdf" and not mime.startswith("text/"):
                name = str(document.get("name") or "document")
                raise ValueError(
                    f"Google chat currently accepts PDF or text documents; '{name}' uses {mime}."
                )
            parts.append({"inlineData": _data_uri(str(document.get("data") or ""), mime)})
    return parts


def build_google_chat_payload(
    messages: Iterable[dict[str, Any]],
    *,
    model: str,
    temperature: float = 0.7,
    reasoning_effort: Optional[str] = None,
    search_grounding: bool = False,
) -> dict[str, Any]:
    contents: list[dict[str, Any]] = []
    system_parts: list[dict[str, str]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user").lower()
        parts = _message_parts(message.get("content"))
        if not parts:
            continue
        if role == "system":
            system_parts.extend(part for part in parts if "text" in part)
            continue
        gemini_role = "model" if role == "assistant" else "user"
        # Scal sąsiednie wiadomości tej samej roli. Gemini oczekuje naprzemiennej
        # historii, a Caelo może mieć kilka bloków system/user po migracji rozmowy.
        if contents and contents[-1]["role"] == gemini_role:
            contents[-1]["parts"].extend(parts)
        else:
            contents.append({"role": gemini_role, "parts": parts})
    if not contents:
        raise ValueError("Google chat requires at least one user message")

    generation: dict[str, Any] = {}
    if model.startswith("gemini-2."):
        generation["temperature"] = max(0.0, min(1.0, float(temperature)))
    effort = str(reasoning_effort or "").lower()
    if model.startswith("gemini-3") and effort in {"low", "medium", "high"}:
        generation["thinkingConfig"] = {"thinkingLevel": effort}

    payload: dict[str, Any] = {
        "contents": contents,
        "safetySettings": list(_SAFETY_OFF),
    }
    if generation:
        payload["generationConfig"] = generation
    if system_parts:
        payload["systemInstruction"] = {"parts": system_parts}
    if search_grounding:
        payload["tools"] = [{"googleSearch": {}}]
    return payload


def _chunk_text(chunk: dict[str, Any]) -> str:
    candidates = chunk.get("candidates") or []
    if not isinstance(candidates, list) or not candidates:
        return ""
    content = candidates[0].get("content") if isinstance(candidates[0], dict) else None
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list):
        return ""
    return "".join(
        str(part.get("text") or "") for part in parts
        if isinstance(part, dict) and not part.get("thought") and part.get("text")
    )


def _blocked_reason(chunk: dict[str, Any]) -> Optional[str]:
    feedback = chunk.get("promptFeedback") or {}
    if isinstance(feedback, dict) and feedback.get("blockReason"):
        return str(feedback["blockReason"])
    candidates = chunk.get("candidates") or []
    if isinstance(candidates, list) and candidates and isinstance(candidates[0], dict):
        reason = str(candidates[0].get("finishReason") or "")
        if reason and reason not in {"STOP", "MAX_TOKENS", "FINISH_REASON_UNSPECIFIED"}:
            return reason
    return None


def _citations(chunk: dict[str, Any]) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    candidates = chunk.get("candidates") or []
    if not isinstance(candidates, list):
        return found
    for candidate in candidates:
        metadata = candidate.get("groundingMetadata") if isinstance(candidate, dict) else None
        chunks = metadata.get("groundingChunks") if isinstance(metadata, dict) else None
        if not isinstance(chunks, list):
            continue
        for item in chunks:
            web = item.get("web") if isinstance(item, dict) else None
            uri = str(web.get("uri") or "") if isinstance(web, dict) else ""
            if uri:
                found.append({"url": uri, "title": str(web.get("title") or uri)})
    return found


def _usage(chunk: dict[str, Any]) -> dict[str, int]:
    metadata = chunk.get("usageMetadata") or {}
    if not isinstance(metadata, dict):
        return {}
    mapping = {
        "promptTokenCount": "input_tokens",
        "candidatesTokenCount": "output_tokens",
        "totalTokenCount": "total_tokens",
        "thoughtsTokenCount": "reasoning_tokens",
    }
    return {
        target: int(metadata[source]) for source, target in mapping.items()
        if isinstance(metadata.get(source), (int, float))
    }


class GoogleChatProvider:
    def __init__(self, client: GoogleClient) -> None:
        self.client = client

    def stream_chat(
        self,
        messages: Iterable[dict[str, Any]],
        *,
        model: Optional[str] = None,
        temperature: float = 0.7,
        reasoning_effort: Optional[str] = None,
        search_grounding: bool = False,
        on_delta: Optional[Callable[[str, str], None]] = None,
        on_tool: Optional[Callable[[dict[str, Any]], None]] = None,
        stop_flag: Optional[Callable[[], bool]] = None,
    ) -> ChatCompletionResult:
        model_id = model or "gemini-3.8-flash"
        payload = build_google_chat_payload(
            messages, model=model_id, temperature=temperature,
            reasoning_effort=reasoning_effort, search_grounding=search_grounding,
        )
        text_parts: list[str] = []
        citation_map: dict[str, dict[str, str]] = {}
        usage: dict[str, Any] = {}
        search_announced = False
        for chunk in self.client.stream_generate_content(model_id, payload):
            if stop_flag and stop_flag():
                break
            blocked = _blocked_reason(chunk)
            if blocked:
                raise ProviderError(
                    f"Google blocked the chat response ({blocked}).",
                    provider="google", category=ErrorCategory.SAFETY,
                    retryable=False, code=blocked,
                )
            delta = _chunk_text(chunk)
            if delta:
                text_parts.append(delta)
                if on_delta:
                    on_delta(delta, "".join(text_parts))
            for citation in _citations(chunk):
                citation_map[citation["url"]] = citation
            current_usage = _usage(chunk)
            if current_usage:
                usage = current_usage
            candidates = chunk.get("candidates") or []
            metadata = (candidates[0].get("groundingMetadata")
                        if isinstance(candidates, list) and candidates
                        and isinstance(candidates[0], dict) else None)
            queries = metadata.get("webSearchQueries") if isinstance(metadata, dict) else None
            if queries and on_tool and not search_announced:
                on_tool({"tool": "google_search", "status": "completed",
                         "query": str(queries[0])})
                search_announced = True
        full = "".join(text_parts)
        if not full and not (stop_flag and stop_flag()):
            raise ProviderError(
                "Google returned no chat text.", provider="google",
                category=ErrorCategory.REMOTE, retryable=True, code="NO_TEXT",
            )
        return ChatCompletionResult(
            text=full, citations=tuple(citation_map.values()), usage=usage,
            tool_calls=1 if search_announced else 0,
        )

    def complete_chat(
        self, messages: Iterable[dict[str, Any]], *, model: Optional[str] = None,
        **options: Any,
    ) -> str:
        return self.stream_chat(messages, model=model, **options).text
