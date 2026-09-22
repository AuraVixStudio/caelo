"""OpenAI Responses function calling dla neutralnej pętli Code/Agent."""

from __future__ import annotations

import json
from typing import Any, Callable, Iterable, Optional

import requests  # type: ignore

from caelo_core import validation as V
from caelo_core.agent.llm import AssistantTurn, ToolCall
from caelo_core.models.pricing import openai_cost_from_usage
from caelo_core.providers import responses_transport
from caelo_core.providers.errors import normalize_provider_error

from .client import OPENAI_API_BASE


def _flat_tools(tools: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for definition in tools:
        if not isinstance(definition, dict):
            continue
        function = definition.get("function")
        function = function if isinstance(function, dict) else definition
        if not function.get("name"):
            continue
        out.append({
            "type": "function",
            "name": str(function["name"]),
            "description": str(function.get("description") or ""),
            "parameters": function.get("parameters") or {"type": "object"},
        })
    return out


def build_openai_agent_input(messages: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Przekształć neutralną historię Caelo do stateless Responses input.

    Surowy output poprzedniej odpowiedzi jest przechowywany w ``provider_data``.
    Dzięki temu encrypted reasoning items i natywne function calls mogą zostać
    odesłane dokładnie w wymaganej kolejności przy ``store:false``.
    """
    items: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role == "tool":
            call_id = str(message.get("tool_call_id") or "")
            if call_id:
                items.append({
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": str(message.get("content") or ""),
                })
            continue

        openai_data = (message.get("provider_data") or {}).get("openai")
        raw_output = openai_data.get("output") if isinstance(openai_data, dict) else None
        if role == "assistant" and isinstance(raw_output, list):
            items.extend(item for item in raw_output if isinstance(item, dict))
            continue

        converted = responses_transport.to_input([message])
        items.extend(converted)
        if role == "assistant":
            for call in message.get("tool_calls") or []:
                if not isinstance(call, dict):
                    continue
                function = call.get("function") or {}
                if not isinstance(function, dict) or not function.get("name"):
                    continue
                arguments = function.get("arguments") or "{}"
                if not isinstance(arguments, str):
                    arguments = json.dumps(arguments, ensure_ascii=False)
                items.append({
                    "type": "function_call",
                    "call_id": str(call.get("id") or ""),
                    "name": str(function["name"]),
                    "arguments": arguments,
                })
    return items


def _calls(output: Any) -> tuple[ToolCall, ...]:
    calls: list[ToolCall] = []
    for index, item in enumerate(output if isinstance(output, list) else []):
        if not isinstance(item, dict) or item.get("type") != "function_call":
            continue
        raw = item.get("arguments") or "{}"
        try:
            arguments = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, json.JSONDecodeError):
            arguments = {}
        if not isinstance(arguments, dict):
            arguments = {}
        calls.append(ToolCall(
            str(item.get("call_id") or item.get("id") or f"openai_call_{index}"),
            str(item.get("name") or ""),
            arguments,
        ))
    return tuple(call for call in calls if call.name)


def _text(output: Any) -> str:
    chunks: list[str] = []
    for item in output if isinstance(output, list) else []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if isinstance(part, dict) and part.get("type") in {"output_text", "text"}:
                if part.get("text"):
                    chunks.append(str(part["text"]))
    return "".join(chunks)


class OpenAIAgentTools:
    def __init__(self, api_key_provider: Callable[[], str]) -> None:
        self._api_key_provider = api_key_provider

    def stream_chat_with_tools(
        self, api_key: str, base_url: str, messages: list[dict[str, Any]], model: str,
        temperature: float, tools: list[dict[str, Any]],
        on_text: Optional[Callable[[str], None]] = None,
        stop_flag: Optional[Callable[[], bool]] = None,
        reasoning_effort: Optional[str] = None,
    ) -> dict[str, Any]:
        del api_key, base_url, temperature
        key = self._api_key_provider().strip()
        if not key:
            # Korzystamy z tego samego, znormalizowanego błędu co Settings/Chat.
            from caelo_core.providers.errors import ErrorCategory, ProviderError
            raise ProviderError(
                "OpenAI API key is not configured", provider="openai",
                category=ErrorCategory.AUTH, retryable=False, code="MISSING_API_KEY",
            )
        payload: dict[str, Any] = {
            "model": model,
            "input": build_openai_agent_input(messages),
            "stream": True,
            "store": False,
            "tools": _flat_tools(tools),
            "tool_choice": "auto",
            "include": ["reasoning.encrypted_content"],
        }
        effort = V.normalize_effort(reasoning_effort)
        if effort:
            payload["reasoning"] = {"effort": effort}

        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        text = ""
        usage: dict[str, Any] = {}
        output: list[dict[str, Any]] = []
        completed = False
        try:
            response = requests.post(
                f"{OPENAI_API_BASE}/responses", headers=headers, json=payload,
                stream=True, timeout=responses_transport.TIMEOUT_RESPONSES,
            )
            with response:
                response.raise_for_status()
                for raw in response.iter_lines(decode_unicode=False):
                    if stop_flag and stop_flag():
                        break
                    if not raw:
                        continue
                    line = raw.decode("utf-8", "replace") if isinstance(
                        raw, (bytes, bytearray)
                    ) else raw
                    if line.startswith("event:"):
                        continue
                    if line.startswith("data:"):
                        line = line[5:].strip()
                    if not line or line == "[DONE]":
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(event, dict):
                        continue
                    event_type = str(event.get("type") or "")
                    if event_type.endswith("output_text.delta"):
                        delta = event.get("delta")
                        if isinstance(delta, dict):
                            delta = delta.get("text")
                        if delta:
                            text += str(delta)
                            if on_text:
                                on_text(text)
                    elif event_type in {"response.output_item.done", "response.output_item.added"}:
                        item = event.get("item")
                        if event_type.endswith("done") and isinstance(item, dict):
                            output.append(item)
                    elif event_type == "response.completed" or event_type.endswith("response.done"):
                        completed = True
                        result = event.get("response") or event
                        if isinstance(result.get("usage"), dict):
                            usage = dict(result["usage"])
                        if isinstance(result.get("output"), list):
                            output = [item for item in result["output"] if isinstance(item, dict)]
                    elif event_type.endswith("error") or event.get("error"):
                        raise RuntimeError(str(event.get("error") or event.get("message") or "stream error"))
        except Exception as exc:  # noqa: BLE001
            raise normalize_provider_error(exc, "openai") from exc

        if not text:
            text = _text(output)
            if text and on_text:
                on_text(text)
        tool_calls = _calls(output)
        if not completed and not text and not tool_calls and not (stop_flag and stop_flag()):
            from caelo_core.providers.errors import ErrorCategory, ProviderError
            raise ProviderError(
                "OpenAI returned no agent text or function call.", provider="openai",
                category=ErrorCategory.REMOTE, retryable=True, code="NO_CONTENT",
            )
        cost = openai_cost_from_usage(model, usage)
        if cost is not None:
            usage["cost_usd"] = cost
        return AssistantTurn(
            content=text or None,
            tool_calls=tool_calls,
            usage=usage,
            provider_data={"openai": {"output": output}},
        ).to_message_dict()
