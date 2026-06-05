"""WebSocket agenta kodowania: /agent/stream.

Protokół (JSON):
  klient -> serwer:
    {"type":"workspace","path":"C:/..."}          # ustaw katalog roboczy
    {"type":"message","text":"...","model":"...","mode":"ask"}  # nowa tura agenta
    {"type":"approval","id":"<call_id>","decision":"accept|reject|always"}
    {"type":"stop"}
  serwer -> klient:
    {"type":"workspace","path":"..."}
    {"type":"text","full":"..."}                  # strumień tekstu modelu
    {"type":"tool_call","id","name","args"}
    {"type":"approval_request","id","name","detail":{kind,diff|command|binary,...}}
    {"type":"checkpoint","id","label","created_at"}  # M13-B3: powstał checkpoint
    {"type":"output","id","chunk"}                # wyjście run_command
    {"type":"tool_result","id","ok","summary"}
    {"type":"assistant_done","content"} / {"type":"stopped"} / {"type":"error","error"}
    {"type":"done"}                               # koniec tury

M13: ramka message niesie "mode" (ask/accept-edits/plan/bypass) — jak „Mode" w
Claude Code: plan = tylko READONLY (mutacje blokowane), accept-edits = auto write/
edit, bypass = auto wszystko. M13-B3: checkpointy tworzy menedżer współdzielony
przez Backend (REST /agent/undo cofa to, co tu zsnapshotowano).

Most: tura agenta biegnie w wątku (blokujące LLM + narzędzia). Zdarzenia trafiają
do `WsStream` (ograniczona kolejka + backpressure — P0-9) i są wysyłane po WS.
`approval_request` blokuje wątek na threading.Event aż dotrze {"type":"approval"}.
Na rozłączeniu `WsStream.aclose()` DOŁĄCZA wątek tury (≤5 s) — agent nie pisze
plików ani nie uruchamia komend po zniknięciu socketu (P0-9).
"""

from __future__ import annotations

import logging
import json
import threading
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import config  # type: ignore

from grok_core.agent.llm import stream_chat_with_tools
from grok_core.agent.session import AgentSession
from grok_core.routes._ws import WsStream
from grok_core.state import ws_authorized

log = logging.getLogger(__name__)

# P1-12: górny limit oczekiwania na decyzję zatwierdzenia. Bez niego wątek tury
# blokował się na `event.wait()` bez końca (gdyby `finally` go nie odblokował) —
# trzymając workspace. Timeout = traktuj jak „reject".
APPROVAL_TIMEOUT_S = 600  # 10 min — z zapasem na realną reakcję człowieka

router = APIRouter()


@router.websocket("/agent/stream")
async def agent_stream(ws: WebSocket) -> None:
    if not ws_authorized(ws):  # P0-8: fail-closed token + Origin
        await ws.close(code=1008)
        return

    await ws.accept()
    backend = getattr(ws.app.state, "backend", None)
    if backend is None:
        await ws.send_json({"type": "error", "error": "Backend not initialized"})
        await ws.close()
        return

    pending: dict[str, dict] = {}
    stop_event = threading.Event()
    gate = backend.permissions  # trwała allowlista współdzielona z REST /permissions
    state = {"session": None, "busy": False}

    async with WsStream(ws) as stream:

        def emit(ev: dict) -> None:
            # Z wątku-workera (tura agenta). Gdy konsument zniknął → ustaw Stop,
            # żeby pętla agenta przerwała się przy najbliższym sprawdzeniu (P0-9).
            if ev.get("type") == "assistant_done":  # M9-B2: złap finalną odpowiedź tury
                state["last_assistant"] = ev.get("content") or ""
            if not stream.emit(ev):
                stop_event.set()

        def request_approval(call_id: str, name: str, detail: Optional[dict]) -> str:
            event = threading.Event()
            pending[call_id] = {"event": event, "decision": "reject"}
            emit({"type": "approval_request", "id": call_id, "name": name, "detail": detail})
            # P1-12: timeout → domyślna decyzja „reject" (z pending). Brak limitu
            # mógł zakleszczyć wątek tury na zawsze.
            if not event.wait(timeout=APPROVAL_TIMEOUT_S):
                log.warning("Approval for %s (%s) timed out → reject", name, call_id)
            return pending.pop(call_id, {}).get("decision", "reject")

        def run_turn(text: str, model: str, images: list, mode: str = "ask") -> None:
            state["busy"] = True
            state["last_assistant"] = ""  # M9-B2: reset przed turą
            try:
                ws_obj = backend.get_workspace()
                if ws_obj is None:
                    emit({"type": "error", "error": "No workspace selected"})
                    return
                session = state["session"]
                if session is None:
                    session = AgentSession(
                        ws_obj, gate, stream_chat_with_tools, backend.get_api_key,
                        config.API_BASE, emit=emit, request_approval=request_approval,
                        checkpoints_provider=backend.get_checkpoints,  # M13-B3/B5
                        mcp=backend.mcp,        # M14-B2: narzędzia MCP w agencie
                        hooks=backend.hooks,    # M14-B5: hooki cyklu życia narzędzi
                        skills=backend.skills,  # M14-B6: wstrzykiwanie skilli do promptu
                    )
                    state["session"] = session
                else:
                    session.ws = ws_obj  # workspace mógł się zmienić
                stop_event.clear()
                session.run_turn(text, model, stop_flag=stop_event.is_set, images=images,
                                 mode=mode)
            except Exception:  # noqa: BLE001
                # P1-13: nie wysyłaj surowego str(exc) (może zawierać szczegóły xAI/
                # ścieżki). Loguj pełny ślad, do klienta — ogólny komunikat.
                log.exception("Agent turn failed")
                emit({"type": "error", "error": "Agent error (see server log for details)"})
            finally:
                state["busy"] = False
                # M9-B2: podsumowanie tury agenta do wspólnej historii huba (mode=code).
                # Tekst = finalna odpowiedź agenta; instrukcja usera + workspace w meta.
                if text or state.get("last_assistant"):
                    wsp = backend.get_workspace()
                    backend.record_event(
                        mode="code", text=state.get("last_assistant") or "",
                        meta={"prompt": text, "model": model,
                              "workspace": wsp.root.as_posix() if wsp else None},
                    )
                emit({"type": "done"})

        try:
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                mtype = msg.get("type")
                if mtype == "workspace":
                    # Ramki sterujące z PĘTLI ZDARZEŃ → await send (emit() z pętli
                    # zakleszczyłby się na własnej korutynie).
                    try:
                        backend.set_workspace(msg["path"])
                        await stream.send({"type": "workspace",
                                           "path": backend.get_workspace().root.as_posix()})
                    except Exception as exc:  # noqa: BLE001
                        await stream.send({"type": "error", "error": str(exc)})
                elif mtype == "message":
                    if state["busy"]:
                        await stream.send({"type": "error", "error": "Agent is busy"})
                        continue
                    text = msg.get("text", "")
                    images = msg.get("images") or []
                    # M13: tryb agenta (ask/accept-edits/plan/bypass); wstecznie „plan":true.
                    mode = msg.get("mode") or ("plan" if msg.get("plan") else "ask")
                    model = (
                        msg.get("model")
                        or backend.read_settings().get("code_model")
                        or "grok-build-0.1"
                    )
                    t = threading.Thread(target=run_turn, args=(text, model, images, mode),
                                         daemon=True)
                    stream.track(t)   # P0-9: dołączony przy zamykaniu
                    t.start()
                elif mtype == "approval":
                    slot = pending.get(msg.get("id"))
                    if slot:
                        slot["decision"] = msg.get("decision", "reject")
                        slot["event"].set()
                elif mtype == "stop":
                    stop_event.set()
        except WebSocketDisconnect:
            pass
        finally:
            # Najpierw odblokuj wszystko, co czeka — by worker mógł się domknąć,
            # zanim WsStream.aclose() go dołączy (P0-9).
            stop_event.set()
            for slot in pending.values():
                slot["event"].set()
