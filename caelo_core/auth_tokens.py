"""Warstwa autoryzacji sidecara (P2-13 — wydzielona ze `state.py`).

Czysta, testowalna BEZ `Backend`: zależności FastAPI `require_token` (REST) i
`ws_authorized` (WebSocket) czytają token sesji z `app.state.session_token`
(ustawianego w `server.create_app`) — nie dotykają `Backend`. `state.py`
re-eksportuje te symbole, więc `from caelo_core.state import require_token/
ws_authorized/_ws_origin_ok` (server.py, routes, self-checki) działa bez zmian.

Model: REST i WS są FAIL-CLOSED (P0-8/P1-10). Bez skonfigurowanego tokenu obie
strony ODMAWIAJĄ — chyba że jawny opt-in dev `CAELO_CORE_ALLOW_NO_TOKEN=1`
(logowany na starcie w server.py ORAZ per-request tutaj, rate-limited — P2-14).
"""

from __future__ import annotations

import logging
import os
import secrets
import time
from typing import Optional
from urllib.parse import urlparse

from fastapi import Header, HTTPException, Request, WebSocket

log = logging.getLogger(__name__)


# --- P2-14: ślad audytowy dla dev opt-inu bez tokenu ---
# Gdy aktywny CAELO_CORE_ALLOW_NO_TOKEN=1, KAŻDE żądanie jest serwowane bez
# autoryzacji. server.py loguje to raz na starcie; tu logujemy też przy ruchu
# (rate-limited, by nie zalać logu), aby świadomy tryb dev zostawiał ślad per-request.
_NO_TOKEN_WARN_INTERVAL_S = 60.0
_no_token_last_warn = 0.0


def _warn_no_token(channel: str) -> None:
    global _no_token_last_warn
    now = time.monotonic()
    if now - _no_token_last_warn >= _NO_TOKEN_WARN_INTERVAL_S:
        _no_token_last_warn = now
        log.warning(
            "CAELO_CORE_ALLOW_NO_TOKEN=1: %s request served WITHOUT authentication "
            "(dev opt-in). Do NOT use this outside a trusted local session.",
            channel,
        )


def require_token(request: Request, authorization: Optional[str] = Header(default=None)) -> None:
    expected = getattr(request.app.state, "session_token", "")
    if not expected:
        # P1-10: FAIL-CLOSED symetrycznie do WS (P0-8). Bez skonfigurowanego tokenu
        # odmawiamy — chyba że jawny opt-in dev CAELO_CORE_ALLOW_NO_TOKEN=1. Wcześniej
        # REST było „otwarte" (dowolny lokalny proces mógł pisać pliki/wydawać quotę).
        if os.environ.get("CAELO_CORE_ALLOW_NO_TOKEN") == "1":
            _warn_no_token("REST")  # P2-14: ślad per-request, nie tylko na starcie
            return
        raise HTTPException(status_code=401, detail="Server is running without a session token")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization[len("Bearer ") :].strip()
    if not secrets.compare_digest(token, expected):  # P1-9: porównanie w czasie stałym
        raise HTTPException(status_code=403, detail="Invalid token")


# --- autoryzacja WebSocketów (P0-8) ---
# WS nie mogą ustawić nagłówka Authorization → token w query. W przeciwieństwie do
# REST (tryb otwarty bez tokenu), WS są FAIL-CLOSED: brak skonfigurowanego tokenu =
# ODMOWA, chyba że jawny opt-in env CAELO_CORE_ALLOW_NO_TOKEN=1. Powód: /terminal to
# pełna powłoka, a /agent/stream ma dostęp do plików i `run_command`.
_WS_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _ws_origin_ok(origin: Optional[str]) -> bool:
    """Kontrola Origin (P0-8). Dopuszczamy: brak/`null` Origin (natywni klienci),
    `file://` (Electron prod) oraz dowolny host pętli zwrotnej (dev renderer na
    dowolnym porcie). Drive-by z zewnętrznej strony ma realny host → odrzucony."""
    if not origin or origin == "null":
        return True
    if origin.startswith("file://"):
        return True
    try:
        return urlparse(origin).hostname in _WS_LOOPBACK_HOSTS
    except Exception:  # noqa: BLE001 — zniekształcony Origin: fail-closed (odmów); bez logu, by drive-by nie spamował
        return False


def ws_authorized(ws: WebSocket) -> bool:
    """Autoryzuje WebSocket: kontrola Origin + token w query (czas stały)."""
    if not _ws_origin_ok(ws.headers.get("origin")):
        return False
    expected = getattr(ws.app.state, "session_token", "")
    if not expected:
        # FAIL-CLOSED: bez tokenu odmawiamy, o ile nie ma jawnego opt-inu dev.
        if os.environ.get("CAELO_CORE_ALLOW_NO_TOKEN") == "1":
            _warn_no_token("WS")  # P2-14: ślad per-request dla świadomego trybu dev
            return True
        return False
    return secrets.compare_digest(ws.query_params.get("token", ""), expected)
