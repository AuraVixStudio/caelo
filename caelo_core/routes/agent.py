"""WebSocket agenta kodowania: /agent/stream.

Protokół (JSON):
  klient -> serwer:
    {"type":"workspace","path":"C:/..."}          # ustaw katalog roboczy
    {"type":"message","text":"...","model":"...","mode":"ask","effort":"high"}  # nowa tura agenta (effort: M19-B9, opcjonalny)
    {"type":"approval","id":"<call_id>","decision":"accept|reject|always"}
    {"type":"session","id":"<sid>"|null}          # M21: wznów sesję (id) / nowa (null)
    {"type":"stop"}
  serwer -> klient:
    {"type":"workspace","path":"..."}
    {"type":"session","id":"<sid>"}               # M21: aktywne id trwałej sesji
    {"type":"text","full":"..."}                  # strumień tekstu modelu
    {"type":"tool_call","id","name","args"}
    {"type":"approval_request","id","name","detail":{kind,diff|command|binary,...}}
    {"type":"checkpoint","id","label","created_at"}  # M13-B3: powstał checkpoint
    {"type":"output","id","chunk"}                # wyjście run_command
    {"type":"tool_result","id","ok","summary"}
    {"type":"plan","items":[{"content","status":"pending|in_progress|completed"}]}  # TOP3: live checklist (update_plan)
    {"type":"assistant_done","content"} / {"type":"stopped"} / {"type":"error","error"}
    {"type":"info","text","level":"info|warn"}    # miękka notka (np. limit kroków)
    {"type":"usage","input_tokens","output_tokens","context_tokens","max_context"}  # licznik + miernik kontekstu
    {"type":"done"}                               # koniec tury
    # M17 — zespół subagentów (multipleks po agent_id na tym samym WsStream):
    {"type":"subagent","agent_id","role","task","event":{<zagnieżdżona ramka subagenta>}}
    {"type":"subagent_status","agent_id","role","task","status","summary","merge_id",...}
    {"type":"team_done","report":{subagents,totals,errors}}  # koniec przebiegu delegate
    # approval_request subagenta niesie w detail: agent_id/role/task (atrybucja, F3)

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
import secrets
import threading
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from caelo_core import validation as V
from caelo_core.agent.runner import AgentRunner
from caelo_core.errors import masked_error
from caelo_core.routes._ws import WsStream
from caelo_core.state import ws_authorized

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
    # M19-§0: tylko flaga zajętości zostaje w warstwie transportu; model/tryb/sesja/
    # zespół i finalna odpowiedź tury żyją w AgentRunner.
    state = {"busy": False}

    async with WsStream(ws) as stream:

        def emit(ev: dict) -> None:
            # Z wątku-workera (tura agenta). Gdy konsument zniknął → ustaw Stop,
            # żeby pętla agenta przerwała się przy najbliższym sprawdzeniu (P0-9).
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

        # M19-§0: wspólne okablowanie sesji (leniwa AgentSession + TeamManager +
        # delegacja + zapis tury). Ten sam runner obsłuży headless (B1) i ACP (B2).
        # M21: każde połączenie zaczyna od świeżej trwałej sesji (id generowane tu);
        # runner utrwala pełną historię po każdej turze, a klient może ją wznowić.
        runner = AgentRunner(backend, emit=emit, request_approval=request_approval,
                             stop=stop_event.is_set, session_id=secrets.token_urlsafe(8))

        def run_turn(text: str, model: str, images: list, mode: str = "ask",
                     reasoning_effort: Optional[str] = None) -> None:
            state["busy"] = True
            try:
                stop_event.clear()  # nowa tura zaczyna od czystej flagi Stop
                runner.run_turn(text, model, images=images, mode=mode,
                                reasoning_effort=reasoning_effort)
            finally:
                state["busy"] = False
                # Licznik tokenów + miernik okna kontekstowego po turze.
                u = runner.usage
                emit({"type": "usage", "input_tokens": u["input_tokens"],
                      "output_tokens": u["output_tokens"],
                      "context_tokens": u["context_tokens"],
                      "max_context": u["max_context"]})
                emit({"type": "done"})

        # M21: powiadom klienta o aktywnym id sesji (UI śledzi je do listy/wznawiania).
        await stream.send({"type": "session", "id": runner.current_session_id})

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
                        await stream.send({"type": "error",
                                           "error": masked_error(exc, "Could not set workspace")})
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
                    # M19-B9: reasoning_effort z ramki (selektor UI agenta) z fallbackiem
                    # na ustawienie `code_effort`; niepoprawne → None (pole pominięte).
                    effort = V.normalize_effort(
                        msg.get("effort") or backend.read_settings().get("code_effort"))
                    t = threading.Thread(target=run_turn,
                                         args=(text, model, images, mode, effort),
                                         daemon=True)
                    stream.track(t)   # P0-9: dołączony przy zamykaniu
                    t.start()
                elif mtype == "approval":
                    slot = pending.get(msg.get("id"))
                    if slot:
                        slot["decision"] = msg.get("decision", "reject")
                        slot["event"].set()
                elif mtype == "session":
                    # M21: wznów zapisaną sesję (id) lub zacznij nową (null). Odrzuć
                    # w trakcie tury — podmiana historii pod biegnącym agentem byłaby
                    # niespójna (klient i tak blokuje Open/New gdy busy).
                    if state["busy"]:
                        await stream.send({"type": "error", "error": "Agent is busy"})
                        continue
                    sid = msg.get("id")
                    if sid:
                        from caelo_core.agent import sessions
                        data = sessions.load(str(sid))
                        if not data:
                            await stream.send({"type": "error", "error": "Session not found"})
                            continue
                        runner.resume_session(str(sid), data.get("history") or [])
                        await stream.send({"type": "session", "id": str(sid)})
                    else:
                        await stream.send({"type": "session", "id": runner.new_session()})
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
