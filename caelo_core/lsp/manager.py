"""Menedżer serwerów LSP (M19-B3).

Routuje pliki do serwerów po rozszerzeniu (`extensionToLanguage`), trzyma leniwe
`LspClient`-y (start na pierwsze użycie), restartuje po awarii (`restartOnCrash`/
`maxRestarts`). Schemat configu jak w Grok CLI/Claude Code (`lsp.json`):

    { "<name>": { "command": "...", "args": [...], "extensionToLanguage": {".ts":"typescript"},
                  "env": {...}, "startupTimeout": 30000, "restartOnCrash": true, "maxRestarts": 3 } }

Ścieżki przekazywane do metod są ABSOLUTNE (sandbox/odczyt robi wołający, np.
`session.py` przez `Workspace.resolve`) — menedżer ich nie czyta z dysku.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from caelo_core.lsp.client import DEFAULT_DIAGNOSTICS_WAIT_S, LspClient

log = logging.getLogger(__name__)


class LspManager:
    def __init__(self, configs: dict, *, workspace_root) -> None:
        self.root = workspace_root  # Path | None
        self._configs: dict = configs or {}
        self._clients: dict[str, LspClient] = {}
        self._restarts: dict[str, int] = {}
        self._ext_to_name: dict[str, str] = {}
        self._ext_to_lang: dict[str, str] = {}
        for name, c in self._configs.items():
            for ext, lang in (c.get("extensionToLanguage") or {}).items():
                e = (ext if ext.startswith(".") else "." + ext).lower()
                self._ext_to_name.setdefault(e, name)
                self._ext_to_lang[e] = lang

    def enabled(self) -> bool:
        """Czy są jakiekolwiek serwery skonfigurowane (decyzja o advertowaniu narzędzia)."""
        return bool(self._configs)

    # --- lifecycle klientów ------------------------------------------------------
    def _lang_for(self, abs_path: str) -> str:
        return self._ext_to_lang.get(Path(abs_path).suffix.lower(), "")

    def _ensure(self, name: Optional[str]) -> Optional[LspClient]:
        if not name:
            return None
        c = self._clients.get(name)
        if c is not None and c.alive:
            return c
        cfg = self._configs.get(name)
        if not cfg or not cfg.get("command"):
            return None
        if c is not None:  # padł — restart wg polityki
            maxr = int(cfg.get("maxRestarts", 3))
            if not cfg.get("restartOnCrash", True) or self._restarts.get(name, 0) >= maxr:
                return None
            self._restarts[name] = self._restarts.get(name, 0) + 1
        command = [cfg["command"], *(cfg.get("args") or [])]
        cwd = str(self.root) if self.root else os.getcwd()
        client = LspClient(name, command, cwd=cwd, env=cfg.get("env"),
                           startup_timeout_s=float(cfg.get("startupTimeout", 30000)) / 1000.0)
        try:
            client.start()
        except Exception:  # noqa: BLE001
            log.warning("LSP server %r failed to start", name, exc_info=True)
            return None
        self._clients[name] = client
        return client

    def _client_for(self, abs_path: str) -> Optional[LspClient]:
        return self._ensure(self._ext_to_name.get(Path(abs_path).suffix.lower()))

    # --- API dla agenta ----------------------------------------------------------
    def diagnostics(self, abs_path: str, text: str,
                    timeout: float = DEFAULT_DIAGNOSTICS_WAIT_S) -> list:
        c = self._client_for(abs_path)
        if c is None:
            return []
        try:
            return c.wait_diagnostics(abs_path, text, self._lang_for(abs_path), timeout)
        except Exception:  # noqa: BLE001
            log.warning("LSP diagnostics failed for %s", abs_path, exc_info=True)
            return []

    def query(self, action: str, abs_path: str, text: str, line: int, character: int) -> object:
        c = self._client_for(abs_path)
        if c is None:
            return None
        return c.query(action, abs_path, text, self._lang_for(abs_path), line, character)

    # --- API dla REST/UI ---------------------------------------------------------
    def list_servers(self) -> list:
        return [{
            "name": n,
            "command": c.get("command"),
            "args": c.get("args") or [],
            "languages": sorted(set((c.get("extensionToLanguage") or {}).values())),
            "running": n in self._clients and self._clients[n].alive,
        } for n, c in self._configs.items()]

    def restart(self, name: str) -> bool:
        c = self._clients.pop(name, None)
        if c is not None:
            try:
                c.stop()
            except Exception:  # noqa: BLE001
                pass
        self._restarts[name] = 0
        return self._ensure(name) is not None

    def shutdown(self) -> None:
        for c in list(self._clients.values()):
            try:
                c.stop()
            except Exception:  # noqa: BLE001
                pass
        self._clients.clear()
