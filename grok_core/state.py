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

from fastapi import Depends, Header, HTTPException, Request, WebSocket

# Legacy moduły z korzenia repo (sys.path ustawiony w grok_core/__init__.py).
import config  # type: ignore
from api_manager import APIManager  # type: ignore
from history_manager import HistoryManager  # type: ignore
from oauth_manager import OAuthManager  # type: ignore

try:
    import requests  # type: ignore
except Exception:  # pragma: no cover
    requests = None  # type: ignore

# P1-14: twardy limit pobieranych mediów (anty-OOM / miękki DoS przy spoofie URL).
MAX_MEDIA_BYTES = 256 * 1024 * 1024  # 256 MB (wideo bywa duże, ale nie nieograniczone)


class Backend:
    """Reużyte managery legacy + logika kluczy, ustawień i zapisu mediów."""

    # M9-B5: aktywny projekt (scope historii/artefaktów). Atrybut KLASOWY, by
    # instancje budowane przez __new__ (testy) też miały bezpieczny default None.
    current_project_id: Optional[str] = None

    def __init__(self) -> None:
        from grok_core.agent.permissions import PermissionGate

        self.history = HistoryManager()
        self.oauth = OAuthManager()
        # P2-8: rozmowy czatu są przechowywane w localStorage renderera (świadomy
        # wybór — patrz useConversations). Backend ich NIE utrwala; `ChatStore`
        # usunięto, bo żadna trasa go nie wystawiała, a tworzył grok_chats.json
        # przy każdym starcie (martwy kod robiący I/O). `chats_manager.py` pozostaje
        # w rdzeniu (reużywalny), ale sidecar go nie instancjonuje.
        self.api = APIManager(self.get_api_key)
        self._workspace = None  # agent/IDE workspace (Workspace | None)
        # Trwała allowlista agenta ("Always allow") współdzielona przez WS i REST.
        self.permissions = PermissionGate(config.PERMISSIONS_FILE)
        # M9-B5: ostatnio wybrany projekt (przeżywa restart przez grok_settings.json).
        self.current_project_id = self.read_settings().get("current_project_id")

    # --- workspace agenta kodowania (Faza 4) ---
    def set_workspace(self, path: str):
        from grok_core.agent.workspace import Workspace

        self._workspace = Workspace(path)
        root = self._workspace.root.as_posix()
        self._record_recent(root)
        # M9-B5: workspace kodu staje się aktywnym projektem (most, nie duplikat) —
        # dzięki temu czat/media/voice w tej sesji też trafiają do tego projektu.
        try:
            proj = self.history_store.ensure_project_for_root(root, name=self._workspace.root.name)
            self.select_project(proj.id)
        except Exception:
            log.warning("Could not bind workspace to a project", exc_info=True)
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
        # P1-6/P1-11: korupcja → backup .corrupt + pusty wynik (wspólny loader,
        # ten sam mechanizm co dla chats/history/auth/permissions).
        return config.load_json_or_backup(config.SETTINGS_FILE, {}) or {}

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

    # --- M9-B2: wspólna historia huba (artefakty + zdarzenia, SQLite/FTS5) ---
    @property
    def history_store(self):
        """Leniwy magazyn `grok_history.db` (tworzony przy 1. użyciu). Osobny od
        legacy `self.history`/`grok_config.json` — kręgosłup huba (PLAN_M9)."""
        from grok_core.history_store import get_store
        return get_store()

    def record_event(self, *, mode: str, text: str = "", artifact_id=None,
                     project_id=None, meta=None):
        """Dorzuć zdarzenie do wspólnej, przeszukiwalnej historii huba (M9-B2).
        Bez jawnego `project_id` stempluje AKTYWNYM projektem (M9-B5). NIGDY nie
        wywraca ścieżki użytkownika — błąd magazynu jest logowany i połykany."""
        pid = project_id if project_id is not None else self.current_project_id
        try:
            return self.history_store.record_event(
                mode=mode, text=text or "", artifact_id=artifact_id,
                project_id=pid, meta=meta,
            )
        except Exception:
            log.warning("Could not record history event (mode=%s)", mode, exc_info=True)
            return None

    def add_artifact(self, **kwargs):
        """Zarejestruj artefakt (obraz/wideo/audio/...) w magazynie huba. Bez jawnego
        `project_id` stempluje aktywnym projektem (M9-B5). Połyka błędy."""
        if kwargs.get("project_id") is None:
            kwargs["project_id"] = self.current_project_id
        try:
            return self.history_store.add_artifact(**kwargs)
        except Exception:
            log.warning("Could not record artifact (mode=%s)", kwargs.get("mode"), exc_info=True)
            return None

    # --- projekty (M9-B5): wspólny scope trybów ---
    def list_projects(self):
        return self.history_store.list_projects()

    def current_project(self):
        pid = self.current_project_id
        return self.history_store.get_project(pid) if pid else None

    def create_project(self, name: str, root: str = ""):
        """Utwórz (lub dla `root` reużyj) projekt i ustaw go jako aktywny."""
        if root:
            proj = self.history_store.ensure_project_for_root(root, name=name)
        else:
            proj = self.history_store.add_project(name=name, root="")
        self.select_project(proj.id)
        return proj

    def select_project(self, project_id):
        """Ustaw aktywny projekt (None = wyczyść). Nieznane id → ValueError."""
        if project_id is not None and self.history_store.get_project(project_id) is None:
            raise ValueError("Unknown project")
        self.current_project_id = project_id
        try:
            s = self.read_settings()
            s["current_project_id"] = project_id
            self.write_settings(s)  # przeżywa restart; niekrytyczne (połykane)
        except Exception:
            log.warning("Could not persist current project", exc_info=True)

    @staticmethod
    def _media_kind(legacy_mode: str, ext: str):
        """Zmapuj legacy tryb zapisu ('generate'/'edit'/'video'/'tts') + rozszerzenie
        na M9 (type, mode, mime). M9 mode ∈ {image, video, voice}."""
        e = (ext or "").lower().lstrip(".")
        audio_mime = {"mp3": "audio/mpeg", "wav": "audio/wav", "ogg": "audio/ogg",
                      "m4a": "audio/mp4"}
        image_mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                      "webp": "image/webp", "gif": "image/gif"}
        if legacy_mode == "tts" or e in audio_mime:
            return "audio", "voice", audio_mime.get(e, "audio/mpeg")
        if legacy_mode == "video" or e in ("mp4", "mov", "webm"):
            return "video", "video", "video/mp4"
        return "image", "image", image_mime.get(e, "image/png")

    def _record_media_artifact(self, *, legacy_mode: str, ext: str, prompt: str,
                               path, url) -> None:
        """M9-B2: zapisz wygenerowane medium jako artefakt + zdarzenie historii.
        Wołane z `save_media_urls`/`save_media_bytes` (poza gorącą pętlą; błędy połykane)."""
        a_type, a_mode, mime = self._media_kind(legacy_mode, ext)
        meta = {"prompt": prompt or "", "op": legacy_mode}
        if url:
            meta["url"] = url
        art = self.add_artifact(type=a_type, mode=a_mode, mime=mime,
                                path=path or "", meta=meta)
        self.record_event(mode=a_mode, text=prompt or "",
                          artifact_id=(art.id if art else None))

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
                    path = self._download_media(url, save_dir, mode, ext)
                except Exception:
                    log.warning("Failed to download/save media from %s", url, exc_info=True)
                    path = None
            try:
                self.history.save_to_history(mode, path or url, prompt)
            except Exception:
                log.warning("Failed to record media in history", exc_info=True)
            # M9-B2: artefakt + zdarzenie we wspólnej, przeszukiwalnej historii huba.
            self._record_media_artifact(legacy_mode=mode, ext=ext, prompt=prompt,
                                        path=path, url=url)
            out.append({"url": url, "path": path})
        return out

    def _download_media(self, url: str, save_dir: Path, mode: str, ext: str) -> str:
        """P1-14: pobranie mediów z xAI BEZPIECZNIE — tylko `https` (blokuje SSRF do
        http/file/itp.), strumieniowo na dysk z TWARDYM limitem rozmiaru (bez
        buforowania całości w pamięci). Zwraca ścieżkę pliku albo rzuca wyjątek."""
        if urlparse(url).scheme != "https":
            raise ValueError("refused non-https media URL")
        fn = f"studio_{mode}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}{ext}"
        target = save_dir / fn
        total = 0
        try:
            with requests.get(url, timeout=180, stream=True) as r:
                r.raise_for_status()
                cl = r.headers.get("Content-Length")
                if cl and cl.isdigit() and int(cl) > MAX_MEDIA_BYTES:
                    raise ValueError("media exceeds size cap")
                with open(target, "wb") as f:
                    for chunk in r.iter_content(65536):
                        if not chunk:
                            continue
                        total += len(chunk)
                        if total > MAX_MEDIA_BYTES:
                            raise ValueError("media exceeds size cap")
                        f.write(chunk)
            return str(target)
        except Exception:
            try:
                if target.exists():
                    target.unlink()  # usuń częściowy plik
            except OSError:
                pass
            raise

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
        # M9-B2: artefakt (np. audio TTS) + zdarzenie w historii huba.
        self._record_media_artifact(legacy_mode=mode, ext=ext, prompt=prompt,
                                    path=path, url=None)
        return {"path": path}


# --- zależności FastAPI ---
def get_backend(request: Request) -> Backend:
    backend = getattr(request.app.state, "backend", None)
    if backend is None:
        detail = getattr(request.app.state, "backend_error", "Backend not initialized")
        raise HTTPException(status_code=503, detail=detail)
    return backend


def require_workspace(b: "Backend" = Depends(get_backend)):
    """Zależność: zwraca aktywny Workspace lub 400 'No workspace selected'.
    Wspólna dla tras /fs i /git (P2-12 — wcześniej zdublowany `_require_ws`)."""
    ws = b.get_workspace()
    if ws is None:
        raise HTTPException(status_code=400, detail="No workspace selected")
    return ws


def require_token(request: Request, authorization: Optional[str] = Header(default=None)) -> None:
    expected = getattr(request.app.state, "session_token", "")
    if not expected:
        # P1-10: FAIL-CLOSED symetrycznie do WS (P0-8). Bez skonfigurowanego tokenu
        # odmawiamy — chyba że jawny opt-in dev GROK_CORE_ALLOW_NO_TOKEN=1. Wcześniej
        # REST było „otwarte" (dowolny lokalny proces mógł pisać pliki/wydawać quotę).
        if os.environ.get("GROK_CORE_ALLOW_NO_TOKEN") == "1":
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
