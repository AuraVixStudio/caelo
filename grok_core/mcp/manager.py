"""Menedżer serwerów MCP — M14-B1/B2.

Trzyma konfigurację (`grok_mcp.json`, atomowo + `load_json_or_backup`) i **runtime**
połączeń. Serwery `stdio` startują lokalnie (klient z `client.py`); serwery `remote`
NIE startują tu — to native remote MCP (B3) konsumowane przez `responses_client`
(wykonanie po stronie xAI). Narzędzia są namespace'owane (`mcp__<server>__<tool>`),
a routing wywołań idzie przez jawny słownik (sanityzacja/obcięcie nazw nie psuje
adresowania). Klasyfikacja do bramki: `annotations.readOnlyHint == True` → READONLY
(bez zgody), inaczej → MUTATING (gate jak edycje agenta).

Bezpieczeństwo: start serwera = uruchomienie dowolnej komendy → jawny `start_server`
(UI pyta o zgodę, jak run_command). Sekrety (`authorization`, wartości `env`) NIE
wracają do renderera (`public_config` maskuje). Plik `grok_mcp.json` jest gitignored.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from pathlib import Path
from typing import Optional

import config  # type: ignore

from grok_core.mcp.client import (
    McpClient,
    McpError,
    StdioTransport,
    flatten_tool_result,
)

log = logging.getLogger(__name__)

_NAME_OK = re.compile(r"[^a-zA-Z0-9_-]")
MAX_FN_NAME = 64  # limit nazwy funkcji w function-calling (xAI/OpenAI)
VALID_TRANSPORTS = ("stdio", "remote")  # "http" (lokalny Streamable HTTP) — odłożony (hybryda)


def _slug(text: str) -> str:
    return _NAME_OK.sub("_", (text or "").strip()) or "srv"


def _qualify(server_id: str, tool_name: str) -> str:
    """Globalnie unikalna, function-call-safe nazwa narzędzia. Routing i tak idzie
    przez słownik, ale trzymamy ją czytelną i deterministyczną."""
    raw = f"mcp__{_slug(server_id)}__{_slug(tool_name)}"
    if len(raw) <= MAX_FN_NAME:
        return raw
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
    return raw[: MAX_FN_NAME - 9] + "_" + digest


class McpServer:
    """Runtime jednego serwera: config + klient + odkryte narzędzia/zasoby/prompty."""

    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg
        self.client: Optional[McpClient] = None
        self.status: str = "stopped"  # stopped | starting | ready | error
        self.error: str = ""
        self.tools: list[dict] = []
        self.resources: list[dict] = []
        self.prompts: list[dict] = []

    @property
    def id(self) -> str:
        return self.cfg.get("id", "")

    @property
    def transport(self) -> str:
        return (self.cfg.get("transport") or "stdio").lower()

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.get("enabled", True))

    def start(self) -> None:
        if self.transport == "remote":
            # Native remote MCP (B3) — nie startuje lokalnie; obsługą zajmuje się xAI.
            self.status = "remote"
            return
        if self.transport != "stdio":
            self.status = "error"
            self.error = f"transport '{self.transport}' is not supported locally yet"
            return
        command = self.cfg.get("command") or []
        if not command:
            self.status = "error"
            self.error = "stdio server has no command"
            return
        self.status = "starting"
        self.error = ""
        client = McpClient(
            StdioTransport(command, cwd=self.cfg.get("cwd") or None,
                           env=self.cfg.get("env") or None),
            name=self.id,
        )
        try:
            client.connect()
            self.tools = client.list_tools()
            self.resources = client.list_resources()
            self.prompts = client.list_prompts()
        except McpError as exc:
            self.status = "error"
            self.error = str(exc)[:300]
            try:
                client.close()
            except Exception:  # noqa: BLE001
                pass
            return
        except Exception as exc:  # noqa: BLE001
            self.status = "error"
            self.error = f"unexpected MCP error: {str(exc)[:200]}"
            try:
                client.close()
            except Exception:  # noqa: BLE001
                pass
            return
        self.client = client
        self.status = "ready"

    def stop(self) -> None:
        if self.client is not None:
            try:
                self.client.close()
            except Exception:  # noqa: BLE001
                pass
        self.client = None
        self.tools = []
        self.resources = []
        self.prompts = []
        if self.status != "error":
            self.status = "stopped"

    def is_ready(self) -> bool:
        return self.status == "ready" and self.client is not None and self.client.is_alive()


class McpManager:
    """Wiele serwerów MCP + agregacja narzędzi + routing wywołań + klasyfikacja gate."""

    def __init__(self, config_path: Optional[Path] = None) -> None:
        self._path = config_path or config.MCP_FILE
        self._lock = threading.RLock()
        self._servers: dict[str, McpServer] = {}
        # qualified_name -> (server_id, raw_tool_name) — adresowanie odporne na sanityzację.
        self._routes: dict[str, tuple[str, str]] = {}
        self._load()

    # --- trwałość ---
    def _load(self) -> None:
        data = config.load_json_or_backup(self._path, {}) or {}
        servers = data.get("servers") if isinstance(data, dict) else None
        for cfg in servers or []:
            if isinstance(cfg, dict) and cfg.get("id"):
                self._servers[cfg["id"]] = McpServer(dict(cfg))

    def _save(self) -> None:
        data = {"servers": [s.cfg for s in self._servers.values()]}
        try:
            config.atomic_write_text(self._path, json.dumps(data, indent=2, ensure_ascii=False))
        except Exception:  # noqa: BLE001
            log.warning("Failed to save %s", getattr(self._path, "name", self._path),
                        exc_info=True)

    # --- konfiguracja serwerów ---
    def add_server(self, cfg: dict) -> dict:
        """Dodaj/zaktualizuj serwer. Waliduje transport i wymagane pola. Nie startuje."""
        sid = _slug(cfg.get("id") or cfg.get("name") or "server")
        transport = (cfg.get("transport") or "stdio").lower()
        if transport not in VALID_TRANSPORTS:
            raise ValueError(f"transport must be one of {VALID_TRANSPORTS}")
        if transport == "stdio" and not (cfg.get("command") or []):
            raise ValueError("stdio server requires a non-empty 'command' (argv list)")
        if transport == "remote" and not cfg.get("url"):
            raise ValueError("remote server requires a 'url'")
        clean = {
            "id": sid,
            "name": cfg.get("name") or sid,
            "transport": transport,
            "enabled": bool(cfg.get("enabled", True)),
        }
        if transport == "stdio":
            cmd = cfg.get("command")
            if isinstance(cmd, str):
                cmd = cmd.split()
            clean["command"] = [str(x) for x in (cmd or [])]
            clean["cwd"] = cfg.get("cwd") or None
            clean["env"] = {str(k): str(v) for k, v in (cfg.get("env") or {}).items()}
        else:  # remote
            clean["url"] = str(cfg.get("url"))
            if cfg.get("authorization"):
                clean["authorization"] = str(cfg["authorization"])
            clean["server_label"] = _slug(cfg.get("server_label") or sid)
        with self._lock:
            # Zachowaj uruchomiony klient, jeśli edytujemy istniejący wpis bez restartu.
            existing = self._servers.get(sid)
            srv = McpServer(clean)
            if existing is not None and existing.is_ready():
                # Restart wymagany, by zmiany weszły — zatrzymaj stary.
                existing.stop()
            self._servers[sid] = srv
            self._save()
        return self.public_config(sid)

    def remove_server(self, sid: str) -> bool:
        with self._lock:
            srv = self._servers.pop(sid, None)
            if srv is None:
                return False
            srv.stop()
            self._routes = {k: v for k, v in self._routes.items() if v[0] != sid}
            self._save()
        return True

    def set_enabled(self, sid: str, enabled: bool) -> dict:
        with self._lock:
            srv = self._servers.get(sid)
            if srv is None:
                raise ValueError("unknown server")
            srv.cfg["enabled"] = bool(enabled)
            if not enabled:
                srv.stop()
            self._save()
        return self.public_config(sid)

    # --- cykl życia (start jawny — gate jak run_command) ---
    def start_server(self, sid: str) -> dict:
        with self._lock:
            srv = self._servers.get(sid)
            if srv is None:
                raise ValueError("unknown server")
            if srv.is_ready():
                self._rebuild_routes_locked()
                return self.status(sid)
            srv.cfg["enabled"] = True
        # connect() blokuje (subprocess + handshake) — poza lockiem, by nie zamrozić
        # innych tras. Re-lock dopiero przy aktualizacji routingu.
        srv.start()
        with self._lock:
            self._rebuild_routes_locked()
            self._save()
        return self.status(sid)

    def stop_server(self, sid: str) -> dict:
        with self._lock:
            srv = self._servers.get(sid)
            if srv is None:
                raise ValueError("unknown server")
            srv.stop()
            self._rebuild_routes_locked()
        return self.status(sid)

    def start_enabled(self) -> None:
        """Wystartuj wszystkie włączone serwery stdio (np. po starcie sidecara, jeśli
        user wcześniej je włączył). Błędy izolowane per serwer."""
        for sid in list(self._servers):
            srv = self._servers.get(sid)
            if srv and srv.enabled and srv.transport == "stdio" and not srv.is_ready():
                try:
                    self.start_server(sid)
                except Exception:  # noqa: BLE001
                    log.warning("MCP autostart failed for %s", sid, exc_info=True)

    def shutdown(self) -> None:
        with self._lock:
            for srv in self._servers.values():
                srv.stop()
            self._routes.clear()

    # --- routing narzędzi ---
    def _rebuild_routes_locked(self) -> None:
        routes: dict[str, tuple[str, str]] = {}
        for srv in self._servers.values():
            if not srv.is_ready():
                continue
            for tool in srv.tools:
                name = tool.get("name")
                if not name:
                    continue
                routes[_qualify(srv.id, name)] = (srv.id, name)
        self._routes = routes

    def _find_tool_def(self, sid: str, raw_name: str) -> Optional[dict]:
        srv = self._servers.get(sid)
        if not srv:
            return None
        for tool in srv.tools:
            if tool.get("name") == raw_name:
                return tool
        return None

    def list_tools(self) -> list[dict]:
        """Zagregowane narzędzia gotowych serwerów (namespaced). Każdy wpis:
        {qualified_name, server_id, name, description, input_schema, readonly}."""
        out: list[dict] = []
        with self._lock:
            for srv in self._servers.values():
                if not srv.is_ready():
                    continue
                for tool in srv.tools:
                    name = tool.get("name")
                    if not name:
                        continue
                    out.append({
                        "qualified_name": _qualify(srv.id, name),
                        "server_id": srv.id,
                        "name": name,
                        "description": tool.get("description") or "",
                        "input_schema": tool.get("inputSchema") or {"type": "object"},
                        "readonly": _is_readonly(tool),
                    })
        return out

    def tool_defs_for_responses(self) -> list[dict]:
        """Definicje function-calling (format xAI/OpenAI) dla `responses_client`/agenta.
        Tylko z gotowych, włączonych serwerów lokalnych."""
        defs: list[dict] = []
        for t in self.list_tools():
            schema = t["input_schema"] if isinstance(t["input_schema"], dict) else {"type": "object"}
            defs.append({
                "type": "function",
                "function": {
                    "name": t["qualified_name"],
                    "description": (t["description"] or t["name"])[:1024],
                    "parameters": schema or {"type": "object"},
                },
            })
        return defs

    def is_mcp_tool(self, qualified_name: str) -> bool:
        with self._lock:
            return qualified_name in self._routes

    def is_mutating(self, qualified_name: str) -> bool:
        """Czy wywołanie wymaga zgody (gate). READONLY (readOnlyHint) → False."""
        with self._lock:
            route = self._routes.get(qualified_name)
        if route is None:
            return True  # nieznane → ostrożnie pytaj
        tool = self._find_tool_def(*route)
        return not _is_readonly(tool or {})

    def describe_tool(self, qualified_name: str) -> dict:
        """Opis do karty zatwierdzenia (M14-F2): serwer + nazwa + opis."""
        with self._lock:
            route = self._routes.get(qualified_name)
            if route is None:
                return {"qualified_name": qualified_name, "server_id": "", "name": qualified_name}
            sid, raw = route
            tool = self._find_tool_def(sid, raw) or {}
            return {"qualified_name": qualified_name, "server_id": sid, "name": raw,
                    "description": tool.get("description") or "",
                    "readonly": _is_readonly(tool)}

    def call_tool(self, qualified_name: str, arguments: Optional[dict] = None) -> str:
        """Zwołaj narzędzie MCP po nazwie namespaced. Zwraca spłaszczony tekst wyniku
        (gotowy do oddania modelowi). Rzuca McpError, gdy serwer nieosiągalny."""
        with self._lock:
            route = self._routes.get(qualified_name)
            srv = self._servers.get(route[0]) if route else None
            client = srv.client if srv else None
            raw_name = route[1] if route else None
        if client is None or raw_name is None:
            raise McpError(f"unknown or unavailable MCP tool: {qualified_name}")
        result = client.call_tool(raw_name, arguments or {})
        return flatten_tool_result(result)

    # --- native remote MCP (B3) ---
    def remote_tool_blocks(self) -> list[dict]:
        """Bloki `tools=[{type:'mcp',...}]` dla żądania Responses (B3) — tylko włączone
        serwery `remote`. Wykonanie po stronie xAI; brak lokalnej bramki (jawne w UI)."""
        blocks: list[dict] = []
        with self._lock:
            for srv in self._servers.values():
                if srv.transport != "remote" or not srv.enabled:
                    continue
                block = {
                    "type": "mcp",
                    "server_label": srv.cfg.get("server_label") or srv.id,
                    "server_url": srv.cfg.get("url"),
                }
                if srv.cfg.get("authorization"):
                    block["authorization"] = srv.cfg["authorization"]
                blocks.append(block)
        return blocks

    # --- widoki dla renderera (bez sekretów) ---
    def public_config(self, sid: str) -> dict:
        srv = self._servers.get(sid)
        if srv is None:
            raise ValueError("unknown server")
        cfg = srv.cfg
        out = {
            "id": srv.id,
            "name": cfg.get("name") or srv.id,
            "transport": srv.transport,
            "enabled": srv.enabled,
        }
        if srv.transport == "stdio":
            out["command"] = list(cfg.get("command") or [])
            out["cwd"] = cfg.get("cwd") or None
            # Maskuj wartości env — zwracamy tylko klucze (sekrety nie wracają do UI).
            out["env_keys"] = sorted((cfg.get("env") or {}).keys())
        else:
            out["url"] = cfg.get("url")
            out["server_label"] = cfg.get("server_label") or srv.id
            out["has_authorization"] = bool(cfg.get("authorization"))
        return out

    def status(self, sid: str) -> dict:
        srv = self._servers.get(sid)
        if srv is None:
            raise ValueError("unknown server")
        pub = self.public_config(sid)
        pub.update({
            "status": srv.status,
            "error": srv.error,
            "tools": [{"name": t.get("name"), "description": t.get("description") or "",
                       "readonly": _is_readonly(t)} for t in srv.tools],
            "tool_count": len(srv.tools),
            "resource_count": len(srv.resources),
            "prompt_count": len(srv.prompts),
        })
        if srv.client is not None:
            pub["server_info"] = srv.client.server_info
        return pub

    def all_status(self) -> list[dict]:
        with self._lock:
            return [self.status(sid) for sid in self._servers]


def _is_readonly(tool: dict) -> bool:
    """Narzędzie jest READONLY tylko gdy serwer JAWNIE oznaczył `annotations.readOnlyHint`.
    Brak adnotacji → traktuj jak mutujące (bezpieczny default → bramka)."""
    ann = tool.get("annotations") if isinstance(tool, dict) else None
    if isinstance(ann, dict) and ann.get("readOnlyHint") is True:
        # destructiveHint=True nadpisuje (serwer sam sobie przeczy) → pytaj.
        return ann.get("destructiveHint") is not True
    return False
