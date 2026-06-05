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
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

log = logging.getLogger(__name__)

from fastapi import Depends, Header, HTTPException, Request, WebSocket

# Legacy moduły z korzenia repo (sys.path ustawiony w caelo_core/__init__.py).
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

# M11-B3: polling zadań wideo po stronie workera (sekundy). Deadline chroni przed
# zadaniem zaciętym w stanie nieterminalnym (analogicznie do POLL_DEADLINE w UI).
VIDEO_POLL_INTERVAL_S = 5
VIDEO_JOB_DEADLINE_S = 12 * 60


class Backend:
    """Reużyte managery legacy + logika kluczy, ustawień i zapisu mediów."""

    # M9-B5: aktywny projekt (scope historii/artefaktów). Atrybut KLASOWY, by
    # instancje budowane przez __new__ (testy) też miały bezpieczny default None.
    current_project_id: Optional[str] = None

    def __init__(self) -> None:
        from caelo_core.agent.permissions import PermissionGate

        self.history = HistoryManager()
        self.oauth = OAuthManager()
        # P2-8: rozmowy czatu są przechowywane w localStorage renderera (świadomy
        # wybór — patrz useConversations). Backend ich NIE utrwala; `ChatStore`
        # usunięto, bo żadna trasa go nie wystawiała, a tworzył caelo_chats.json
        # przy każdym starcie (martwy kod robiący I/O). `chats_manager.py` pozostaje
        # w rdzeniu (reużywalny), ale sidecar go nie instancjonuje.
        self.api = APIManager(self.get_api_key)
        self._workspace = None  # agent/IDE workspace (Workspace | None)
        # M13-B3/B5: menedżer checkpointów bieżącego workspace, współdzielony przez
        # WS (/agent/stream) i REST (/agent/checkpoints,/agent/undo) — jeden mechanizm,
        # jak allowlista. Tworzony leniwie w get_checkpoints (per korzeń workspace).
        self._checkpoints = None
        # Trwała allowlista agenta ("Always allow") współdzielona przez WS i REST.
        self.permissions = PermissionGate(config.PERMISSIONS_FILE)
        # M11-B1: silnik zadań generacji (obraz/wideo) — leniwy (per proces).
        self._genjobs = None
        # M14-B1: menedżer serwerów MCP — leniwy (per proces).
        self._mcp = None
        # M14-B5: menedżer hooków cyklu życia narzędzi — leniwy (per proces).
        self._hooks = None
        # M14-B4/B6: rejestr komend slash + biblioteka skilli — leniwe (per proces).
        self._commands = None
        self._skills = None
        # M17: rejestr ról subagentów (leniwy) + magazyn oczekujących scaleń worktree
        # (per workspace, jak checkpointy) + ostatnie raporty przebiegów zespołu.
        self._subagents = None
        self._team_merges = None
        self._team_reports: list[dict] = []
        # M9-B5: ostatnio wybrany projekt (przeżywa restart przez caelo_settings.json).
        self.current_project_id = self.read_settings().get("current_project_id")

    # --- workspace agenta kodowania (Faza 4) ---
    def set_workspace(self, path: str):
        from caelo_core.agent.workspace import Workspace

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

    # --- checkpointy agenta (M13-B3/B5) ---
    def get_checkpoints(self):
        """Menedżer checkpointów dla AKTYWNEGO workspace (leniwy; reużywany dopóki
        korzeń się nie zmieni). None, gdy brak workspace. Współdzielony przez WS
        i REST — undo z UI (REST) cofa to, co zsnapshotował agent (WS)."""
        from caelo_core.agent.checkpoints import CheckpointManager

        ws = self._workspace
        if ws is None:
            return None
        if self._checkpoints is None or self._checkpoints.root != ws.root:
            self._checkpoints = CheckpointManager(ws.root)
        return self._checkpoints

    # --- subagenci / zespół (M17) ---
    @property
    def subagents(self):
        """Leniwy `RoleRegistry`: role subagentów + limity zespołu (`caelo_subagents.json`)."""
        from caelo_core.agent.roles import RoleRegistry

        if getattr(self, "_subagents", None) is None:
            self._subagents = RoleRegistry(config.SUBAGENTS_FILE)
        return self._subagents

    def get_team_merges(self):
        """Magazyn oczekujących scaleń worktree dla AKTYWNEGO workspace (leniwy,
        reużywany dopóki korzeń się nie zmieni). None bez workspace. Współdzielony
        przez WS (subagent rejestruje scalenie) i REST (/agent/team/merge*)."""
        from caelo_core.agent.team import MergeStore

        ws = self._workspace
        if ws is None:
            return None
        if self._team_merges is None or self._team_merges.root != ws.root:
            self._team_merges = MergeStore(ws.root)
        return self._team_merges

    def record_team_report(self, report: dict, limit: int = 20) -> None:
        """Dorzuć raport przebiegu zespołu (B6/F5). Ring buffer w pamięci (per proces)."""
        try:
            self._team_reports.insert(0, report)
            del self._team_reports[limit:]
        except Exception:  # noqa: BLE001
            log.warning("Could not record team report", exc_info=True)

    def team_reports(self) -> list:
        return list(getattr(self, "_team_reports", []))

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

    # --- ustawienia (caelo_settings.json) ---
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
        """Leniwy magazyn `caelo_history.db` (tworzony przy 1. użyciu). Osobny od
        legacy `self.history`/`caelo_config.json` — kręgosłup huba (PLAN_M9)."""
        from caelo_core.history_store import get_store
        return get_store()

    # --- M11-B1: zadania generacji (jednolita kolejka obrazu/wideo) ----------
    @property
    def genjobs(self):
        """Leniwy `GenJobManager` (per proces) z egzekutorem związanym z tym Backendem.
        Egzekutor reużywa `api`/`save_media_urls` (zero drugiego magazynu media)."""
        from caelo_core.genjobs import GenJobManager

        if getattr(self, "_genjobs", None) is None:
            self._genjobs = GenJobManager(self._gen_executor, store=self.history_store)
        return self._genjobs

    # --- M14-B1: menedżer serwerów MCP (rozszerzalność) ----------------------
    @property
    def mcp(self):
        """Leniwy `McpManager` (per proces): skonfigurowane serwery MCP + ich narzędzia.
        Współdzielony przez REST (/mcp), czat (responses) i agenta (session)."""
        from caelo_core.mcp.manager import McpManager

        if getattr(self, "_mcp", None) is None:
            self._mcp = McpManager(config.MCP_FILE)
        return self._mcp

    # --- M14-B5: hooki cyklu życia narzędzi (uogólniony PermissionGate) ----------
    @property
    def hooks(self):
        """Leniwy `HookManager` (per proces): pre/post-tool + pre-session + audyt.
        Współdzielony przez agenta (session) i REST (/hooks)."""
        from caelo_core.hooks import HookManager

        if getattr(self, "_hooks", None) is None:
            self._hooks = HookManager(config.HOOKS_FILE, config.AUDIT_LOG_FILE)
        return self._hooks

    # --- M14-B4: rejestr komend slash --------------------------------------------
    @property
    def commands(self):
        """Leniwy `CommandRegistry`: wbudowane + użytkownika (`caelo_commands.json`)."""
        from caelo_core.commands import CommandRegistry

        if getattr(self, "_commands", None) is None:
            self._commands = CommandRegistry(config.COMMANDS_FILE)
        return self._commands

    # --- M14-B6: biblioteka skilli -----------------------------------------------
    @property
    def skills(self):
        """Leniwy `SkillManager`: lokalne pakiety skilli (`SKILLS_DIR/<name>/SKILL.md`)."""
        from caelo_core.skills import SkillManager

        if getattr(self, "_skills", None) is None:
            self._skills = SkillManager(config.SKILLS_DIR)
        return self._skills

    def shutdown(self) -> None:
        """Sprzątanie na zamknięciu sidecara: ubij podprocesy serwerów MCP (tree-kill)."""
        mgr = getattr(self, "_mcp", None)
        if mgr is not None:
            try:
                mgr.shutdown()
            except Exception:  # noqa: BLE001
                log.warning("MCP shutdown failed", exc_info=True)

    def _gen_executor(self, job, cancel) -> list:
        """Wykonaj zadanie generacji → lista artifact_id (M9). Rzuca przy błędzie."""
        if job.kind == "image":
            return self._run_image_job(job, cancel)
        if job.kind == "video":
            return self._run_video_job(job, cancel)
        raise ValueError(f"unknown gen job kind: {job.kind}")

    def _run_image_job(self, job, cancel) -> list:
        p = job.params
        prompt = p.get("prompt", "")
        n = int(p.get("n", 1) or 1)
        ratio = p.get("aspect_ratio", "auto")
        resolution = p.get("resolution", "1k")
        model = p.get("model") or None
        if job.op == "text2img":
            urls = self.api.generate_image(prompt, n, ratio, resolution, model=model)
            legacy_mode = "generate"
        else:  # edit / variation — oba przez /images/edits (referencja + prompt)
            images = list(p.get("images") or [])
            if not images:
                raise ValueError("edit/variation requires at least one reference image")
            urls = self.api.edit_image_b64(prompt, images, n, ratio, resolution, model=model)
            legacy_mode = "edit"
        results = self.save_media_urls(urls, prompt, legacy_mode, ".png",
                                       project_id=job.project_id,
                                       meta_extra={"gen_op": job.op, "model": model or ""})
        return [r["artifact_id"] for r in results if r.get("artifact_id")]

    def _run_video_job(self, job, cancel) -> list:
        from caelo_core.genjobs import GenJobCancelled

        p = job.params
        prompt = p.get("prompt", "")
        model = p.get("model") or None
        # Wybór wywołania xAI po operacji; dalej wspólna pętla pollingu.
        if job.op == "edit":
            request_id = self.api.edit_video_job(prompt, p["video"], model=model)
        elif job.op == "extend":
            request_id = self.api.extend_video_job(
                prompt, p["video"], duration=int(p.get("duration") or 0) or None, model=model)
        else:  # text2video / img2video
            request_id = self.api.create_video_job(
                prompt, int(p.get("duration", 6) or 6), p.get("resolution", "480p"),
                p.get("aspect_ratio", "Original"), None, model=model,
                image_data_uri=p.get("image"),
            )
        deadline = time.time() + VIDEO_JOB_DEADLINE_S
        while True:
            if cancel.is_set():
                raise GenJobCancelled()
            st = self.api.poll_video_status(request_id)
            status = (st or {}).get("status")
            if status == "done":
                url = (st.get("video") or {}).get("url")
                if not url:
                    raise RuntimeError("video job finished without a URL")
                results = self.save_media_urls([url], prompt, "video", ".mp4",
                                               project_id=job.project_id,
                                               meta_extra={"gen_op": job.op, "model": model or ""})
                return [r["artifact_id"] for r in results if r.get("artifact_id")]
            if status in ("failed", "expired"):
                raise RuntimeError(f"video job {status}")
            if time.time() > deadline:
                raise RuntimeError("video job timed out (still rendering)")
            # Czekaj, ale pozostań przerywalny: wait() wraca natychmiast po cancel.
            cancel.wait(VIDEO_POLL_INTERVAL_S)

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

    # --- wiedza projektu (M10-B5: lokalne dokumenty, dołączane na żądanie) -------
    # xAI nie wspiera serwerowych vector stores (`/v1/vector_stores` → 404), więc
    # dokumenty „wiedzy projektu" trzymamy LOKALNIE i dołączamy do wiadomości jako
    # input_file na żądanie (przycisk „Attach all" — ścieżka B4, sprawdzona).
    def _project_docs_dir(self, project_id: str) -> Path:
        d = Path(config.PROJECT_DOCS_DIR) / project_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def collection_upload(self, data: bytes, filename: str, mime: str = ""):
        """Zapisz dokument LOKALNIE w wiedzy AKTYWNEGO projektu. Zwraca CollectionFile.
        Brak aktywnego projektu → ValueError (wiedza jest per projekt)."""
        pid = self.current_project_id
        if not pid:
            raise ValueError("No active project — select or create one first")
        if self.history_store.get_project(pid) is None:
            raise ValueError("Unknown project")
        rid = secrets.token_hex(8)
        safe = Path(filename or "document").name  # tylko nazwa, bez ścieżki
        target = self._project_docs_dir(pid) / f"{rid}_{safe}"
        target.write_bytes(data)
        return self.history_store.add_collection_file(
            project_id=pid, name=safe, path=str(target), mime=mime or "",
            bytes=len(data or b""), id=rid)

    def collection_files(self):
        """Dokumenty wiedzy aktywnego projektu (pusta lista bez projektu)."""
        pid = self.current_project_id
        return self.history_store.list_collection_files(pid) if pid else []

    def collection_file_path(self, file_row_id: str):
        """Bezpieczna ścieżka pliku dokumentu (musi leżeć pod PROJECT_DOCS_DIR —
        anty-traversal). None, gdy nie znaleziono / poza katalogiem."""
        cf = self.history_store.get_collection_file(file_row_id)
        if cf is None or not cf.path:
            return None
        try:
            p = Path(cf.path).resolve()
            base = Path(config.PROJECT_DOCS_DIR).resolve()
            if base in p.parents and p.is_file():
                return cf
        except OSError:
            return None
        return None

    def collection_remove(self, file_row_id: str) -> bool:
        """Usuń dokument z wiedzy projektu (plik lokalny + rekord). False, gdy brak."""
        cf = self.history_store.get_collection_file(file_row_id)
        if cf is None:
            return False
        if cf.path:
            try:
                p = Path(cf.path).resolve()
                base = Path(config.PROJECT_DOCS_DIR).resolve()
                if base in p.parents and p.exists():
                    p.unlink()
            except OSError:
                log.warning("Could not delete project doc %s", cf.path, exc_info=True)
        self.history_store.remove_collection_file(file_row_id)
        return True

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
                               path, url, project_id=None, meta_extra=None):
        """M9-B2: zapisz wygenerowane medium jako artefakt + zdarzenie historii.
        Wołane z `save_media_urls`/`save_media_bytes` (poza gorącą pętlą; błędy połykane).
        `project_id` (M11): jawny scope (np. z `GenJob`) — None stempluje aktywnym.
        Zwraca utworzony Artifact (albo None przy błędzie magazynu)."""
        a_type, a_mode, mime = self._media_kind(legacy_mode, ext)
        meta = {"prompt": prompt or "", "op": legacy_mode}
        if url:
            meta["url"] = url
        if meta_extra:
            meta.update(meta_extra)
        art = self.add_artifact(type=a_type, mode=a_mode, mime=mime,
                                path=path or "", meta=meta, project_id=project_id)
        self.record_event(mode=a_mode, text=prompt or "",
                          artifact_id=(art.id if art else None), project_id=project_id)
        return art

    # --- zapis mediów (auto-save jak ResultCard/_auto_save_video) ---
    def save_media_urls(self, urls, prompt: str, mode: str, ext: str,
                        download: bool = True, project_id=None,
                        meta_extra=None) -> list:
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
            # M11: zwracamy też artifact_id, by GenJob zarejestrował swoje wyjścia.
            art = self._record_media_artifact(legacy_mode=mode, ext=ext, prompt=prompt,
                                              path=path, url=url, project_id=project_id,
                                              meta_extra=meta_extra)
            out.append({"url": url, "path": path,
                        "artifact_id": (art.id if art else None)})
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
        # odmawiamy — chyba że jawny opt-in dev CAELO_CORE_ALLOW_NO_TOKEN=1. Wcześniej
        # REST było „otwarte" (dowolny lokalny proces mógł pisać pliki/wydawać quotę).
        if os.environ.get("CAELO_CORE_ALLOW_NO_TOKEN") == "1":
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
    except Exception:
        return False


def ws_authorized(ws: WebSocket) -> bool:
    """Autoryzuje WebSocket: kontrola Origin + token w query (czas stały)."""
    if not _ws_origin_ok(ws.headers.get("origin")):
        return False
    expected = getattr(ws.app.state, "session_token", "")
    if not expected:
        # FAIL-CLOSED: bez tokenu odmawiamy, o ile nie ma jawnego opt-inu dev.
        return os.environ.get("CAELO_CORE_ALLOW_NO_TOKEN") == "1"
    return secrets.compare_digest(ws.query_params.get("token", ""), expected)
