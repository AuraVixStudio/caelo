"""Aplikacja FastAPI sidecara caelo-core.

Faza 1: reużycie managerów legacy (api/oauth/chats/history) przez trasy
`/auth`, `/models`, `/settings`, `/images`, `/video` oraz WebSocket `/chat/stream`.

Bezpieczeństwo:
- backend bindowany WYŁĄCZNIE na 127.0.0.1 (patrz __main__.py),
- trasy REST poza /health wymagają nagłówka `Authorization: Bearer <token>`,
- WebSocket /chat/stream autoryzuje token w query (`?token=...`),
- token to sekret sesji z env CAELO_CORE_TOKEN (ustawiany przez Electron),
  trzymany w `app.state.session_token`.

CORS (P1-9): zawężone do renderera — dev na pętli zwrotnej (dowolny port) oraz
spakowany Electron `file://` (Origin "null"). Strona z zewnątrz (np. atak drive-by)
nie pasuje → odcięta. Bez credentials (token w nagłówku, nie w cookies).
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger("caelo_core.server")

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

import config  # type: ignore

from caelo_core.routes import (
    agent,
    agent_api,
    auth,
    chat,
    collections,
    commands,
    fs,
    genjobs,
    git,
    history,
    hooks,
    lsp,
    mcp,
    media,
    models,
    packages,
    permissions,
    projects,
    sandbox,
    sessions,
    settings,
    skills,
    system,
    team,
    terminal,
    voice,
)
from caelo_core.state import Backend, require_token


def _resolve_app_version() -> str:
    """Wersja PRODUKTU — JEDNO źródło prawdy: desktop/package.json (P3-4).

    Pierwszeństwo:
      1) env CAELO_CORE_APP_VERSION — wstrzykiwane przez proces główny Electron
         (`app.getVersion()`); działa też w SPAKOWANYM buildzie, gdzie package.json
         nie leży obok sidecara.
      2) odczyt desktop/package.json — dev/standalone uruchamiany z korzenia repo.
      3) "0.0.0" — sygnał błędnej konfiguracji (nie zgadujemy).

    Dzięki temu handshake / `/health` / `/whoami` raportują tę samą wersję, którą
    pokazuje instalator. (Legacy `config.APP_VERSION` to OSOBNA wersja archiwalnej
    apki customtkinter — patrz komentarz w config.py.)
    """
    env_v = os.environ.get("CAELO_CORE_APP_VERSION")
    if env_v:
        return env_v
    try:
        pkg = Path(config.BASE_DIR) / "desktop" / "package.json"
        return json.loads(pkg.read_text(encoding="utf-8")).get("version") or "0.0.0"
    except Exception:
        return "0.0.0"


APP_VERSION = _resolve_app_version()
SERVICE_NAME = "caelo-core"


def create_app(
    token: str = "",
    port: int = 0,
    on_startup: Optional[Callable[[], None]] = None,
) -> FastAPI:
    """Tworzy instancję aplikacji FastAPI sidecara.

    Args:
        token: sekret sesji wymagany do autoryzowanych endpointów.
        port:  port nasłuchu (raportowany w /whoami i handshake'u).
        on_startup: callback wołany po starcie serwera (handshake na stdout).
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.session_token = token
        app.state.port = port
        # P1-10: bez tokenu REST i WS są FAIL-CLOSED (symetrycznie). Głośno
        # ostrzegamy — inaczej „nic nie działa" byłoby trudne do zdiagnozowania.
        if not token and os.environ.get("CAELO_CORE_ALLOW_NO_TOKEN") != "1":
            log.warning(
                "No session token configured — REST and WebSocket are FAIL-CLOSED "
                "(every request denied). Set CAELO_CORE_TOKEN, or "
                "CAELO_CORE_ALLOW_NO_TOKEN=1 for an explicit dev opt-in."
            )
        try:
            app.state.backend = Backend()
            app.state.backend_error = None
        except Exception as exc:  # noqa: BLE001
            app.state.backend = None
            app.state.backend_error = str(exc)
        if on_startup is not None:
            on_startup()
        yield
        # Sprzątanie na zamknięciu: ubij podprocesy MCP (tree-kill), itp.
        backend = getattr(app.state, "backend", None)
        if backend is not None:
            try:
                backend.shutdown()
            except Exception:  # noqa: BLE001
                log.warning("Backend shutdown failed", exc_info=True)

    app = FastAPI(title=SERVICE_NAME, version=APP_VERSION, lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        # "null" = strona file:// (spakowany Electron); regex = dev renderer na
        # localhost/127.0.0.1 (dowolny port). Brak "*" — drive-by z sieci odcięty.
        allow_origins=["null"],
        allow_origin_regex=r"^http://(localhost|127\.0\.0\.1)(:\d+)?$",
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict:
        """Liveness probe (bez autoryzacji) — używany przez Electron po handshake'u."""
        return {"status": "ok", "service": SERVICE_NAME, "version": APP_VERSION}

    @app.get("/whoami", dependencies=[Depends(require_token)])
    def whoami(request: Request) -> dict:
        """Potwierdza poprawny token sesji (autoryzowany handshake)."""
        return {
            "authenticated": True,
            "service": SERVICE_NAME,
            "version": APP_VERSION,
            "port": getattr(request.app.state, "port", 0),
            "backend_ready": getattr(request.app.state, "backend", None) is not None,
        }

    # Trasy REST chronione tokenem (Bearer).
    guard = [Depends(require_token)]
    app.include_router(auth.router, dependencies=guard)
    app.include_router(models.router, dependencies=guard)
    app.include_router(settings.router, dependencies=guard)
    app.include_router(media.router, dependencies=guard)
    app.include_router(genjobs.router, dependencies=guard)  # M11: jednolita kolejka obrazu/wideo
    app.include_router(voice.router, dependencies=guard)
    app.include_router(system.router, dependencies=guard)
    app.include_router(fs.router, dependencies=guard)
    app.include_router(git.router, dependencies=guard)
    app.include_router(history.router, dependencies=guard)
    app.include_router(projects.router, dependencies=guard)
    app.include_router(collections.router, dependencies=guard)
    app.include_router(permissions.router, dependencies=guard)
    app.include_router(agent_api.router, dependencies=guard)  # M13-B5: checkpoints/undo/CAELO.md
    app.include_router(sessions.router, dependencies=guard)  # M21: trwałe sesje agenta (lista/odczyt/kasowanie)
    app.include_router(team.router, dependencies=guard)  # M17: subagenci (role/scalenia/przebiegi)
    app.include_router(mcp.router, dependencies=guard)  # M14-B1: serwery MCP
    app.include_router(lsp.router, dependencies=guard)  # M19-B3: serwery LSP (intel kodu)
    app.include_router(hooks.router, dependencies=guard)  # M14-B5: hooki + audyt
    app.include_router(commands.router, dependencies=guard)  # M14-B4: komendy slash
    app.include_router(skills.router, dependencies=guard)  # M14-B6: biblioteka skilli
    app.include_router(packages.router, dependencies=guard)  # M16: marketplace pakietów
    app.include_router(sandbox.router, dependencies=guard)  # S34-d: status sandboxa OS
    # WebSockety same weryfikują token z query (nagłówków nie da się ustawić w WS).
    app.include_router(chat.router)
    app.include_router(agent.router)
    app.include_router(terminal.router)
    app.include_router(voice.ws_router)

    return app
