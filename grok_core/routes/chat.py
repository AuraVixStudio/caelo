"""WebSocket czatu ze streamingiem (SSE -> WS).

Protokół (JSON tekstowe ramki):
  klient -> serwer:
    {"type":"chat","messages":[...],"model":"...","temperature":0.7,"system_prompt":"..."}
    {"type":"stop"}                      # przerwij bieżące generowanie
  serwer -> klient:
    {"type":"delta","delta":"<przyrost treści>"}   # przyrostowo — klient skleja
    {"type":"done","full":"<pełna odpowiedź>"}
    {"type":"error","error":"..."}

Most streamingu: blokujące `APIManager.chat_completion_stream` biegnie w wątku,
a delty trafiają do `WsStream` (ograniczona kolejka + backpressure, P1-3) i są
wysyłane po WS. Pętla odbioru działa równolegle z wysyłką, więc {"type":"stop"}
dociera w trakcie streamingu i ustawia flagę `stop_flag`. UTF-8 jest zachowane
przez APIManager.

Autoryzacja: token w query (`?token=...`) — przeglądarkowy WebSocket nie pozwala
ustawić nagłówka Authorization.
"""

from __future__ import annotations

import json
import threading

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import config  # type: ignore

from grok_core.routes._ws import WsStream
from grok_core.state import ws_authorized

router = APIRouter()


@router.websocket("/chat/stream")
async def chat_stream(ws: WebSocket) -> None:
    if not ws_authorized(ws):  # P0-8: fail-closed token + Origin
        await ws.close(code=1008)  # policy violation (przed accept -> odmowa handshake)
        return

    await ws.accept()
    backend = getattr(ws.app.state, "backend", None)
    if backend is None:
        await ws.send_json({"type": "error", "error": "Backend not initialized"})
        await ws.close()
        return

    current: dict = {"thread": None, "stop": None}  # P1-3: single-flight worker

    async with WsStream(ws) as stream:

        def start_worker(messages, model: str, temperature: float) -> None:
            stop = threading.Event()        # P1-3: stop_event PER-REQUEST
            current["stop"] = stop
            got = {"any": False}

            def on_delta(delta: str, _full: str) -> None:
                got["any"] = True
                # P1-3: wysyłaj PRZYROST (delta), nie skumulowane full (było O(n²) pasma).
                if not stream.emit({"type": "delta", "delta": delta}):
                    stop.set()  # konsument zniknął → przerwij streaming z xAI

            def worker() -> None:
                try:
                    try:
                        full = backend.api.chat_completion_stream(
                            messages, model=model, temperature=temperature,
                            on_delta=on_delta, stop_flag=stop.is_set,
                        )
                    except Exception:
                        if got["any"]:
                            raise
                        # Fallback nie-streamingowy (jak w app._worker_chat).
                        full = backend.api.chat_completion(
                            messages, model=model, temperature=temperature
                        )
                        stream.emit({"type": "delta", "delta": full})
                    stream.emit({"type": "done", "full": full})
                except Exception as exc:  # noqa: BLE001
                    stream.emit({"type": "error", "error": str(exc)})

            t = threading.Thread(target=worker, daemon=True)
            current["thread"] = t
            stream.track(t)   # P0-9: dołączony przy zamykaniu (bez pracy po rozłączeniu)
            t.start()

        def _busy() -> bool:
            t = current["thread"]
            return t is not None and t.is_alive()

        try:
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                mtype = msg.get("type")
                if mtype == "stop":
                    if current["stop"] is not None:
                        current["stop"].set()   # P1-3: zatrzymaj bieżący request (nie czyść!)
                elif mtype == "chat":
                    if _busy():
                        # P1-3: single-flight — nie startuj drugiego workera na tej samej kolejce.
                        await stream.send({"type": "error",
                                           "error": "A response is already streaming; send 'stop' first."})
                        continue
                    messages = list(msg.get("messages") or [])
                    system_prompt = (msg.get("system_prompt") or "").strip()
                    if system_prompt:
                        messages = [{"role": "system", "content": system_prompt}] + messages
                    model = msg.get("model") or backend.read_settings().get(
                        "chat_model"
                    ) or config.DEFAULT_CHAT_MODEL
                    try:
                        temperature = float(msg.get("temperature", 0.7))
                    except (TypeError, ValueError):
                        temperature = 0.7  # złe temperature nie może wywrócić pętli odbioru (por. P1-8)
                    start_worker(messages, model, temperature)
        except WebSocketDisconnect:
            pass
        finally:
            # P1-3: zatrzymaj bieżący request; WsStream.aclose() dołączy workera
            # (≤5 s) i domknie sender — bez czytania z xAI po rozłączeniu.
            if current["stop"] is not None:
                current["stop"].set()
