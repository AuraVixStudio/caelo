"""Gemini function-calling adapter for the neutral Caelo agent contract.

The adapter owns every Google-specific wire detail: function declarations,
functionCall/functionResponse parts, native call ids, thought signatures and
streamed partial arguments.  AgentSession only sees neutral assistant/tool
messages and therefore keeps the same approval, checkpoint and loop semantics.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any, Callable, Iterable, Optional

from caelo_core.agent.llm import AssistantTurn, ToolCall
from caelo_core.providers.errors import ErrorCategory, ProviderError

from .chat import _SAFETY_OFF, _blocked_reason, _message_parts, _usage
from .client import GoogleClient


def _declarations(tools: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    declarations: list[dict[str, Any]] = []
    for tool in tools:
        function = tool.get("function") if isinstance(tool, dict) else None
        if not isinstance(function, dict) or not function.get("name"):
            continue
        declaration: dict[str, Any] = {"name": str(function["name"])}
        if function.get("description"):
            declaration["description"] = str(function["description"])
        parameters = function.get("parameters")
        if isinstance(parameters, dict):
            declaration["parameters"] = copy.deepcopy(parameters)
        declarations.append(declaration)
    return declarations


def _tool_index(messages: Iterable[dict[str, Any]]) -> dict[str, str]:
    index: dict[str, str] = {}
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        for call in message.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            function = call.get("function") or {}
            call_id = str(call.get("id") or "")
            name = str(function.get("name") or "") if isinstance(function, dict) else ""
            if call_id and name:
                index[call_id] = name
    return index


def _assistant_parts(message: dict[str, Any]) -> list[dict[str, Any]]:
    google = (message.get("provider_data") or {}).get("google")
    content = google.get("content") if isinstance(google, dict) else None
    if isinstance(content, dict) and isinstance(content.get("parts"), list):
        # Exact replay is required for Gemini thought signatures.
        return copy.deepcopy(content["parts"])

    parts: list[dict[str, Any]] = []
    text = message.get("content")
    if isinstance(text, str) and text:
        parts.append({"text": text})
    for call in message.get("tool_calls") or []:
        if not isinstance(call, dict):
            continue
        function = call.get("function") or {}
        if not isinstance(function, dict) or not function.get("name"):
            continue
        raw_args = function.get("arguments") or "{}"
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        except json.JSONDecodeError:
            args = {"_raw": str(raw_args)}
        parts.append({"functionCall": {
            "id": str(call.get("id") or ""), "name": str(function["name"]),
            "args": args if isinstance(args, dict) else {"value": args},
        }})
    return parts


def build_google_agent_payload(
    messages: Iterable[dict[str, Any]], *, model: str, tools: Iterable[dict[str, Any]],
    temperature: float = 0.2, reasoning_effort: Optional[str] = None,
) -> dict[str, Any]:
    source = [message for message in messages if isinstance(message, dict)]
    names = _tool_index(source)
    contents: list[dict[str, Any]] = []
    system_parts: list[dict[str, str]] = []
    index = 0
    while index < len(source):
        message = source[index]
        role = str(message.get("role") or "user").lower()
        if role == "system":
            for part in _message_parts(message.get("content")):
                if "text" in part:
                    system_parts.append({"text": str(part["text"])})
            index += 1
            continue
        if role == "assistant":
            parts = _assistant_parts(message)
            if parts:
                contents.append({"role": "model", "parts": parts})
            index += 1
            continue
        if role == "tool":
            # Gemini requires parallel responses in one user turn and in call order.
            parts: list[dict[str, Any]] = []
            while index < len(source) and source[index].get("role") == "tool":
                tool_message = source[index]
                call_id = str(tool_message.get("tool_call_id") or "")
                name = str(tool_message.get("name") or names.get(call_id) or "tool")
                parts.append({"functionResponse": {
                    "id": call_id, "name": name,
                    "response": {"output": tool_message.get("content") or ""},
                }})
                index += 1
            contents.append({"role": "user", "parts": parts})
            continue
        parts = _message_parts(message.get("content"))
        if parts:
            contents.append({"role": "user", "parts": parts})
        index += 1

    if not contents:
        raise ValueError("Google agent requires at least one user message")
    payload: dict[str, Any] = {"contents": contents, "safetySettings": list(_SAFETY_OFF)}
    if system_parts:
        payload["systemInstruction"] = {"parts": system_parts}
    declarations = _declarations(tools)
    if declarations:
        payload["tools"] = [{"functionDeclarations": declarations}]
        payload["toolConfig"] = {
            "functionCallingConfig": {
                "mode": "AUTO",
                "streamFunctionCallArguments": True,
            },
        }
    generation: dict[str, Any] = {}
    if model.startswith("gemini-2."):
        generation["temperature"] = max(0.0, min(1.0, float(temperature)))
    effort = str(reasoning_effort or "").lower()
    if model.startswith("gemini-3") and effort in {"low", "medium", "high"}:
        generation["thinkingConfig"] = {"thinkingLevel": effort}
    if generation:
        payload["generationConfig"] = generation
    return payload


_PATH_TOKEN = re.compile(r"(?:^\$)|(?:\.([^\.\[]+))|(?:\[(\d+)\])|(?:\['([^']+)'\])")


def _path_tokens(path: str) -> list[Any]:
    tokens: list[Any] = []
    for match in _PATH_TOKEN.finditer(path or ""):
        key, array_index, quoted = match.groups()
        if key is not None:
            tokens.append(key)
        elif array_index is not None:
            tokens.append(int(array_index))
        elif quoted is not None:
            tokens.append(quoted)
    return tokens


def _partial_value(item: dict[str, Any]) -> Any:
    for key in ("value", "stringValue", "numberValue", "boolValue", "objectValue", "arrayValue"):
        if key in item:
            return item[key]
    if "nullValue" in item:
        return None
    return None


def _set_partial(root: dict[str, Any], path: str, value: Any) -> None:
    tokens = _path_tokens(path)
    if not tokens:
        if isinstance(value, dict):
            root.update(value)
        return
    node: Any = root
    for position, token in enumerate(tokens):
        last = position == len(tokens) - 1
        next_token = tokens[position + 1] if not last else None
        if isinstance(token, int):
            if not isinstance(node, list):
                return
            while len(node) <= token:
                node.append([] if isinstance(next_token, int) else {})
            if last:
                old = node[token]
                node[token] = old + value if isinstance(old, str) and isinstance(value, str) else value
            else:
                node = node[token]
        else:
            if not isinstance(node, dict):
                return
            if last:
                old = node.get(token)
                node[token] = old + value if isinstance(old, str) and isinstance(value, str) else value
            else:
                expected = [] if isinstance(next_token, int) else {}
                if not isinstance(node.get(token), type(expected)):
                    node[token] = expected
                node = node[token]


def _merge_partial_args(target: dict[str, Any], partials: Any) -> None:
    if not isinstance(partials, list):
        return
    for item in partials:
        if isinstance(item, dict):
            _set_partial(target, str(item.get("jsonPath") or item.get("path") or "$"),
                         _partial_value(item))


def _parts(chunk: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = chunk.get("candidates") or []
    if not isinstance(candidates, list) or not candidates or not isinstance(candidates[0], dict):
        return []
    content = candidates[0].get("content") or {}
    parts = content.get("parts") if isinstance(content, dict) else None
    return [part for part in (parts or []) if isinstance(part, dict)]


class GoogleAgentTools:
    def __init__(self, client: GoogleClient) -> None:
        self.client = client

    def stream_chat_with_tools(
        self, api_key: str, base_url: str, messages: list[dict[str, Any]], model: str,
        temperature: float, tools: list[dict[str, Any]],
        on_text: Optional[Callable[[str], None]] = None,
        stop_flag: Optional[Callable[[], bool]] = None,
        reasoning_effort: Optional[str] = None,
    ) -> dict[str, Any]:
        del api_key, base_url  # Auth and endpoint selection belong to GoogleClient.
        payload = build_google_agent_payload(
            messages, model=model, tools=tools, temperature=temperature,
            reasoning_effort=reasoning_effort,
        )
        text = ""
        calls: list[dict[str, Any]] = []
        slots: dict[str, dict[str, Any]] = {}
        positional_slots: dict[int, str] = {}
        replay_parts: list[dict[str, Any]] = []
        usage: dict[str, Any] = {}
        for chunk in self.client.stream_generate_content(model, payload):
            if stop_flag and stop_flag():
                break
            blocked = _blocked_reason(chunk)
            if blocked:
                raise ProviderError(
                    f"Google blocked the agent response ({blocked}).", provider="google",
                    category=ErrorCategory.SAFETY, retryable=False, code=blocked,
                )
            current_usage = _usage(chunk)
            if current_usage:
                usage = current_usage
            for part_index, part in enumerate(_parts(chunk)):
                if part.get("text") and not part.get("thought"):
                    text += str(part["text"])
                    if on_text:
                        on_text(text)
                function_call = part.get("functionCall")
                if not isinstance(function_call, dict):
                    continue
                native_id = str(function_call.get("id") or "")
                name = str(function_call.get("name") or "")
                partials = function_call.get("partialArgs")
                args = function_call.get("args")
                has_data = bool(native_id or name or isinstance(args, dict)
                                or isinstance(partials, list) and partials)
                if not has_data:
                    # Gemini closes streamed calls with an empty functionCall part.
                    continue
                if native_id:
                    key = native_id
                elif part_index in positional_slots:
                    key = positional_slots[part_index]
                elif len(slots) == 1 and not name:
                    key = next(iter(slots))
                else:
                    key = f"{name}:{part_index}"
                if key not in slots:
                    call_id = native_id or f"google_call_{len(slots)}"
                    slot = {"id": call_id, "name": name, "args": {}, "signature": None}
                    slots[key] = slot
                    calls.append(slot)
                positional_slots[part_index] = key
                slot = slots[key]
                if name:
                    slot["name"] = name
                if isinstance(args, dict):
                    slot["args"] = copy.deepcopy(args)
                _merge_partial_args(slot["args"], partials)
                if part.get("thoughtSignature"):
                    slot["signature"] = part["thoughtSignature"]

        for call in calls:
            function_part: dict[str, Any] = {"functionCall": {
                "id": call["id"], "name": call["name"], "args": call["args"],
            }}
            if call.get("signature"):
                function_part["thoughtSignature"] = call["signature"]
            replay_parts.append(function_part)
        if text:
            replay_parts.insert(0, {"text": text})
        if not text and not calls and not (stop_flag and stop_flag()):
            raise ProviderError(
                "Google returned no agent text or function call.", provider="google",
                category=ErrorCategory.REMOTE, retryable=True, code="NO_CONTENT",
            )
        turn = AssistantTurn(
            content=text or None,
            tool_calls=tuple(ToolCall(call["id"], call["name"], call["args"])
                             for call in calls),
            usage=usage,
            provider_data={"google": {"content": {"role": "model", "parts": replay_parts}}},
        )
        return turn.to_message_dict()
