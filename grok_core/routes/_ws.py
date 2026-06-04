"""Wspólny szkielet streamingu po WebSocket (P2-12).

Powtarzalny wzorzec dla `/chat/stream`, `/agent/stream` i `/terminal`:
- **ograniczona** kolejka asyncio (anty-OOM — P1-3/P0-9),
- zadanie `sender` wypychające ramki na WS,
- threadsafe `emit` z backpressure dla wątków-workerów,
- sprzątanie: **join workerów** (bez pracy po rozłączeniu) + domknięcie sendera.

Powód wydzielenia: fix kolejki/sprzątania był w `chat.py`, ale NIE przeniesiono go
do bliźniaczego `agent.py` (kolejka bez limitu + worker bez join → OOM i pisanie
plików/uruchamianie komend po zniknięciu socketu). Trzymanie wzorca w JEDNYM
miejscu uniemożliwia taki rozjazd.

Reguły wątków:
- `emit(item) -> bool` — wołać z **wątku-workera**. Blokuje, gdy kolejka pełna
  (backpressure). `False` = konsument zniknął/timeout → wątek powinien przerwać.
- `await send(item)` — wołać z **pętli zdarzeń** (handler). `emit()` z pętli
  zakleszczyłby się (czeka na korutynę tej samej pętli) — dlatego osobna ścieżka.
- `track(thread)` — zarejestruj worker; `aclose()` go dołączy (≤ JOIN_TIMEOUT_S).
"""

from __future__ import annotations

import asyncio
import threading
from typing import List, Optional

from fastapi import WebSocket

DEFAULT_MAXSIZE = 512   # P1-3/P0-9: twardy limit ramek w pamięci
EMIT_TIMEOUT_S = 30.0   # max blokady workera, gdy konsument nie nadąża/zniknął
JOIN_TIMEOUT_S = 5.0    # max oczekiwania na worker przy zamykaniu


class WsStream:
    def __init__(self, ws: WebSocket, *, maxsize: int = DEFAULT_MAXSIZE,
                 emit_timeout: float = EMIT_TIMEOUT_S) -> None:
        self.ws = ws
        self.loop = asyncio.get_running_loop()
        self.out_q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._emit_timeout = emit_timeout
        self._sender_task: Optional[asyncio.Task] = None
        self._workers: List[threading.Thread] = []

    async def __aenter__(self) -> "WsStream":
        self._sender_task = asyncio.create_task(self._sender())
        return self

    async def __aexit__(self, *_exc) -> None:
        await self.aclose()

    async def _sender(self) -> None:
        while True:
            item = await self.out_q.get()
            if item is None:
                return
            try:
                await self.ws.send_json(item)
            except Exception:
                return  # WS zamknięty — przestań wysyłać (worker dostanie False)

    def emit(self, item: dict) -> bool:
        """Z wątku-workera: wstaw ramkę z backpressure. False = przerwij streaming."""
        try:
            asyncio.run_coroutine_threadsafe(
                self.out_q.put(item), self.loop
            ).result(timeout=self._emit_timeout)
            return True
        except Exception:
            return False

    async def send(self, item: dict) -> None:
        """Z pętli zdarzeń: wstaw ramkę (backpressure przez await, bez deadlocku)."""
        await self.out_q.put(item)

    def track(self, thread: threading.Thread) -> None:
        """Zarejestruj wątek-worker do join na zamknięciu. Czyści już zakończone,
        by lista nie rosła przez długą sesję (wiele tur)."""
        self._workers = [t for t in self._workers if t.is_alive()]
        self._workers.append(thread)

    async def aclose(self) -> None:
        # 1) Dołącz workery, ZANIM przerwiemy sender — niech naturalnie dopną
        #    backpressure i przestaną działać. Wołający MUSI najpierw ustawić swój
        #    stop/Event (w `finally`), inaczej join czeka pełne JOIN_TIMEOUT_S.
        for t in self._workers:
            if t.is_alive():
                try:
                    await self.loop.run_in_executor(None, t.join, JOIN_TIMEOUT_S)
                except Exception:
                    pass
        self._workers.clear()
        # 2) Domknij sender (anuluj — kolejka mogła być pełna, więc sentinel None
        #    mógłby się nie zmieścić; klient i tak już zniknął).
        if self._sender_task is not None:
            self._sender_task.cancel()
            try:
                await self._sender_task
            except BaseException:  # CancelledError to BaseException
                pass
            self._sender_task = None
