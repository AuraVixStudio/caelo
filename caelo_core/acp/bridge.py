"""Most: ramki `AgentRunner` → notyfikacje ACP `session/update` (M19-B2).

Mapuje zdarzenia pętli agenta (kontrakt z docstringu `routes/agent.py`) na zdarzenia
Agent Client Protocol. `frame_to_acp` zwraca pełną notyfikację JSON-RPC albo None, gdy
ramka nie ma odpowiednika strumieniowego (assistant_done/done/stopped/error — serwer
finalizuje je w `result`; checkpoint/subagent — pomijane w B2).

Kształty zgodne z dokumentacją „Building with Grok" (ACP) + bezpieczne pola dodatkowe
(`tool`/`arguments` obok `title`/`toolCallId`) — nadmiarowe pola są ignorowane przez klienta.
"""
from __future__ import annotations

from typing import Optional


def _notif(sid: str, update: dict) -> dict:
    return {"jsonrpc": "2.0", "method": "session/update",
            "params": {"sessionId": sid, "update": update}}


def frame_to_acp(sid: str, ev: dict, state: dict) -> Optional[dict]:
    """Ramka agenta → notyfikacja ACP (lub None). `state["prev"]` trzyma długość już
    wysłanego tekstu (ramka `text` niesie SKUMULOWANY `full` → liczymy deltę)."""
    t = ev.get("type")
    if t == "text":
        full = ev.get("full") or ""
        delta = full[state.get("prev", 0):]
        state["prev"] = len(full)
        if not delta:
            return None
        return _notif(sid, {"sessionUpdate": "agent_message_chunk",
                            "content": {"type": "text", "text": delta}})
    if t == "tool_call":
        return _notif(sid, {"sessionUpdate": "tool_call",
                            "toolCallId": ev.get("id"), "title": ev.get("name"),
                            "kind": "other", "status": "pending",
                            "tool": ev.get("name"), "arguments": ev.get("args")})
    if t == "tool_result":
        return _notif(sid, {"sessionUpdate": "tool_call_update",
                            "toolCallId": ev.get("id"),
                            "status": "completed" if ev.get("ok") else "failed",
                            "content": [{"type": "content", "content":
                                         {"type": "text", "text": ev.get("summary") or ""}}]})
    if t == "output":
        return _notif(sid, {"sessionUpdate": "tool_call_update",
                            "toolCallId": ev.get("id"),
                            "content": [{"type": "content", "content":
                                         {"type": "text", "text": ev.get("chunk") or ""}}]})
    return None


def stop_reason(internal: Optional[str]) -> str:
    """Wewnętrzny sygnał końca → `stopReason` ACP (enum: end_turn/cancelled/refusal/…)."""
    return {"stopped": "cancelled", "error": "refusal"}.get(internal or "", "end_turn")
