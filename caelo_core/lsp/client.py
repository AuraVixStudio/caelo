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
DEFAULT_DIAGNOSTICS_WAIT_S = 5.0   # best-effort: ile czekać na publishDiagnostics po edycie
                                    # (LIVE 2026-06-17: 1.5 s za krótko dla pyright/duży workspace —
                                    # pętla i tak przerywa NATYCHMIAST gdy diagnostyka dojdzie, więc
                                    # czysty plik nie płaci pełnego budżetu; płaci go tylko brak wyniku).
DIAG_EMPTY_GRACE_S = 1.0           # po PIERWSZYM (często pustym) publishDiagnostics daj serwerowi
                                    # chwilę na DOSŁANIE właściwego wyniku analizy (pyright: empty→full).
STDERR_RING = 50
MAX_LSP_BODY_BYTES = 32 * 1024 * 1024   # S34-f-1: clamp absurdalnego Content-Length (OOM)
STOP_EXIT_WAIT_S = 2.0                   # S34-f-2: okno na czyste wyjście przed tree-kill


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


def canon_key(path_or_uri: str) -> str:
    """Kanoniczny klucz pliku do MATCHOWANIA diagnostyk — odporny na różnice formatu URI.
    Na Windows pyright publikuje `file:///g%3A/...` (mała litera dysku, `:`→`%3A`), a nasze
    `path_to_uri` daje `file:///G:/...` — surowe stringi URI się NIE zgadzają (LIVE 2026-06-17:
    diagnostyki zawsze puste). Sprowadzamy oba do ścieżki i `normcase`+`normpath` (na Win
    lowercase + ujednolicone separatory), więc klucz zapisu i odczytu jest ten sam."""
    p = uri_to_path(path_or_uri) if path_or_uri.startswith("file:") else path_or_uri
    # realpath (nie sam normpath): serwer publikuje URI dla ŚCIEŻKI RZECZYWISTEJ
    # (`path_to_uri` = `Path.resolve()`), więc klucz ZAPISU jest po symlinkach
    # rozwiązany. Klucz ODCZYTU musi być tak samo — inaczej na macOS (`/var`→
    # `/private/var` w tempdirach) i Windows CI (nazwy 8.3) zapis≠odczyt i diagnostyki
    # nigdy się nie matchują. realpath robi też normpath; normcase ujednolica wielkość.
    try:
        p = os.path.realpath(p)
    except OSError:
        p = os.path.normpath(p)
    return os.path.normcase(p)


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
        proc = self._proc
        try:
            self._send({"jsonrpc": "2.0", "id": self._new_id(), "method": "shutdown"})
            self._send({"jsonrpc": "2.0", "method": "exit"})
        except Exception:  # noqa: BLE001
            pass
        # S34-f-2: daj serwerowi OKNO na czyste wyjście (flush indeksu) — dopiero potem
        # tree-kill (jak StdioTransport.close w MCP; wcześniej LSP killował natychmiast).
        try:
            proc.wait(timeout=STOP_EXIT_WAIT_S)
        except Exception:  # noqa: BLE001 (TimeoutExpired itd.) — wymuś
            _tree_kill(proc)
            try:
                proc.wait(timeout=3)
            except Exception:  # noqa: BLE001
                pass
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

    @staticmethod
    def _read_exact(stream, n: int) -> bytes:
        """Doczytaj DOKŁADNIE `n` bajtów ciała. P1-C: `read(n)` na pipe (bufsize=0)
        może zwrócić mniej niż `n` — większe ciała (diagnostyki/hover) przychodziły
        obcięte → `json.loads` padał → wiadomość ginęła. `b''` = EOF: zwróć partial,
        caller przerywa pętlę czytnika (jak istniejące `if not line: break`)."""
        buf = bytearray()
        while len(buf) < n:
            chunk = stream.read(n - len(buf))
            if not chunk:
                return bytes(buf)  # pipe zamknięty w trakcie ciała → partial
            buf.extend(chunk)
        return bytes(buf)

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
                if length > MAX_LSP_BODY_BYTES:  # S34-f-1: wrogi/zepsuty nagłówek → nie alokuj
                    log.warning("LSP %s: Content-Length %d exceeds cap; closing reader",
                                self.name, length)
                    break
                if length > 0:
                    body = self._read_exact(out, length)
                    if len(body) < length:
                        break  # pipe zamknięty w trakcie ciała (P1-C) — zakończ czytnik
                else:
                    body = b""
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
            key = canon_key(p.get("uri", ""))  # kanoniczny klucz (Win: URI pyright ≠ nasz)
            self._diagnostics[key] = p.get("diagnostics") or []
            self._diag_seq[key] = self._diag_seq.get(key, 0) + 1
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
        return list(self._diagnostics.get(canon_key(abs_path), []))

    def wait_diagnostics(self, abs_path: str, text: str, language_id: str,
                         timeout: float = DEFAULT_DIAGNOSTICS_WAIT_S) -> list:
        """didOpen/didChange + poczekaj na NOWE publishDiagnostics (best-effort) → lista.

        Pyright (i inne serwery) często wysyła NAJPIERW pusty `publishDiagnostics` po
        didOpen, a właściwy wynik analizy DOSYŁA chwilę później. Dlatego: przerwij od razu
        gdy przyjdzie NIEPUSTA diagnostyka; jeśli pierwszy publish był pusty, poczekaj
        jeszcze krótką „łaskę" (`DIAG_EMPTY_GRACE_S`) na kolejny publish, zamiast zwracać
        pustkę na pierwszym sygnale. Czysty plik (brak błędów) zwraca pusto po łasce."""
        import time
        key = canon_key(abs_path)  # ten sam klucz, którym zapisujemy publishDiagnostics
        seq0 = self._diag_seq.get(key, 0)
        self.open_or_update(abs_path, text, language_id)
        deadline = time.monotonic() + timeout
        grace_deadline: Optional[float] = None
        while time.monotonic() < deadline:
            if self._diag_seq.get(key, 0) > seq0:
                diags = self.diagnostics_for(abs_path)
                if diags:
                    return diags  # mamy wynik — koniec
                # pierwszy publish pusty: daj serwerowi chwilę na DOSŁANIE analizy
                seq0 = self._diag_seq.get(key, 0)
                if grace_deadline is None:
                    grace_deadline = min(deadline, time.monotonic() + DIAG_EMPTY_GRACE_S)
                elif time.monotonic() >= grace_deadline:
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
