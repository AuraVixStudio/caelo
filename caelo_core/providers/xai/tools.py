"""xAI adapter for the coding-agent neutral tool-call contract.

The session never depends on the OpenAI-compatible wire format.  This module is
the only place which serializes neutral Caelo messages to xAI chat completions.
"""

from __future__ import annotations

import json
import logging
from typing import Callable, List, Optional

import requests  # type: ignore

from caelo_core import validation as V

log = logging.getLogger(__name__)


def _xai_messages(messages: List[dict]) -> List[dict]:
    """Strip provider-private replay data before crossing the xAI boundary."""
    allowed = {"role", "content", "name", "tool_calls", "tool_call_id"}
    return [{k: v for k, v in message.items() if k in allowed}
            for message in messages if isinstance(message, dict)]


def stream_chat_with_tools(
    api_key: str,
    base_url: str,
    messages: List[dict],
    model: str,
    temperature: float,
    tools: list,
    on_text: Optional[Callable[[str], None]] = None,
    stop_flag: Optional[Callable[[], bool]] = None,
    reasoning_effort: Optional[str] = None,
) -> dict:
    payload = {
        "model": model,
        "messages": _xai_messages(messages),
        "temperature": temperature,
        "stream": True,
        "tools": tools,
        "tool_choice": "auto",
    }
    eff = V.normalize_effort(reasoning_effort)
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    def _open(send_effort: bool):
        body = dict(payload)
        if send_effort and eff:
            body["reasoning_effort"] = eff
        return requests.post(f"{base_url}/chat/completions", headers=headers, json=body,
                             stream=True, timeout=600)

    content = ""
    tool_calls: dict[int, dict] = {}
    usage: Optional[dict] = None
    response = _open(bool(eff))
    if eff and getattr(response, "status_code", 200) in (400, 422):
        log.info("model %s rejected reasoning_effort=%s (HTTP %s); retrying without it",
                 model, eff, getattr(response, "status_code", "?"))
        response.close()
        response = _open(False)

    with response:
        response.raise_for_status()
        for raw in response.iter_lines(decode_unicode=False):
            if stop_flag and stop_flag():
                break
            if not raw:
                continue
            line = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else raw
            if line.startswith("data:"):
                line = line[5:].strip()
            if line == "[DONE]":
                break
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if isinstance(obj.get("usage"), dict):
                usage = obj["usage"]
            delta = (obj.get("choices") or [{}])[0].get("delta") or {}
            if delta.get("content"):
                content += delta["content"]
                if on_text:
                    on_text(content)
            for tool_delta in delta.get("tool_calls") or []:
                index = tool_delta.get("index", 0)
                slot = tool_calls.setdefault(index, {"id": None, "name": "", "args": ""})
                if tool_delta.get("id"):
                    slot["id"] = tool_delta["id"]
                function = tool_delta.get("function") or {}
                if function.get("name"):
                    slot["name"] = function["name"]
                if function.get("arguments"):
                    slot["args"] += function["arguments"]

    message: dict = {"role": "assistant", "content": content or None}
    if tool_calls:
        message["tool_calls"] = [
            {"id": value["id"] or f"call_{index}", "type": "function",
             "function": {"name": value["name"], "arguments": value["args"] or "{}"}}
            for index, value in sorted(tool_calls.items())
        ]
    if usage is not None:
        message["usage"] = usage
    return message
