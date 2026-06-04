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
a delty trafiają do kolejki asyncio (`call_soon_threadsafe`) i są wysyłane po WS.
Pętla odbioru działa równolegle z wysyłką, więc {"type":"stop"} dociera w trakcie
streamingu i ustawia flagę `stop_flag`. UTF-8 jest zachowane przez APIManager.

Autoryzacja: token w query (`?token=...`) — przeglądarkowy WebSocket nie pozwala
ustawić nagłówka Authorization.
"""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import config  # type: ignore

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

    loop = asyncio.get_running_loop()
    out_q: asyncio.Queue = asyncio.Queue(maxsize=512)  # P1-3: ograniczona (anty-OOM)
    current: dict = {"thread": None, "stop": None}     # P1-3: single-flight worker

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

    def emit(item: dict) -> bool:
        """Wstaw ramkę do kolejki z backpressure (wątek blokuje się, gdy pełna —
        ogranicza pamięć i tempo). False = konsument zniknął/timeout → przerwij."""
        try:
            asyncio.run_coroutine_threadsafe(out_q.put(item), loop).result(timeout=30)
            return True
        except Exception:
            return False

    def start_worker(messages, model: str, temperature: float) -> None:
        stop = threading.Event()        # P1-3: stop_event PER-REQUEST (bez clear() współdzielonego)
        current["stop"] = stop
        got = {"any": False}

        def on_delta(delta: str, _full: str) -> None:
            got["any"] = True
            # P1-3: wysyłaj PRZYROST (delta), nie skumulowane full (było O(n²) pasma).
            if not emit({"type": "delta", "delta": delta}):
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
                    emit({"type": "delta", "delta": full})
                emit({"type": "done", "full": full})
            except Exception as exc:  # noqa: BLE001
                emit({"type": "error", "error": str(exc)})

        t = threading.Thread(target=worker, daemon=True)
        current["thread"] = t
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
                    await ws.send_json({"type": "error",
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
        if current["stop"] is not None:
            current["stop"].set()
        t = current["thread"]
        if t is not None and t.is_alive():
            # P1-3: poczekaj na workera bez blokowania pętli zdarzeń (join w executorze).
            try:
                await loop.run_in_executor(None, t.join, 5)
            except Exception:
                pass
        sender_task.cancel()
        try:
            await sender_task
        except (asyncio.CancelledError, Exception):  # CancelledError to BaseException
            pass
