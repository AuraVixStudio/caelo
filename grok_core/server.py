"""Aplikacja FastAPI sidecara grok-core.

Faza 1: reużycie managerów legacy (api/oauth/chats/history) przez trasy
`/auth`, `/models`, `/settings`, `/images`, `/video` oraz WebSocket `/chat/stream`.

Bezpieczeństwo:
- backend bindowany WYŁĄCZNIE na 127.0.0.1 (patrz __main__.py),
- trasy REST poza /health wymagają nagłówka `Authorization: Bearer <token>`,
- WebSocket /chat/stream autoryzuje token w query (`?token=...`),
- token to sekret sesji z env GROK_CORE_TOKEN (ustawiany przez Electron),
  trzymany w `app.state.session_token`.

CORS (P1-9): zawężone do renderera — dev na pętli zwrotnej (dowolny port) oraz
spakowany Electron `file://` (Origin "null"). Strona z zewnątrz (np. atak drive-by)
nie pasuje → odcięta. Bez credentials (token w nagłówku, nie w cookies).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Callable, Optional

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from grok_core.routes import (
    agent,
    auth,
    chat,
    fs,
    git,
    media,
    models,
    permissions,
    settings,
    system,
    terminal,
    voice,
)
from grok_core.state import Backend, require_token

APP_VERSION = "0.1.0"
SERVICE_NAME = "grok-core"


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
        try:
            app.state.backend = Backend()
            app.state.backend_error = None
        except Exception as exc:  # noqa: BLE001
            app.state.backend = None
            app.state.backend_error = str(exc)
        if on_startup is not None:
            on_startup()
        yield

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
    app.include_router(voice.router, dependencies=guard)
    app.include_router(system.router, dependencies=guard)
    app.include_router(fs.router, dependencies=guard)
    app.include_router(git.router, dependencies=guard)
    app.include_router(permissions.router, dependencies=guard)
    # WebSockety same weryfikują token z query (nagłówków nie da się ustawić w WS).
    app.include_router(chat.router)
    app.include_router(agent.router)
    app.include_router(terminal.router)
    app.include_router(voice.ws_router)

    return app
