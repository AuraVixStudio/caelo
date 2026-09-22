"""Adapter Nano Banana przez generateContent (Vertex i AI Studio)."""

from __future__ import annotations

import base64
from typing import Any, Iterable

from caelo_core.providers.base import ImageGenerationRequest, ImageGenerationResult, MediaOutput
from caelo_core.providers.errors import ErrorCategory, ProviderError

from .client import GoogleClient


_ROLE_ORDER = ("starting_image", "character", "object", "style", "general")
_SAFETY_SETTINGS = (
    "HARM_CATEGORY_HARASSMENT",
    "HARM_CATEGORY_HATE_SPEECH",
    "HARM_CATEGORY_SEXUALLY_EXPLICIT",
    "HARM_CATEGORY_DANGEROUS_CONTENT",
)
_BLOCK_REASONS = {
    "SAFETY",
    "IMAGE_SAFETY",
    "BLOCKLIST",
    "PROHIBITED_CONTENT",
    "OTHER",
    "BLOCK_REASON_UNSPECIFIED",
    "BLOCKED_REASON_UNSPECIFIED",
}


def parse_data_uri(value: str, expected: str = "") -> tuple[str, str]:
    if not isinstance(value, str) or not value.startswith("data:") or ";base64," not in value:
        raise ProviderError("Google media inputs must be base64 data URIs", provider="google",
                            category=ErrorCategory.INVALID_INPUT)
    header, data = value.split(",", 1)
    mime = header[5:].split(";", 1)[0].lower()
    if expected and not mime.startswith(expected + "/"):
        raise ProviderError(f"Expected a {expected} input", provider="google",
                            category=ErrorCategory.INVALID_INPUT)
    try:
        base64.b64decode(data, validate=True)
    except Exception as exc:
        raise ProviderError("Invalid base64 media input", provider="google",
                            category=ErrorCategory.INVALID_INPUT, cause=exc) from exc
    return mime, data


def _walk(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def extract_inline_media(value: Any, prefix: str) -> list[MediaOutput]:
    """Wyciąga media inline z odpowiedzi, POMIJAJĄC części „myślowe".

    Modele Nano Banana z włączonym `thinkingConfig` zwracają w tej samej
    odpowiedzi robocze podglądy oznaczone `thought: true` — zawsze w 1K,
    niezależnie od `imageConfig.imageSize`. Finalny render jest OSTATNIM
    obrazem bez tej flagi; wzięcie pierwszego dawało wersję roboczą
    (czat już filtruje `thought` w `chat.py`/`tools.py` — tu tego brakowało).
    """
    outputs: list[MediaOutput] = []
    seen: set[str] = set()
    for node in _walk(value):
        inline = node.get("inlineData") or node.get("inline_data")
        if not isinstance(inline, dict):
            continue
        if node.get("thought") is True:
            continue
        data = inline.get("data")
        mime = str(inline.get("mimeType") or inline.get("mime_type") or "")
        if not isinstance(data, str) or not mime.startswith(prefix + "/"):
            continue
        fingerprint = f"{len(data)}:{data[:64]}"
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        raw = base64.b64decode(data)
        extension = ".jpg" if mime == "image/jpeg" else (".mp4" if prefix == "video" else ".png")
        outputs.append(MediaOutput(data=raw, mime_type=mime, extension=extension))
    return outputs


def _safety_block(value: Any) -> tuple[str, str] | None:
    """Zwraca bezpieczny komunikat i kod blokady bez ujawniania surowej odpowiedzi."""
    reasons: list[str] = []
    ratings: list[str] = []
    for node in _walk(value):
        for key in ("blockReason", "block_reason", "finishReason", "finish_reason"):
            raw = node.get(key)
            reason = str(raw or "").upper()
            if reason in _BLOCK_REASONS and reason not in reasons:
                reasons.append(reason)
        if node.get("blocked") is True:
            category = str(node.get("category") or "SAFETY").removeprefix("HARM_CATEGORY_")
            probability = str(node.get("probability") or node.get("severity") or "").upper()
            label = f"{category}={probability}" if probability else category
            if label not in ratings:
                ratings.append(label)

    if not reasons and not ratings:
        return None
    code = reasons[0] if reasons else "SAFETY"
    detail = ", ".join([*reasons, *ratings][:6])
    return f"Google blocked image generation ({detail})", code


def _role_hint(roles: tuple[str, ...]) -> str:
    counts = {role: roles.count(role) for role in set(roles)}
    hints = []
    if counts.get("starting_image"):
        hints.append("The first image is the starting image to edit.")
    if counts.get("character"):
        hints.append(f"{counts['character']} image(s) define character identity; keep it consistent.")
    if counts.get("object"):
        hints.append(f"{counts['object']} image(s) show objects that must appear as depicted.")
    if counts.get("style"):
        hints.append(f"{counts['style']} image(s) define visual style only, not content.")
    return " ".join(hints)


class GoogleImageProvider:
    provider_id = "google"

    def __init__(self, client: GoogleClient) -> None:
        self.client = client

    def validate_connection(self) -> dict[str, Any]:
        return self.client.validate_connection()

    def _payload(self, request: ImageGenerationRequest) -> dict[str, Any]:
        roles = request.reference_roles or tuple("general" for _ in request.images)
        paired = list(zip(request.images, roles))
        paired.sort(key=lambda pair: _ROLE_ORDER.index(pair[1]) if pair[1] in _ROLE_ORDER else 99)
        hint = _role_hint(tuple(role for _, role in paired))
        prompt = f"{request.prompt}\n\n{hint}" if hint else request.prompt
        parts: list[dict[str, Any]] = [{"text": prompt}]
        for image, _ in paired:
            mime, data = parse_data_uri(image, "image")
            parts.append({"inlineData": {"mimeType": mime, "data": data}})
        image_config: dict[str, Any] = {"personGeneration": "ALLOW_ADULT"}
        if request.aspect_ratio.lower() not in {"auto", "original"}:
            image_config["aspectRatio"] = request.aspect_ratio
        size = request.resolution.upper()
        if size == "0.5K":
            size = "1K"
        if size:
            image_config["imageSize"] = size
        if request.mime_type == "image/jpeg":
            image_config["outputMimeType"] = "image/jpeg"
        generation: dict[str, Any] = {"responseModalities": ["TEXT", "IMAGE"],
                                      "imageConfig": image_config}
        if request.thinking_level:
            generation["thinkingConfig"] = {"thinkingLevel": request.thinking_level}
        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": generation,
            "safetySettings": [
                {"category": category, "threshold": "OFF"}
                for category in _SAFETY_SETTINGS
            ],
        }
        if request.search_grounding:
            payload["tools"] = [{"googleSearch": {}}]
        return payload

    def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        if not request.model:
            raise ProviderError("Google image model is required", provider="google",
                                category=ErrorCategory.INVALID_INPUT)
        outputs: list[MediaOutput] = []
        metadata: dict[str, Any] = {"model": request.model, "transport": "generateContent"}
        for _ in range(max(1, request.count)):
            response = self.client.generate_content(request.model, self._payload(request))
            found = extract_inline_media(response, "image")
            if not found:
                blocked = _safety_block(response)
                raise ProviderError(
                    blocked[0] if blocked else
                    "Google completed without returning an image",
                    provider="google", category=ErrorCategory.SAFETY if blocked else ErrorCategory.REMOTE,
                    retryable=False if blocked else True,
                    code=blocked[1] if blocked else "NO_IMAGE",
                )
            # Finalny render to OSTATNI obraz w odpowiedzi (części „thought" są
            # już odfiltrowane) — pierwszy bywa roboczym podglądem w 1K.
            outputs.append(found[-1])
            metadata["response"] = response
        return ImageGenerationResult(tuple(outputs), metadata=metadata)
