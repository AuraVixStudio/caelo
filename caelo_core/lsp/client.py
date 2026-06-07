"""Klient LSP po stdio (ramkowanie Content-Length) — M19-B3.

⚠ RÓŻNICA OD MCP: LSP ramkuje wiadomości nagłówkiem `Content-Length: N\\r\\n\\r\\n<body>`
(N = długość ciała w bajtach UTF-8), NIE newline-delimited. Stąd osobny czytnik (proces
w trybie BINARNYM — bajt-dokładne `read(n)`), nie kopia `StdioTransport`.

Wątkowość jak `McpClient`: wątek-czytnik (stdout → korelacja odpowiedzi po `id` +
bufor `publishDiagnostics` per URI), `request()` blokuje wątek wołającego na `Event`
(timeout). Warstwa SYNCHRONICZNA (wołana z wątków-workerów tury agenta).

Hartowanie podprocesu jak `tools.run_command`/MCP: `scrubbed_env()` (bez sekretów) +
`_tree_kill` na zamknięciu. Caelo NIE bundluje serwerów — `command` musi być na PATH.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
from collections import deque
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse

from caelo_core.agent.tools import _tree_kill, scrubbed_env

log = logging.getLogger(__name__)

DEFAULT_STARTUP_TIMEOUT_S = 30.0
DEFAULT_REQUEST_TIMEOUT_S = 15.0
DEFAULT_DIAGNOSTICS_WAIT_S = 1.5   # best-effort: ile czekać na publishDiagnostics po edycie
STDERR_RING = 50


class LspError(Exception):
    pass


def _prepare_argv(command: list[str]) -> list[str]:
    """Rozwiń exe przez PATH; na Windows owiń shimy `.cmd`/`.bat` w `cmd /c` (jak MCP)."""
    argv = list(command)
    if not argv:
        raise LspError("empty LSP server command")
    resolved = shutil.which(argv[0]) or argv[0]
    argv[0] = resolved
    if os.name == "nt" and resolved.lower().endswith((".cmd", ".bat")):
        return ["cmd", "/c", *argv]
    return argv


def path_to_uri(path: str) -> str:
    return Path(path).resolve().as_uri()


def uri_to_path(uri: str) -> str:
    if not uri.startswith("file:"):
        return uri
    p = urlparse(uri)
    path = unquote(p.path)
    if os.name == "nt" and path.startswith("/") and len(path) > 2 and path[2] == ":":
        path = path[1:]  # /C:/x -> C:/x
    return path


class LspClient:
    """Jeden serwer LSP. Leniwy: `start()` uruchamia podproces i robi handshake."""

    def __init__(self, name: str, command: list[str], *, cwd: str,
                 env: Optional[dict] = None,
                 startup_timeout_s: float = DEFAULT_STARTUP_TIMEOUT_S) -> None:
        self.name = name
        self.command = command
        self.cwd = cwd
        self._env = {**scrubbed_env(), **(env or {})}
        self._startup = startup_timeout_s
        self._proc: Optional[subprocess.Popen] = None
        self._reader: Optional[threading.Thread] = None
        self._pending: dict = {}
        self._diagnostics: dict[str, list] = {}
        self._diag_seq: dict[str, int] = {}
        self._opened: set[str] = set()
        self._versions: dict[str, int] = {}
        self._next = 0
        self._id_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._stderr_ring: deque[str] = deque(maxlen=STDERR_RING)

    # --- lifecycle ---------------------------------------------------------------
    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> None:
        argv = _prepare_argv(self.command)
        # M19-B7: opcjonalny sandbox OS (off-by-default → no-op). Owija argv; FAIL-OPEN.
        # Root = korzeń workspace (cwd serwera LSP) → profil `workspace` (read wszędzie) OK.
        try:
            from caelo_core import sandbox
            argv = sandbox.wrap_command(argv, root=self.cwd)
        except Exception:  # noqa: BLE001
            pass
        popen_kwargs: dict = {}
        if os.name != "nt":
            popen_kwargs["start_new_session"] = True  # własna grupa → tree-kill (killpg)
        try:
            self._proc = subprocess.Popen(
                argv, cwd=self.cwd, env=self._env,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                bufsize=0, **popen_kwargs,  # binarny — bajt-dokładne ramkowanie
            )
        except Exception as exc:  # noqa: BLE001
            raise LspError(f"cannot start LSP server {self.name!r}: {exc}")

        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        threading.Thread(target=self._drain_stderr, daemon=True).start()
        self._initialize()

    def _drain_stderr(self) -> None:
        try:
            assert self._proc and self._proc.stderr
            for line in self._proc.stderr:
                self._stderr_ring.append(line.decode("utf-8", "replace").rstrip())
        except Exception:  # noqa: BLE001
            pass

    def stop(self) -> None:
        if self._proc is None:
            return
        try:
            self._send({"jsonrpc": "2.0", "id": self._new_id(), "method": "shutdown"})
            self._send({"jsonrpc": "2.0", "method": "exit"})
        except Exception:  # noqa: BLE001
            pass
        _tree_kill(self._proc)
        self._proc = None

    # --- transport (Content-Length) ----------------------------------------------
    def _new_id(self) -> int:
        with self._id_lock:
            self._next += 1
            return self._next

    def _send(self, obj: dict) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise LspError("LSP server not running")
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        with self._write_lock:
            self._proc.stdin.write(header + body)
            self._proc.stdin.flush()

    def _read_loop(self) -> None:
        out = self._proc.stdout if self._proc else None
        if out is None:
            return
        try:
            while True:
                # nagłówki do pustej linii
                length = 0
                line = out.readline()
                if not line:
                    break  # EOF (serwer padł)
                while line not in (b"\r\n", b"\n"):
                    if b":" in line:
                        k, v = line.split(b":", 1)
                        if k.strip().lower() == b"content-length":
                            try:
                                length = int(v.strip())
                            except ValueError:
                                length = 0
                    line = out.readline()
                    if not line:
                        return
                body = out.read(length) if length > 0 else b""
                if not body:
                    continue
                try:
                    msg = json.loads(body.decode("utf-8"))
                except Exception:  # noqa: BLE001
                    continue
                self._on_message(msg)
        except Exception:  # noqa: BLE001
            log.debug("LSP reader stopped for %s", self.name, exc_info=True)

    def _on_message(self, msg: dict) -> None:
        if "id" in msg and ("result" in msg or "error" in msg) and "method" not in msg:
            slot = self._pending.get(msg["id"])
            if slot:
                slot["result"] = msg.get("result")
                slot["error"] = msg.get("error")
                slot["event"].set()
            return
        method = msg.get("method")
        if method == "textDocument/publishDiagnostics":
            p = msg.get("params") or {}
            uri = p.get("uri", "")
            self._diagnostics[uri] = p.get("diagnostics") or []
            self._diag_seq[uri] = self._diag_seq.get(uri, 0) + 1
        elif "id" in msg and method:
            # żądanie serwer→klient (np. client/registerCapability, workspace/configuration)
            # — odpowiedz neutralnie, by serwer nie wisiał.
            try:
                self._send({"jsonrpc": "2.0", "id": msg["id"], "result": None})
            except Exception:  # noqa: BLE001
                pass

    def _request(self, method: str, params: Optional[dict], timeout: float):
        rid = self._new_id()
        event = threading.Event()
        self._pending[rid] = {"event": event, "result": None, "error": None}
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        if not event.wait(timeout=timeout):
            self._pending.pop(rid, None)
            raise LspError(f"LSP request {method} timed out after {timeout}s")
        slot = self._pending.pop(rid, {})
        if slot.get("error"):
            raise LspError(f"LSP {method} error: {slot['error']}")
        return slot.get("result")

    def _notify(self, method: str, params: Optional[dict]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    # --- protokół ----------------------------------------------------------------
    def _initialize(self) -> None:
        self._request("initialize", {
            "processId": os.getpid(),
            "rootUri": path_to_uri(self.cwd),
            "capabilities": {
                "textDocument": {
                    "synchronization": {"didSave": False, "dynamicRegistration": False},
                    "publishDiagnostics": {},
                    "hover": {"contentFormat": ["plaintext", "markdown"]},
                    "definition": {}, "references": {}, "documentSymbol": {},
                },
                "workspace": {},
            },
        }, timeout=self._startup)
        self._notify("initialized", {})

    def open_or_update(self, abs_path: str, text: str, language_id: str) -> None:
        uri = path_to_uri(abs_path)
        if uri not in self._opened:
            self._versions[uri] = 1
            self._notify("textDocument/didOpen", {"textDocument": {
                "uri": uri, "languageId": language_id, "version": 1, "text": text}})
            self._opened.add(uri)
        else:
            v = self._versions.get(uri, 1) + 1
            self._versions[uri] = v
            self._notify("textDocument/didChange", {
                "textDocument": {"uri": uri, "version": v},
                "contentChanges": [{"text": text}]})

    def diagnostics_for(self, abs_path: str) -> list:
        return list(self._diagnostics.get(path_to_uri(abs_path), []))

    def wait_diagnostics(self, abs_path: str, text: str, language_id: str,
                         timeout: float = DEFAULT_DIAGNOSTICS_WAIT_S) -> list:
        """didOpen/didChange + poczekaj na NOWE publishDiagnostics (best-effort) → lista."""
        uri = path_to_uri(abs_path)
        seq0 = self._diag_seq.get(uri, 0)
        self.open_or_update(abs_path, text, language_id)
        # poll (krótkie okno) aż dojdzie świeża diagnostyka dla tego URI lub timeout
        import time
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._diag_seq.get(uri, 0) > seq0:
                break
            time.sleep(0.05)
        return self.diagnostics_for(abs_path)

    def query(self, action: str, abs_path: str, text: str, language_id: str,
              line: int, character: int) -> object:
        self.open_or_update(abs_path, text, language_id)
        uri = path_to_uri(abs_path)
        if action == "documentSymbol":
            return self._request("textDocument/documentSymbol",
                                 {"textDocument": {"uri": uri}}, DEFAULT_REQUEST_TIMEOUT_S)
        params = {"textDocument": {"uri": uri}, "position": {"line": line, "character": character}}
        if action == "references":
            params["context"] = {"includeDeclaration": True}
        return self._request("textDocument/" + action, params, DEFAULT_REQUEST_TIMEOUT_S)
