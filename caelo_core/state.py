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
import threading
from pathlib import Path
from typing import List, Optional

log = logging.getLogger(__name__)

from fastapi import Depends, HTTPException, Request

# Legacy moduły z korzenia repo (sys.path ustawiony w caelo_core/__init__.py).
import config  # type: ignore
from api_manager import APIManager  # type: ignore
from history_manager import HistoryManager  # type: ignore
from oauth_manager import OAuthManager  # type: ignore

# P2-13: warstwa autoryzacji wydzielona do auth_tokens.py (czysta, testowalna bez
# Backendu). Re-eksport, by `from caelo_core.state import require_token/ws_authorized/
# _ws_origin_ok` (server.py, routes, self-checki) działał bez zmian.
from caelo_core.auth_tokens import (  # noqa: F401
    _ws_origin_ok,
    require_token,
    ws_authorized,
)

# P2-13: generacja/zapis mediów (MediaMixin) i wiedza projektu (CollectionsMixin)
# wydzielone do osobnych modułów — Backend je dziedziczy, API instancji bez zmian.
# Stałe (MAX_MEDIA_BYTES / VIDEO_*) i `requests` żyją teraz w backend_media.py
# (self-checki patchują je tam: `caelo_core.backend_media`).
from caelo_core.backend_collections import CollectionsMixin
from caelo_core.backend_media import MediaMixin


class Backend(MediaMixin, CollectionsMixin):
    """Reużyte managery legacy + logika kluczy/ustawień/projektów. Generacja i zapis
    mediów (MediaMixin) oraz wiedza projektu (CollectionsMixin) dziedziczone z mixinów."""

    # M9-B5: aktywny projekt CZATU (scope historii/artefaktów/wiedzy chat/media/voice).
    # Atrybut KLASOWY, by instancje budowane przez __new__ (testy) miały bezpieczny default.
    current_project_id: Optional[str] = None
    # M22: projekt workspace'u Code (kind='code') do stemplowania zdarzeń mode='code'.
    # Trzymany ODDZIELNIE — otwarcie folderu w Code NIE zmienia aktywnego projektu czatu.
    _code_project_id: Optional[str] = None

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
        # M19-B8: indeks pamięci hybrydowej — leniwy (per proces); opt-in (config).
        self._memory = None
        # M19-B3: menedżer LSP — leniwy per workspace (rebuild przy zmianie korzenia).
        self._lsp = None
        # M14-B5: menedżer hooków cyklu życia narzędzi — leniwy (per proces).
        self._hooks = None
        # M14-B4/B6: rejestr komend slash + biblioteka skilli — leniwe (per proces).
        self._commands = None
        self._skills = None
        # M16: menedżer pakietów społeczności (marketplace) — leniwy (per proces).
        self._packages = None
        # M17: rejestr ról subagentów (leniwy) + magazyn oczekujących scaleń worktree
        # (per workspace, jak checkpointy) + ostatnie raporty przebiegów zespołu.
        self._subagents = None
        self._team_merges = None
        self._team_reports: list[dict] = []
        # M9-B5: ostatnio wybrany projekt CZATU (przeżywa restart przez caelo_settings.json).
        self.current_project_id = self.read_settings().get("current_project_id")
        # M22: legacy current_project_id mógł wskazywać workspace Code (przed rozdzieleniem) —
        # projekt czatu musi startować czysto. Zeruj, gdy to projekt kind='code'.
        if self.current_project_id:
            try:
                p = self.history_store.get_project(self.current_project_id)
                if p is not None and p.kind == "code":
                    self.current_project_id = None
            except Exception:
                log.warning("Could not validate current project kind", exc_info=True)
        # M19-B4: zbuduj reguły glob bramki z ustawień globalnych (workspace jeszcze None
        # → tylko globalne; projektowe doczytane przy set_workspace).
        self.reload_permission_rules()

    # --- workspace agenta kodowania (Faza 4) ---
    def set_workspace(self, path: str):
        from caelo_core.agent.workspace import Workspace

        old_root = self._workspace.root if self._workspace is not None else None
        self._workspace = Workspace(path)
        new_root = self._workspace.root
        root = new_root.as_posix()
        self._record_recent(root)
        # M19-B5 §1.2: inny workspace → inny <ws>/.mcp.json. Przebuduj MCP (tree-kill
        # starych podprocesów). Property `mcp` i tak self-healuje po korzeniu, ale tu
        # robimy to deterministycznie w momencie przełączenia (jak intencja get_lsp).
        if new_root != old_root:
            self.reload_mcp()
        # M22: workspace Code wiąże się z projektem kind='code' (do stemplowania zdarzeń
        # mode='code' i scope historii Code), ale — inaczej niż w M9-B5 — NIE zmienia
        # aktywnego projektu CZATU. Trzymamy jego id osobno (record_event używa go dla code).
        try:
            proj = self.history_store.ensure_project_for_root(
                root, name=self._workspace.root.name, kind="code")
            self._code_project_id = proj.id
        except Exception:
            self._code_project_id = None
            log.warning("Could not bind workspace to a code project", exc_info=True)
        # M19-B4: dociągnij reguły uprawnień projektowe (<ws>/.caelo/permissions.json).
        self.reload_permission_rules()
        return self._workspace

    def get_workspace(self):
        return self._workspace

    # --- reguły uprawnień glob (M19-B4) ---
    def reload_permission_rules(self) -> None:
        """Zbuduj `RuleSet` bramki z reguł GLOBALNYCH (`caelo_settings.json` →
        `permission_rules.{allow,deny}`) + PROJEKTOWYCH (`<ws>/.caelo/permissions.json`).
        Wołane przy starcie i przy zmianie workspace; deny>allow egzekwuje bramka."""
        allow: list[str] = []
        deny: list[str] = []
        g = self.read_settings().get("permission_rules") or {}
        allow += list(g.get("allow") or [])
        deny += list(g.get("deny") or [])
        ws = getattr(self, "_workspace", None)
        if ws is not None:
            # M19-B14: czytaj `.caelo/permissions.json` z KAŻDEGO katalogu od korzenia
            # repo do workspace (przodkowie + workspace); reguły są sumowane (deny>allow
            # i tak globalne). Pojedynczy root (GUI) → tylko workspace (jak przed B14).
            from caelo_core.agent.project import project_dir_chain
            try:
                for d in project_dir_chain(ws.root):
                    data = config.load_json_or_backup(d / ".caelo" / "permissions.json", {}) or {}
                    allow += list(data.get("allow") or [])
                    deny += list(data.get("deny") or [])
            except Exception:
                log.warning("Could not load project permission rules", exc_info=True)
        self.permissions.set_rules(allow, deny)

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
    # Preferencja zrodla ("przelacznik trybow"): 'auto' = dotychczasowa precedencja
    # (OAuth -> klucz z ustawien -> .env); 'oauth' / 'api_key' = wymus dane zrodlo,
    # z lagodnym fallbackiem gdy wybrane jest niedostepne. UI pokazuje FAKTYCZNE
    # aktywne zrodlo (active_auth_source), nie samo zyczenie.
    _AUTH_SOURCES = ("auto", "oauth", "api_key")

    def _stored_key(self) -> str:
        """Klucz API zapisany w ustawieniach (usuwalny z UI)."""
        return (self.read_settings().get("api_key") or "").strip()

    def _env_key(self) -> str:
        """Klucz z XAI_API_KEY (.env) — nieusuwalny z UI (plik usera)."""
        return (os.getenv("XAI_API_KEY") or "").strip()

    def has_stored_key(self) -> bool:
        return bool(self._stored_key())

    def has_env_key(self) -> bool:
        return bool(self._env_key())

    def has_api_key(self) -> bool:
        return bool(self._stored_key() or self._env_key())

    def auth_source_pref(self) -> str:
        pref = (self.read_settings().get("auth_source") or "auto").strip().lower()
        return pref if pref in self._AUTH_SOURCES else "auto"

    def _resolve_auth(self) -> tuple[str, str]:
        """Zwraca (source, key) wg preferencji + dostepnosci; source nalezy do
        {oauth, api_key, env, none}. Ustawienia czytane RAZ (gorace wywolanie na kazde
        zadanie API). Token OAuth pobierany leniwie (moze odswiezac) — tylko gdy potrzebny."""
        s = self.read_settings()
        stored = (s.get("api_key") or "").strip()
        env = (os.getenv("XAI_API_KEY") or "").strip()
        pref = (s.get("auth_source") or "auto").strip().lower()
        if pref not in self._AUTH_SOURCES:
            pref = "auto"
        # TWARDY przelacznik: jawny wybor 'oauth'/'api_key' NIE przeskakuje po cichu na
        # drugie zrodlo (inaczej "API key" uzywaloby OAuth, gdy brak klucza — mylace).
        # 'api_key' obejmuje klucz z ustawien I .env (oba to "klucz API"), bez OAuth.
        # 'auto' = wygodna precedencja z pelnym fallbackiem.
        order = {
            "api_key": ("api_key", "env"),
            "oauth": ("oauth",),
            "auto": ("oauth", "api_key", "env"),
        }[pref]
        for src in order:
            if src == "oauth":
                tok = self.oauth.get_access_token()
                if tok:
                    return "oauth", tok
            elif src == "api_key" and stored:
                return "api_key", stored
            elif src == "env" and env:
                return "env", env
        return "none", ""

    def get_api_key(self) -> str:
        return self._resolve_auth()[1]

    def active_auth_source(self) -> str:
        """Ktore zrodlo JEST faktycznie uzywane przez get_api_key (oauth|api_key|env|none)."""
        return self._resolve_auth()[0]

    def clear_api_key(self) -> None:
        """Usun zapisany klucz API z ustawien (nie dotyka .env ani OAuth)."""
        s = self.read_settings()
        if s.pop("api_key", None) is not None:
            self.write_settings(s)

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

    # --- M19-B8: pamięć hybrydowa (FTS5 + embeddingi) ------------------------
    @property
    def memory(self):
        """Leniwy `MemoryIndex`: embedder xAI (`embeddings.embed_texts` z naszym
        `get_api_key`) + magazyn historii. **Opt-in** (`config.MEMORY_ENABLED`); gdy OFF,
        `injected_text`/`recall`/`index_event` są no-opami (zero kosztu/sieci)."""
        from caelo_core import embeddings
        from caelo_core.memory import MemoryIndex

        if getattr(self, "_memory", None) is None:
            self._memory = MemoryIndex(
                self.history_store,
                lambda texts: embeddings.embed_texts(texts, api_key_provider=self.get_api_key),
                enabled=bool(getattr(config, "MEMORY_ENABLED", False)),
                max_results=int(getattr(config, "MEMORY_MAX_RESULTS", 5)),
                min_score=float(getattr(config, "MEMORY_MIN_SCORE", 0.55)),
            )
        return self._memory

    def _maybe_index_memory(self, ev) -> None:
        """M19-B8: zaindeksuj zdarzenie w pamięci semantycznej (opt-in). Embedding = sieć,
        więc puszczamy je w wątku w tle (fire-and-forget) — gorąca ścieżka nie czeka.
        Błąd połknięty."""
        if ev is None or not getattr(config, "MEMORY_ENABLED", False):
            return
        text = (getattr(ev, "text", "") or "").strip()
        if not text:
            return
        try:
            mem = self.memory
            threading.Thread(target=mem.index_event, args=(ev.id, text),
                             daemon=True).start()
        except Exception:  # noqa: BLE001
            log.warning("Could not schedule memory indexing", exc_info=True)

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
        """Leniwy `McpManager`: skonfigurowane serwery MCP + ich narzędzia. Współdzielony
        przez REST (/mcp), czat (responses) i agenta (session).

        M19-B5 §1.2 (interop): poza natywnym `caelo_mcp.json` scala serwery z ekosystemu —
        globalny `~/.claude.json` (klucz `mcpServers`) i projektowy `<ws>/.mcp.json`.
        Workspace-aware jak `get_lsp`: gdy korzeń się zmieni, przebuduj (tree-kill starych
        podprocesów). Importowane serwery wchodzą WYŁĄCZONE (reżim M16)."""
        from caelo_core.mcp.manager import McpManager

        ws = getattr(self, "_workspace", None)
        root = ws.root if ws is not None else None
        cur = getattr(self, "_mcp", None)
        if cur is None or cur.workspace_root != root:
            if cur is not None:
                try:
                    cur.shutdown()
                except Exception:  # noqa: BLE001
                    log.warning("MCP shutdown failed during rebuild", exc_info=True)
                self._packages = None  # zależy od mcp_manager — odbuduj ze świeżym
            claude_json = getattr(config, "CLAUDE_JSON", None)
            self._mcp = McpManager(config.MCP_FILE, workspace_root=root, claude_json=claude_json)
        return self._mcp

    def reload_mcp(self) -> None:
        """Wymuś przebudowę `McpManager` (po zmianie configu/workspace). Tree-kill bieżących
        serwerów (jak `reload_lsp`); następny dostęp do `.mcp` odbuduje (interop + workspace)."""
        cur = getattr(self, "_mcp", None)
        if cur is not None:
            try:
                cur.shutdown()
            except Exception:  # noqa: BLE001
                log.warning("MCP shutdown failed", exc_info=True)
        self._mcp = None
        self._packages = None  # PackageManager trzyma referencję do mcp_manager

    # --- M19-B3: serwery LSP (intel kodu w trybie Code) -----------------------
    def _discover_lsp_configs(self, root) -> dict:
        """Scal `lsp.json` globalny (DATA_DIR) + projektowy (<ws>/.caelo/lsp.json);
        projekt wygrywa per nazwa serwera. Schemat: {name: {command,args,extensionToLanguage,…}}."""
        cfg: dict = {}
        g = config.load_json_or_backup(config.DATA_DIR / "lsp.json", {}) or {}
        if isinstance(g, dict):
            cfg.update(g)
        if root is not None:
            # M19-B14: scal `.caelo/lsp.json` z łańcucha korzeń-repo→workspace (deeper
            # wygrywa per nazwa serwera). Pojedynczy root → jeden update (jak przed B14).
            from caelo_core.agent.project import project_dir_chain
            for d in project_dir_chain(root):
                proj = config.load_json_or_backup(d / ".caelo" / "lsp.json", {}) or {}
                if isinstance(proj, dict):
                    cfg.update(proj)
        return cfg

    def get_lsp(self):
        """Leniwy `LspManager` dla AKTYWNEGO workspace (rebuild przy zmianie korzenia;
        tree-kill starego). None bez workspace. Współdzielony przez agenta (narzędzie
        lsp + pasywna diagnostyka) i REST (/lsp)."""
        from caelo_core.lsp.manager import LspManager

        ws = self._workspace
        root = ws.root if ws is not None else None
        if root is None:
            return None
        cur = getattr(self, "_lsp", None)
        if cur is None or cur.root != root:
            if cur is not None:
                try:
                    cur.shutdown()
                except Exception:  # noqa: BLE001
                    pass
            self._lsp = LspManager(self._discover_lsp_configs(root), workspace_root=root)
        return self._lsp

    def reload_lsp(self) -> None:
        """Wymuś przebudowę menedżera LSP (po zmianie configu z REST). Tree-kill bieżącego."""
        cur = getattr(self, "_lsp", None)
        if cur is not None:
            try:
                cur.shutdown()
            except Exception:  # noqa: BLE001
                pass
        self._lsp = None

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
        """Leniwy `SkillManager`: pakiety skilli (`SKILLS_DIR/<name>/SKILL.md`).

        M19-B5 §1.3 (interop): poza builtin + `SKILLS_DIR` odkrywa też ekosystem —
        globalny `~/.claude/skills` i projektowe `<ws>/.claude/skills`+`<ws>/.grok/skills`.
        Workspace-aware jak `get_lsp`: przy zmianie korzenia przebuduj (brak podprocesów →
        tylko nowe ścieżki skanu; `_all` i tak czyta dysk świeżo na każde wywołanie)."""
        from caelo_core.skills import SkillManager

        ws = getattr(self, "_workspace", None)
        root = ws.root if ws is not None else None
        cur = getattr(self, "_skills", None)
        if cur is None or cur.workspace_root != root:
            claude_home = getattr(config, "CLAUDE_HOME", None)
            self._skills = SkillManager(config.SKILLS_DIR, workspace_root=root,
                                        claude_home=claude_home)
        return self._skills

    # --- M16: pakiety społeczności / marketplace ---------------------------------
    @property
    def packages(self):
        """Leniwy `PackageManager`: eksport/import pakietów `.caelopkg` (skille/komendy/
        MCP/szablony), registry git i aktualizacje. Zależności (komendy/MCP) wstrzyknięte,
        by instalacja trafiała do tych samych rejestrów co M14 (jeden reżim zgody)."""
        from caelo_core.packages import PackageManager

        if getattr(self, "_packages", None) is None:
            self._packages = PackageManager(
                config.PACKAGES_FILE, config.SKILLS_DIR, config.TEMPLATES_DIR,
                command_registry=self.commands, mcp_manager=self.mcp)
        return self._packages

    def shutdown(self) -> None:
        """Sprzątanie na zamknięciu sidecara: ubij podprocesy serwerów MCP (tree-kill)."""
        mgr = getattr(self, "_mcp", None)
        if mgr is not None:
            try:
                mgr.shutdown()
            except Exception:  # noqa: BLE001
                log.warning("MCP shutdown failed", exc_info=True)
        lsp = getattr(self, "_lsp", None)  # M19-B3: tree-kill serwerów LSP
        if lsp is not None:
            try:
                lsp.shutdown()
            except Exception:  # noqa: BLE001
                log.warning("LSP shutdown failed", exc_info=True)

    def record_event(self, *, mode: str, text: str = "", artifact_id=None,
                     project_id=None, meta=None):
        """Dorzuć zdarzenie do wspólnej, przeszukiwalnej historii huba (M9-B2).
        Bez jawnego `project_id` stempluje AKTYWNYM projektem (M9-B5). NIGDY nie
        wywraca ścieżki użytkownika — błąd magazynu jest logowany i połykany."""
        if project_id is not None:
            pid = project_id
        elif mode == "code":
            # M22: zdarzenia agenta (Code) stempluj projektem workspace'u (kind='code'),
            # nie projektem czatu — rozdzielenie scope'ów.
            pid = self._code_project_id or self.current_project_id
        else:
            pid = self.current_project_id
        try:
            ev = self.history_store.record_event(
                mode=mode, text=text or "", artifact_id=artifact_id,
                project_id=pid, meta=meta,
            )
        except Exception:
            log.warning("Could not record history event (mode=%s)", mode, exc_info=True)
            return None
        self._maybe_index_memory(ev)  # M19-B8: opt-in, w tle, błąd połknięty
        return ev

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

    # --- projekty (M9-B5; M22: rozdzielone na kind chat/code) ---
    def list_projects(self, kind: Optional[str] = None):
        """M22: `kind` filtruje typ ('chat'|'code'); None = wszystkie."""
        return self.history_store.list_projects(kind=kind)

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

    def update_project(self, project_id, *, name=None, instructions=None):
        """M22: zmień nazwę / instrukcje projektu. None → projekt nie istnieje."""
        return self.history_store.update_project(
            project_id, name=name, instructions=instructions)

    def delete_project(self, project_id):
        """M22: usuń projekt + jego historię/artefakty/kolekcje (store) oraz lokalny
        katalog dokumentów wiedzy. Czyści aktywny projekt czatu / workspace, jeśli go
        dotyczył. Zwraca skasowany Project (None gdy nie istniał)."""
        proj = self.history_store.delete_project(project_id)
        if proj is None:
            return None
        try:
            import shutil
            docs = Path(config.PROJECT_DOCS_DIR) / project_id
            if docs.is_dir():
                shutil.rmtree(docs, ignore_errors=True)
        except Exception:
            log.warning("Could not remove project docs dir", exc_info=True)
        if self.current_project_id == project_id:
            self.select_project(None)
        if self._code_project_id == project_id:
            self._code_project_id = None
        return proj

    # --- wiedza projektu / kolekcje → CollectionsMixin (backend_collections.py, P2-13) ---
    # --- generacja i zapis mediów → MediaMixin (backend_media.py, P2-13) ---


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


# Warstwa autoryzacji (require_token / ws_authorized / _ws_origin_ok / _warn_no_token)
# wydzielona do `caelo_core/auth_tokens.py` (P2-13) — czysta, testowalna bez Backendu.
# Re-eksport jest na górze tego modułu, więc istniejące importy działają bez zmian.
