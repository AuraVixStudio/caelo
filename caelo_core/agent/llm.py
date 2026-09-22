"""Neutralny kontrakt odpowiedzi modelu dla agenta kodowania (ADR-8).

Historia sesji używa jednego, serializowalnego kształtu niezależnie od providera.
Prywatne dane wymagane do poprawnego replayu (np. ``thoughtSignature`` Gemini)
żyją w ``provider_data`` i są ignorowane przez pętlę narzędziową.

``stream_chat_with_tools`` pozostaje kompatybilnym wejściem xAI dla starszych
transportów i testów. Właściwa serializacja drutu jest w providerze xAI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)

    def to_message_dict(self) -> dict[str, Any]:
        import json
        return {"id": self.id, "type": "function",
                "function": {"name": self.name,
                             "arguments": json.dumps(self.arguments, ensure_ascii=False)}}


@dataclass(frozen=True)
class AssistantTurn:
    content: Optional[str] = None
    tool_calls: tuple[ToolCall, ...] = ()
    usage: dict[str, Any] = field(default_factory=dict)
    provider_data: dict[str, Any] = field(default_factory=dict)

    def to_message_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            out["tool_calls"] = [call.to_message_dict() for call in self.tool_calls]
        if self.usage:
            out["usage"] = self.usage
        if self.provider_data:
            out["provider_data"] = self.provider_data
        return out


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
    from caelo_core.providers.xai.tools import stream_chat_with_tools as xai_stream
    return xai_stream(api_key, base_url, messages, model, temperature, tools,
                       on_text=on_text, stop_flag=stop_flag,
                       reasoning_effort=reasoning_effort)
