"""Smoke-test tras Fazy 1 — odwzorowuje, jak frontend rozmawia z backendem.

Spawnuje `python -m caelo_core`, czyta handshake i weryfikuje:
  REST:  /health, /whoami(token), /auth/status, /models, /settings  -> 200
         /models bez tokenu -> 401, zły token -> 403
         media/voice (P3-1): /images/*, /video/*, /voice/* — auth (401/403)
           oraz kształt wejścia (Pydantic -> 422) BEZ realnego wywołania xAI
  WS:    /chat/stream?token=<ok>   -> połączenie zaakceptowane
         /chat/stream?token=<zły>  -> odrzucone

Unity (bez sieci xAI): autoryzacja WS, timeouty APIManager, most czatu, walidacja
wejścia, dekodowanie SSE jako UTF-8 (P3-1), oraz strażnik własności plików JSON
(P3-1: zapis ustawień nie rusza caelo_config.json — domena HistoryManagera).

Nie wykonuje realnych wywołań xAI (obraz/wideo/czat) — to weryfikuje użytkownik
z ważnymi poświadczeniami. Kod wyjścia 0 = wszystkie asercje OK.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PKG_DIR = os.path.dirname(THIS_DIR)
REPO_DIR = os.path.dirname(PKG_DIR)
PREFIX = "__CAELO_CORE_READY__"


def _isolated_env(token: str) -> tuple[dict, str]:
    """P1-E: środowisko dla spawnowanego sidecara z IZOLOWANYM katalogiem danych.

    Zwraca `(env, tmp_data_dir)`. Bez tego self-checki chodziłyby po realnym
    `config.DATA_DIR` (dev = korzeń repo) — a `DELETE /genjobs` skasowałby realną
    listę zadań użytkownika. `CAELO_CORE_DATA_DIR` ma pierwszeństwo w config.py.
    Wołający sprząta `tmp` w finally (`shutil.rmtree(tmp, ignore_errors=True)`)."""
    tmp = tempfile.mkdtemp(prefix="caelo-smoke-")
    env = dict(os.environ, CAELO_CORE_TOKEN=token, CAELO_CORE_DATA_DIR=tmp)
    return env, tmp


def _read_handshake(proc: subprocess.Popen, timeout: float = 25.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                err = proc.stderr.read() if proc.stderr else ""
                raise RuntimeError(f"sidecar exited before handshake:\n{err}")
            continue
        line = line.strip()
        if line.startswith(PREFIX):
            return json.loads(line[len(PREFIX):].strip())
    raise RuntimeError("timed out waiting for handshake")


def _wait_ready(base: str, timeout: float = 15.0) -> None:
    """Czekaj, aż serwer FAKTYCZNIE przyjmuje połączenia (poll /health).

    Handshake jest drukowany z `lifespan.startup()` uvicorna, a ten odpala się
    PRZED `loop.create_server()` (otwarciem nasłuchu) — więc tuż po handshake
    pierwsze żądanie potrafi dostać `Connection refused` (wyścig widoczny zwłaszcza
    na POSIX, gdzie połączenie loopback jest natychmiastowe). Realny klient
    (Electron) toleruje to swoim monitorem /health; testy muszą zrobić to samo,
    inaczej są fałszywie czerwone. Poll przerywa się, gdy /health odpowie."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(base + "/health", timeout=2) as resp:
                if resp.status == 200:
                    return
        except urllib.error.HTTPError:
            return  # serwer nasłuchuje (odpowiedział HTTP), to wystarczy
        except (urllib.error.URLError, OSError):
            time.sleep(0.05)  # jeszcze nie nasłuchuje — spróbuj ponownie
    # Nie udało się w deadline — pozostałe asercje pokażą realny błąd.


def _get(base: str, path: str, token: str | None = None):
    req = urllib.request.Request(base + path)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, None


def _post(base: str, path: str, body: dict, token: str | None = None):
    """POST JSON; zwraca (status, body-lub-None). Błędy HTTP (401/403/422/5xx)
    zwracane jako kod (bez wyjątku) — używane do testów auth/walidacji tras."""
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(base + path, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, None


def _delete(base: str, path: str, token: str | None = None):
    """DELETE; zwraca (status, body-lub-None). Błędy HTTP zwracane jako kod."""
    req = urllib.request.Request(base + path, method="DELETE")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, None


def _cors_acao(base: str, path: str, origin: str) -> str | None:
    """Zwraca Access-Control-Allow-Origin dla żądania z danym Origin (P1-9)."""
    req = urllib.request.Request(base + path)
    req.add_header("Origin", origin)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.headers.get("access-control-allow-origin")
    except urllib.error.HTTPError as exc:
        return exc.headers.get("access-control-allow-origin")


def _capture_no_token_warn(call) -> bool:
    """P2-14: wywołaj `call()` w trybie CAELO_CORE_ALLOW_NO_TOKEN=1 i zwróć True, gdy
    padł WARNING o tym trybie (ślad audytowy per-request). Rate-limiter zresetowany i
    poziom loggera ustawiony na WARNING dla determinizmu; stan przywrócony w finally."""
    import logging as _logging
    from caelo_core import auth_tokens as _auth_mod  # P2-13: auth wydzielony ze state.py
    lg = _logging.getLogger("caelo_core.auth_tokens")
    old_lvl, _auth_mod._no_token_last_warn = lg.level, 0.0
    lg.setLevel(_logging.WARNING)
    rec: list = []
    h = _logging.Handler()
    h.emit = rec.append  # type: ignore[assignment]
    lg.addHandler(h)
    os.environ["CAELO_CORE_ALLOW_NO_TOKEN"] = "1"
    try:
        call()
    finally:
        lg.removeHandler(h)
        lg.setLevel(old_lvl)
        os.environ.pop("CAELO_CORE_ALLOW_NO_TOKEN", None)
    return any(r.levelno >= _logging.WARNING and "ALLOW_NO_TOKEN" in r.getMessage() for r in rec)


async def _ws_check(port: int, token: str) -> tuple[bool, bool]:
    """Zwraca (ok_token_zaakceptowany, zły_token_odrzucony).

    P3-1: brak `websockets` NIE jest już cichym „pass" (fałszywie zielone testy) —
    wywołujący sprawdza dostępność biblioteki osobno i pomija żywe testy WS jawnie,
    więc tu zwracamy realną porażkę, gdyby mimo to import się nie powiódł."""
    try:
        import websockets  # type: ignore
    except Exception:
        return (False, False)

    ok_accepted = False
    bad_rejected = False
    try:
        async with asyncio.timeout(8):
            async with websockets.connect(f"ws://127.0.0.1:{port}/chat/stream?token={token}"):
                ok_accepted = True
    except Exception:
        ok_accepted = False
    try:
        async with asyncio.timeout(8):
            async with websockets.connect(f"ws://127.0.0.1:{port}/chat/stream?token=wrong-token") as ws:
                # serwer może zaakceptować i zaraz zamknąć — sprawdź, czy żyje
                await ws.recv()
        bad_rejected = False
    except Exception:
        bad_rejected = True
    return (ok_accepted, bad_rejected)


async def _ws_bad_token_rejected(port: int, path: str) -> bool:
    """True, jeśli WS pod `path` odrzuca zły token (P0-8: ważne dla /agent, /terminal)."""
    try:
        import websockets  # type: ignore
    except Exception:
        return False  # P3-1: brak biblioteki to nie „pass" (patrz _ws_check)
    try:
        async with asyncio.timeout(8):
            async with websockets.connect(f"ws://127.0.0.1:{port}{path}?token=wrong-token") as ws:
                await ws.recv()
        return False
    except Exception:
        return True
