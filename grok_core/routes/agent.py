"""WebSocket agenta kodowania: /agent/stream.

Protokół (JSON):
  klient -> serwer:
    {"type":"workspace","path":"C:/..."}          # ustaw katalog roboczy
    {"type":"message","text":"...","model":"..."} # nowa tura agenta
    {"type":"approval","id":"<call_id>","decision":"accept|reject|always"}
    {"type":"stop"}
  serwer -> klient:
    {"type":"workspace","path":"..."}
    {"type":"text","full":"..."}                  # strumień tekstu modelu
    {"type":"tool_call","id","name","args"}
    {"type":"approval_request","id","name","detail":{kind,diff|command,...}}
    {"type":"output","id","chunk"}                # wyjście run_command
    {"type":"tool_result","id","ok","summary"}
    {"type":"assistant_done","content"} / {"type":"stopped"} / {"type":"error","error"}
    {"type":"done"}                               # koniec tury

Most: tura agenta biegnie w wątku (blokujące LLM + narzędzia). Zdarzenia trafiają
do kolejki asyncio (call_soon_threadsafe) i są wysyłane po WS. `approval_request`
blokuje wątek na threading.Event aż dotrze {"type":"approval"}.
"""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import config  # type: ignore

from grok_core.agent.llm import stream_chat_with_tools
from grok_core.agent.session import AgentSession
from grok_core.state import ws_authorized

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

    loop = asyncio.get_running_loop()
    out_q: asyncio.Queue = asyncio.Queue()
    pending: dict[str, dict] = {}
    stop_event = threading.Event()
    gate = backend.permissions  # trwała allowlista współdzielona z REST /permissions
    state = {"session": None, "busy": False}

    async def sender() -> None:
        while True:
            item = await out_q.get()
            if item is None:
                return
            try:
                await ws.send_json(item)
            except Exception:
                return

    sender_task = asyncio.create_task(sender())

    def emit(ev: dict) -> None:
        loop.call_soon_threadsafe(out_q.put_nowait, ev)

    def request_approval(call_id: str, name: str, detail: Optional[dict]) -> str:
        event = threading.Event()
        pending[call_id] = {"event": event, "decision": "reject"}
        emit({"type": "approval_request", "id": call_id, "name": name, "detail": detail})
        event.wait()
        return pending.pop(call_id, {}).get("decision", "reject")

    def run_turn(text: str, model: str, images: list) -> None:
        state["busy"] = True
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
                )
                state["session"] = session
            else:
                session.ws = ws_obj  # workspace mógł się zmienić
            stop_event.clear()
            session.run_turn(text, model, stop_flag=stop_event.is_set, images=images)
        except Exception as exc:  # noqa: BLE001
            emit({"type": "error", "error": str(exc)})
        finally:
            state["busy"] = False
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
                try:
                    backend.set_workspace(msg["path"])
                    emit({"type": "workspace", "path": backend.get_workspace().root.as_posix()})
                except Exception as exc:  # noqa: BLE001
                    emit({"type": "error", "error": str(exc)})
            elif mtype == "message":
                if state["busy"]:
                    emit({"type": "error", "error": "Agent is busy"})
                    continue
                text = msg.get("text", "")
                images = msg.get("images") or []
                model = (
                    msg.get("model")
                    or backend.read_settings().get("code_model")
                    or "grok-build-0.1"
                )
                threading.Thread(target=run_turn, args=(text, model, images), daemon=True).start()
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
        stop_event.set()
        for slot in pending.values():
            slot["event"].set()
        out_q.put_nowait(None)
        try:
            await sender_task
        except Exception:
            pass
