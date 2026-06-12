"""Klient MCP po stdio (newline-delimited JSON-RPC 2.0) — M14-B1.

Transport jest pluginowalny (`McpTransport`): tu implementujemy `StdioTransport`
(podproces serwera, czytany linia-po-linii). Korelacja żądań/odpowiedzi po `id`
żyje w `McpClient` (ponad transportem), więc dodanie transportu HTTP (B3) nie
dotyka logiki protokołu.

Wątkowość: `StdioTransport` ma własny wątek-czytnik (stdout → `on_message`) i wątek
drenujący stderr (diagnostyka). `McpClient.request()` blokuje wątek wołającego na
`threading.Event` aż przyjdzie odpowiedź z danym `id` (lub upłynie timeout). Cała
warstwa jest SYNCHRONICZNA — wołana z wątków-workerów tury czatu/agenta, jak xAI.

Hardening podprocesu (jak `tools.run_command`): scrubbed env (bez sekretów,
+ jawne env serwera z configu), tree-kill na zamknięciu. shell=False; na Windows
shimy `.cmd`/`.bat` (npx/uvx) uruchamiane przez `cmd /c` (CreateProcess nie umie
odpalić batch-a wprost).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
from collections import deque
from typing import Callable, Optional

from caelo_core.agent.tools import _tree_kill, scrubbed_env

log = logging.getLogger(__name__)

# Wersja protokołu, którą deklarujemy w handshake'u. Serwer negocjuje i może zwrócić
# inną — akceptujemy zwróconą (parser tolerancyjny, jak reszta wire-formatów tu).
PROTOCOL_VERSION = "2025-06-18"
CLIENT_NAME = "caelo-desktop"

DEFAULT_REQUEST_TIMEOUT_S = 30.0   # list/handshake — szybkie metadane
DEFAULT_CALL_TIMEOUT_S = 120.0     # tools/call — narzędzie może liczyć dłużej
START_TIMEOUT_S = 20.0             # handshake (initialize) musi zdążyć w tym oknie
STDERR_RING = 50                   # ile ostatnich linii stderr trzymać do diagnostyki
MAX_MCP_LINE_BYTES = 8 * 1024 * 1024   # S34-f-1: cap pojedynczej linii stdout (OOM)


class McpError(Exception):
    """Błąd protokołu/serwera MCP. `code` = kod JSON-RPC (gdy z odpowiedzi error)."""

    def __init__(self, message: str, code: Optional[int] = None) -> None:
        super().__init__(message)
        self.code = code


# --- transport (abstrakcja) ------------------------------------------------------

class McpTransport:
    """Kontrakt transportu: wystartuj (z callbackiem na ramki), wysyłaj, zamknij.

    `on_message(obj)` jest wołane z wątku-czytnika transportu dla każdej odebranej
    ramki JSON-RPC (dict). `send(obj)` serializuje i wypycha ramkę do serwera.
    """

    def start(self, on_message: Callable[[dict], None]) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    def send(self, message: dict) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    def is_alive(self) -> bool:  # pragma: no cover - abstract
        raise NotImplementedError


def _prepare_argv(command: list[str]) -> list[str]:
    """Rozwiń exe przez PATH i (na Windows) owiń shimy `.cmd`/`.bat` w `cmd /c`.

    CreateProcess (shell=False) nie odpala batch-y wprost, a większość serwerów MCP
    startuje przez `npx`/`uvx` (na Windows to `.cmd`). `shutil.which` znajduje realny
    plik na PATH; batch → `cmd /c <plik> <args>`. Reszta (exe) idzie bez powłoki."""
    argv = list(command)
    if not argv:
        raise McpError("empty MCP server command")
    resolved = shutil.which(argv[0]) or argv[0]
    argv[0] = resolved
    if os.name == "nt" and resolved.lower().endswith((".cmd", ".bat")):
        return ["cmd", "/c", *argv]
    return argv


class StdioTransport(McpTransport):
    """Serwer MCP jako podproces; ramki JSON-RPC po stdout/stdin (newline-delimited)."""

    def __init__(self, command: list[str], *, cwd: Optional[str] = None,
                 env: Optional[dict] = None) -> None:
        self.command = list(command)
        self.cwd = cwd
        # scrubbed env (bez naszych sekretów) + jawne env serwera z configu (np. token
        # konkretnego serwera, świadomie podany przez usera). Nasze sekrety nie wyciekają.
        self._env = {**scrubbed_env(), **(env or {})}
        self._proc: Optional[subprocess.Popen] = None
        self._reader: Optional[threading.Thread] = None
        self._stderr_thread: Optional[threading.Thread] = None
        self._stderr_ring: deque[str] = deque(maxlen=STDERR_RING)
        self._write_lock = threading.Lock()

    def start(self, on_message: Callable[[dict], None]) -> None:
        argv = _prepare_argv(self.command)
        # M19-B7: opcjonalny sandbox OS (off-by-default → no-op). Owija argv launcherem;
        # FAIL-OPEN (błąd nie blokuje startu serwera). Root = skonfigurowany cwd serwera.
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
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                **popen_kwargs,
            )
        except Exception as exc:  # noqa: BLE001
            raise McpError(f"cannot start MCP server: {exc}")

        def _dispatch(line: str) -> None:
            line = line.strip()
            if not line:
                return
            try:
                obj = json.loads(line)
            except Exception:
                # Niektóre serwery psują kontrakt i logują na stdout — pomiń nie-JSON
                # zamiast wywracać czytnik.
                log.debug("MCP non-JSON stdout line ignored: %.200s", line)
                return
            if isinstance(obj, dict):
                try:
                    on_message(obj)
                except Exception:  # noqa: BLE001
                    log.exception("MCP on_message handler failed")

        def _read_stdout() -> None:
            assert self._proc is not None and self._proc.stdout is not None
            # S34-f-1: czytnik z cap'em długości linii. `readline(limit)` wraca po \n LUB po
            # `limit` znakach — nie blokuje (jak `read(n)`) i nie alokuje w nieskończoność
            # przy zepsutym/wrogim serwerze wypisującym gigantyczny blob bez \n. Linia bez
            # \n o długości > cap = odrzuć i dociągnij do następnego \n (resync).
            stream = self._proc.stdout
            try:
                while True:
                    line = stream.readline(MAX_MCP_LINE_BYTES + 1)
                    if not line:
                        break  # EOF (stdout zamknięty / kill)
                    if len(line) > MAX_MCP_LINE_BYTES and not line.endswith("\n"):
                        log.warning("MCP stdout line exceeds cap; dropping to next newline")
                        while True:
                            tail = stream.readline(MAX_MCP_LINE_BYTES + 1)
                            if not tail or tail.endswith("\n"):
                                break
                        continue
                    _dispatch(line)
            except (ValueError, OSError):
                pass  # stdout zamknięty (kill) — oczekiwane

        def _drain_stderr() -> None:
            assert self._proc is not None and self._proc.stderr is not None
            try:
                for line in self._proc.stderr:
                    self._stderr_ring.append(line.rstrip("\n"))
            except (ValueError, OSError):
                pass

        self._reader = threading.Thread(target=_read_stdout, daemon=True)
        self._reader.start()
        self._stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
        self._stderr_thread.start()

    def send(self, message: dict) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None or proc.poll() is not None:
            raise McpError("MCP server is not running")
        line = json.dumps(message, ensure_ascii=False) + "\n"
        with self._write_lock:
            try:
                proc.stdin.write(line)
                proc.stdin.flush()
            except (ValueError, OSError) as exc:
                raise McpError(f"MCP server write failed: {exc}")

    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def stderr_tail(self) -> str:
        return "\n".join(self._stderr_ring)

    def close(self) -> None:
        proc = self._proc
        if proc is None:
            return
        # Zamknij stdin (sygnał EOF dla serwera), daj chwilę, potem tree-kill drzewa.
        try:
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.close()
        except OSError:
            pass
        try:
            proc.wait(timeout=2)
        except Exception:  # noqa: BLE001
            _tree_kill(proc)  # ubij serwer I jego potomków (jak run_command)
            try:
                proc.wait(timeout=3)
            except Exception:  # noqa: BLE001
                pass


# --- klient (warstwa protokołu) --------------------------------------------------

class _Pending:
    __slots__ = ("event", "result", "error")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.result: Optional[dict] = None
        self.error: Optional[dict] = None


class McpClient:
    """JSON-RPC ponad transportem: handshake + list_tools/resources/prompts + call_tool.

    Korelacja po `id` (licznik + słownik `_pending`). Bezpieczny wątkowo:
    `request()` wołalny z wielu wątków-workerów; czytnik transportu dostarcza
    odpowiedzi. Serwerowe żądania (sampling/roots — nie wspieramy) odbijamy błędem,
    by nie zawiesić serwera czekającego na odpowiedź."""

    def __init__(self, transport: McpTransport, *, name: str = "mcp") -> None:
        self.transport = transport
        self.name = name
        self._id = 0
        self._id_lock = threading.Lock()
        self._pending: dict[int, _Pending] = {}
        self._pending_lock = threading.Lock()
        self._closed = False
        self.server_info: dict = {}
        self.capabilities: dict = {}
        self.protocol_version: str = ""

    # --- niskopoziomowe JSON-RPC ---
    def _next_id(self) -> int:
        with self._id_lock:
            self._id += 1
            return self._id

    def _on_message(self, obj: dict) -> None:
        mid = obj.get("id")
        if "method" in obj and mid is not None:
            # Żądanie serwer→klient (np. sampling/createMessage, roots/list). Nie
            # deklarujemy tych zdolności → odpowiedz „method not found", nie wisuj.
            self._safe_send({"jsonrpc": "2.0", "id": mid,
                             "error": {"code": -32601, "method_unsupported": True,
                                       "message": "client does not support this method"}})
            return
        if "method" in obj:
            # Notyfikacja serwera (np. notifications/tools/list_changed) — zaloguj, pomiń.
            log.debug("MCP %s notification: %s", self.name, obj.get("method"))
            return
        if mid is None:
            return
        with self._pending_lock:
            slot = self._pending.get(mid)
        if slot is None:
            return  # odpowiedź na nieznane/wygasłe żądanie — pomiń
        if "error" in obj and obj["error"] is not None:
            slot.error = obj["error"]
        else:
            slot.result = obj.get("result") or {}
        slot.event.set()

    def _safe_send(self, message: dict) -> None:
        try:
            self.transport.send(message)
        except McpError:
            pass

    def request(self, method: str, params: Optional[dict] = None, *,
                timeout: float = DEFAULT_REQUEST_TIMEOUT_S) -> dict:
        if self._closed:
            raise McpError("MCP client is closed")
        mid = self._next_id()
        slot = _Pending()
        with self._pending_lock:
            self._pending[mid] = slot
        message = {"jsonrpc": "2.0", "id": mid, "method": method}
        if params is not None:
            message["params"] = params
        try:
            self.transport.send(message)
        except McpError:
            with self._pending_lock:
                self._pending.pop(mid, None)
            raise
        if not slot.event.wait(timeout=timeout):
            with self._pending_lock:
                self._pending.pop(mid, None)
            raise McpError(f"MCP request '{method}' timed out after {timeout:.0f}s")
        with self._pending_lock:
            self._pending.pop(mid, None)
        if slot.error is not None:
            msg = slot.error.get("message") if isinstance(slot.error, dict) else str(slot.error)
            code = slot.error.get("code") if isinstance(slot.error, dict) else None
            raise McpError(f"MCP error: {msg}", code=code)
        return slot.result or {}

    def notify(self, method: str, params: Optional[dict] = None) -> None:
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self._safe_send(message)

    # --- cykl życia ---
    def connect(self, *, timeout: float = START_TIMEOUT_S) -> dict:
        """Wystartuj transport i wykonaj handshake (initialize → initialized).
        Zwraca `{serverInfo, capabilities, protocolVersion}`. Rzuca McpError przy błędzie."""
        self.transport.start(self._on_message)
        result = self.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},  # nie wspieramy sampling/roots (gate'ujemy lokalnie)
            "clientInfo": {"name": CLIENT_NAME, "version": "1.0"},
        }, timeout=timeout)
        self.server_info = result.get("serverInfo") or {}
        self.capabilities = result.get("capabilities") or {}
        self.protocol_version = result.get("protocolVersion") or ""
        # Potwierdzenie gotowości — wymagane przez spec przed wywołaniami narzędzi.
        self.notify("notifications/initialized")
        return {"serverInfo": self.server_info, "capabilities": self.capabilities,
                "protocolVersion": self.protocol_version}

    def close(self) -> None:
        self._closed = True
        # Odblokuj wszystkich czekających (transport zaraz zniknie).
        with self._pending_lock:
            pending = list(self._pending.values())
            self._pending.clear()
        for slot in pending:
            if slot.error is None and slot.result is None:
                slot.error = {"message": "client closed"}
            slot.event.set()
        try:
            self.transport.close()
        except Exception:  # noqa: BLE001
            log.debug("MCP transport close failed", exc_info=True)

    def is_alive(self) -> bool:
        return not self._closed and self.transport.is_alive()

    # --- odkrywanie / wywołania ---
    def list_tools(self) -> list[dict]:
        # Guard po OBECNOŚCI klucza, nie prawdziwości — serwery deklarują `"tools": {}`
        # (pusty dict jest falsy), więc test truthiness fałszywie pomijałby narzędzia.
        if self.capabilities and "tools" not in self.capabilities:
            return []
        return _paginate(self, "tools/list", "tools")

    def list_resources(self) -> list[dict]:
        if self.capabilities and "resources" not in self.capabilities:
            return []
        try:
            return _paginate(self, "resources/list", "resources")
        except McpError:
            return []

    def list_prompts(self) -> list[dict]:
        if self.capabilities and "prompts" not in self.capabilities:
            return []
        try:
            return _paginate(self, "prompts/list", "prompts")
        except McpError:
            return []

    def call_tool(self, name: str, arguments: Optional[dict] = None, *,
                  timeout: float = DEFAULT_CALL_TIMEOUT_S) -> dict:
        """Wywołaj narzędzie. Zwraca surowy wynik `{content:[...], isError?}`."""
        return self.request("tools/call", {"name": name, "arguments": arguments or {}},
                            timeout=timeout)


def _paginate(client: McpClient, method: str, key: str, *, max_pages: int = 50) -> list[dict]:
    """Złóż listę z paginacji JSON-RPC (`nextCursor`). Twardy limit stron (anty-pętla)."""
    items: list[dict] = []
    cursor: Optional[str] = None
    for _ in range(max_pages):
        params = {"cursor": cursor} if cursor else None
        result = client.request(method, params)
        page = result.get(key)
        if isinstance(page, list):
            items.extend(x for x in page if isinstance(x, dict))
        cursor = result.get("nextCursor")
        if not cursor:
            break
    return items


def flatten_tool_result(result: dict) -> str:
    """Spłaszcz `tools/call` content[] na tekst dla modelu (M14-B2).

    Bloki tekstowe sklejone; nie-tekstowe (image/audio/resource) oznaczone
    placeholderem. `isError` poprzedza komunikat prefiksem 'Error'."""
    content = result.get("content")
    parts: list[str] = []
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                parts.append(str(block.get("text", "")))
            elif btype in ("image", "audio"):
                parts.append(f"[{btype} {block.get('mimeType', '')}]".strip())
            elif btype == "resource":
                res = block.get("resource") or {}
                parts.append(str(res.get("text") or f"[resource {res.get('uri', '')}]"))
            else:
                parts.append(f"[{btype or 'content'}]")
    elif isinstance(content, str):
        parts.append(content)
    text = "\n".join(p for p in parts if p) or "(no output)"
    # Niektóre serwery zwracają też structuredContent — dołącz zwięźle, gdy brak tekstu.
    if text == "(no output)" and result.get("structuredContent") is not None:
        try:
            text = json.dumps(result["structuredContent"], ensure_ascii=False)[:4000]
        except Exception:  # noqa: BLE001
            pass
    if result.get("isError"):
        return "Error: " + text
    return text
