"""Streaming czatu z tool-calls na xAI (akumulacja delt treści i tool_calls).

Zwraca pełną wiadomość asystenta: {"role":"assistant","content":..., "tool_calls":[...]}.
Dekoduje SSE jawnie jako UTF-8 (zasada z legacy — inaczej mojibake polskich znaków).
"""

from __future__ import annotations

import json
from typing import Callable, List, Optional

import requests  # type: ignore


def stream_chat_with_tools(
    api_key: str,
    base_url: str,
    messages: List[dict],
    model: str,
    temperature: float,
    tools: list,
    on_text: Optional[Callable[[str], None]] = None,
    stop_flag: Optional[Callable[[], bool]] = None,
) -> dict:
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": True,
        "tools": tools,
        "tool_choice": "auto",
    }
    # M17-B6: NIE dokładamy `stream_options.include_usage` do payloadu — to nowy parametr
    # na krytycznej ścieżce agenta, której nie da się zweryfikować w sandboxie (TLS),
    # a 400 zepsułby każdą turę. Jeśli serwer i tak wyśle `usage` w strumieniu — zbierzemy
    # je niżej (telemetria tokenów); telemetria tur/narzędzi (B6) działa niezależnie.
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    content = ""
    tool_calls: dict[int, dict] = {}
    usage: Optional[dict] = None

    with requests.post(f"{base_url}/chat/completions", headers=headers, json=payload,
                       stream=True, timeout=600) as r:
        r.raise_for_status()
        for raw in r.iter_lines(decode_unicode=False):
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
                usage = obj["usage"]  # zwykle w ostatnim chunku (include_usage)
            delta = (obj.get("choices") or [{}])[0].get("delta") or {}
            if delta.get("content"):
                content += delta["content"]
                if on_text:
                    on_text(content)
            for tcd in delta.get("tool_calls") or []:
                idx = tcd.get("index", 0)
                slot = tool_calls.setdefault(idx, {"id": None, "name": "", "args": ""})
                if tcd.get("id"):
                    slot["id"] = tcd["id"]
                fn = tcd.get("function") or {}
                if fn.get("name"):
                    slot["name"] = fn["name"]
                if fn.get("arguments"):
                    slot["args"] += fn["arguments"]

    msg: dict = {"role": "assistant", "content": content or None}
    if tool_calls:
        msg["tool_calls"] = [
            {
                "id": v["id"] or f"call_{i}",
                "type": "function",
                "function": {"name": v["name"], "arguments": v["args"] or "{}"},
            }
            for i, v in sorted(tool_calls.items())
        ]
    if usage is not None:
        # M17-B6: telemetria — AgentSession zdejmuje to pole przed zapisem do historii
        # (nie wraca do xAI). Brak usage → pole pominięte (mock LLM = 0 tokenów).
        msg["usage"] = usage
    return msg
