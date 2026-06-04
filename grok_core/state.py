"""Stan backendu i zależności współdzielone przez trasy.

`Backend` skupia reużyte managery legacy oraz logikę kluczy/uwierzytelniania
odwzorowaną 1:1 z `app.py` (OAuth token -> klucz API -> XAI_API_KEY z .env).
`get_backend` i `require_token` to zależności FastAPI (token czytany z
`app.state.session_token`, ustawianego przy starcie w server.create_app).
"""

from __future__ import annotations

import json
import logging
import os
import secrets
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

log = logging.getLogger(__name__)

from fastapi import Header, HTTPException, Request, WebSocket

# Legacy moduły z korzenia repo (sys.path ustawiony w grok_core/__init__.py).
import config  # type: ignore
from api_manager import APIManager  # type: ignore
from chats_manager import ChatStore  # type: ignore
from history_manager import HistoryManager  # type: ignore
from oauth_manager import OAuthManager  # type: ignore

try:
    import requests  # type: ignore
except Exception:  # pragma: no cover
    requests = None  # type: ignore


class Backend:
    """Reużyte managery legacy + logika kluczy, ustawień i zapisu mediów."""

    def __init__(self) -> None:
        from grok_core.agent.permissions import PermissionGate

        self.history = HistoryManager()
        self.oauth = OAuthManager()
        self.chats = ChatStore()
        self.api = APIManager(self.get_api_key)
        self._workspace = None  # agent/IDE workspace (Workspace | None)
        # Trwała allowlista agenta ("Always allow") współdzielona przez WS i REST.
        self.permissions = PermissionGate(config.PERMISSIONS_FILE)

    # --- workspace agenta kodowania (Faza 4) ---
    def set_workspace(self, path: str):
        from grok_core.agent.workspace import Workspace

        self._workspace = Workspace(path)
        self._record_recent(self._workspace.root.as_posix())
        return self._workspace

    def get_workspace(self):
        return self._workspace

    # --- ostatnie workspace (Faza 6, szybkie przełączanie folderów) ---
    def _record_recent(self, posix_path: str, limit: int = 10) -> None:
        s = self.read_settings()
        recents = [p for p in (s.get("recent_workspaces") or []) if p != posix_path]
        recents.insert(0, posix_path)
        s["recent_workspaces"] = recents[:limit]
        try:
            self.write_settings(s)  # niekrytyczne (lista „ostatnich") — nie wywracaj na błędzie zapisu
        except Exception:
            log.warning("Could not persist recent workspaces", exc_info=True)

    def recent_workspaces(self) -> List[str]:
        return list(self.read_settings().get("recent_workspaces") or [])

    # --- ustawienia (grok_settings.json) ---
    def read_settings(self) -> dict:
        if config.SETTINGS_FILE.exists():
            try:
                return json.loads(config.SETTINGS_FILE.read_text(encoding="utf-8")) or {}
            except Exception as exc:
                # P1-6: nie kasuj po cichu — zaloguj i ZACHOWAJ uszkodzony plik w
                # kopii .corrupt, by zwrot {} (i nadpisanie) nie zniszczył danych bezpowrotnie.
                log.error("Corrupt %s (%s); backing up and starting empty",
                          config.SETTINGS_FILE.name, exc)
                try:
                    backup = config.SETTINGS_FILE.with_suffix(config.SETTINGS_FILE.suffix + ".corrupt")
                    os.replace(config.SETTINGS_FILE, backup)
                except OSError:
                    pass
        return {}

    def write_settings(self, data: dict) -> None:
        # P1-6/P1-7: zapis ATOMOWY (config.atomic_write_text) i błąd PROPAGOWANY —
        # żeby trasa /settings nie zwróciła „zapisano", gdy zapis się nie udał.
        try:
            config.atomic_write_text(config.SETTINGS_FILE, json.dumps(data, indent=2))
        except Exception:
            log.exception("Failed to write %s", config.SETTINGS_FILE.name)
            raise

    def update_settings(self, patch: dict) -> dict:
        s = self.read_settings()
        for key, value in patch.items():
            if value is not None:
                s[key] = value
        self.write_settings(s)
        return s

    # --- klucze / uwierzytelnianie (jak app.get_api_key/is_authenticated) ---
    def has_api_key(self) -> bool:
        return bool(self.read_settings().get("api_key") or os.getenv("XAI_API_KEY"))

    def get_api_key(self) -> str:
        token = self.oauth.get_access_token()
        if token:
            return token
        return self.read_settings().get("api_key") or os.getenv("XAI_API_KEY", "")

    def is_authenticated(self) -> bool:
        return bool(self.oauth.is_authenticated() or self.has_api_key())

    # --- modele czatu (jak app._refresh_models) ---
    def list_chat_models(self) -> List[str]:
        ids = self.api.list_models()
        chat_ids = [m for m in ids if m and "imagine" not in m]
        merged = list(chat_ids)
        for m in config.DEFAULT_CHAT_MODELS:
            if m not in merged:
                merged.append(m)
        return merged

    # --- zapis mediów (auto-save jak ResultCard/_auto_save_video) ---
    def save_media_urls(self, urls, prompt: str, mode: str, ext: str,
                        download: bool = True) -> list:
        out = []
        save_dir = Path(self.history.get_save_path())
        try:
            save_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            log.warning("Could not create media save dir %s", save_dir, exc_info=True)
        for url in urls:
            path = None
            if download and requests is not None:
                try:
                    data = requests.get(url, timeout=180).content
                    fn = f"studio_{mode}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}{ext}"
                    target = save_dir / fn
                    target.write_bytes(data)
                    path = str(target)
                except Exception:
                    log.warning("Failed to download/save media from %s", url, exc_info=True)
                    path = None
            try:
                self.history.save_to_history(mode, path or url, prompt)
            except Exception:
                log.warning("Failed to record media in history", exc_info=True)
            out.append({"url": url, "path": path})
        return out

    def save_media_bytes(self, data: bytes, prompt: str, mode: str, ext: str) -> dict:
        """Zapis gotowych bajtów (np. audio z TTS) do folderu wyjściowego + historia."""
        save_dir = Path(self.history.get_save_path())
        path = None
        try:
            save_dir.mkdir(parents=True, exist_ok=True)
            fn = f"studio_{mode}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}{ext}"
            target = save_dir / fn
            target.write_bytes(data)
            path = str(target)
        except Exception:
            path = None
        try:
            self.history.save_to_history(mode, path or "", prompt)
        except Exception:
            pass
        return {"path": path}


# --- zależności FastAPI ---
def get_backend(request: Request) -> Backend:
    backend = getattr(request.app.state, "backend", None)
    if backend is None:
        detail = getattr(request.app.state, "backend_error", "Backend not initialized")
        raise HTTPException(status_code=503, detail=detail)
    return backend


def require_token(request: Request, authorization: Optional[str] = Header(default=None)) -> None:
    expected = getattr(request.app.state, "session_token", "")
    if not expected:
        return  # tryb otwarty (standalone/dev bez tokenu)
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization[len("Bearer ") :].strip()
    if not secrets.compare_digest(token, expected):  # P1-9: porównanie w czasie stałym
        raise HTTPException(status_code=403, detail="Invalid token")


# --- autoryzacja WebSocketów (P0-8) ---
# WS nie mogą ustawić nagłówka Authorization → token w query. W przeciwieństwie do
# REST (tryb otwarty bez tokenu), WS są FAIL-CLOSED: brak skonfigurowanego tokenu =
# ODMOWA, chyba że jawny opt-in env GROK_CORE_ALLOW_NO_TOKEN=1. Powód: /terminal to
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
    except Exception:
        return False


def ws_authorized(ws: WebSocket) -> bool:
    """Autoryzuje WebSocket: kontrola Origin + token w query (czas stały)."""
    if not _ws_origin_ok(ws.headers.get("origin")):
        return False
    expected = getattr(ws.app.state, "session_token", "")
    if not expected:
        # FAIL-CLOSED: bez tokenu odmawiamy, o ile nie ma jawnego opt-inu dev.
        return os.environ.get("GROK_CORE_ALLOW_NO_TOKEN") == "1"
    return secrets.compare_digest(ws.query_params.get("token", ""), expected)
