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
from urllib.parse import urlparse

import requests

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
HTTP_CONNECT_TIMEOUT_S = 5.0       # nawiązanie połączenia; lokalnie to milisekundy

#: Hosty, dla których `http://` nie opuszcza maszyny (patrz `HttpTransport`).
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


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

    def send(self, message: dict, *,
             timeout: Optional[float] = None) -> None:  # pragma: no cover - abstract
        """`timeout` to budżet wołającego na TĘ ramkę, w sekundach (None = domyślny).

        Dla stdio jest bez znaczenia (zapis do rury) i jest ignorowany. Dla HTTP
        to jedyne miejsce, gdzie da się go egzekwować: odpowiedź przychodzi w tym
        samym żądaniu, więc `McpClient.request` czeka na `Event` już PO powrocie
        z `send()`. Bez przekazania budżetu `request(timeout=...)` znaczyłby co
        innego na każdym transporcie."""
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

    def send(self, message: dict, *, timeout: Optional[float] = None) -> None:
        del timeout  # zapis do rury — budżet egzekwuje `request()` na Evencie
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


class HttpTransport(McpTransport):
    """Serwer MCP po LOKALNYM HTTP (Streamable HTTP) — my go wołamy, nie xAI.

    Różnica wobec transportu `remote` jest zasadnicza i widać ją w UI: `remote`
    to native remote MCP, które wykonuje **xAI** po swojej stronie (brak bramki
    lokalnej, dane lecą do xAI), więc adres pętli zwrotnej jest tam bezużyteczny
    — chmura nie zobaczy `127.0.0.1`. Tutaj żądanie wychodzi z tej maszyny, więc
    lokalny serwer MCP na loopbacku jest osiągalny, a narzędzia przechodzą przez
    tę samą bramkę uprawnień co stdio.

    Model żądanie-odpowiedź, nie strumień: POST niesie jedną ramkę JSON-RPC, a
    odpowiedź wraca w TYM SAMYM żądaniu — jako `application/json` albo jako
    `text/event-stream` (spec dopuszcza oba; serwer wybiera). Notyfikacja dostaje
    `202` bez treści. Dlatego `send()` sam woła `on_message` dla tego, co
    przyszło: `McpClient.request()` rejestruje slot PRZED wysłaniem, więc zdąży.

    Strumienia serwer→klient (GET na endpoint) NIE otwieramy. Jest w spec
    opcjonalny, służy notyfikacjom, których i tak nie konsumujemy, a serwer,
    który go nie ma, odpowiada `405` — trzymanie wątku na takim żądaniu byłoby
    kosztem bez pożytku.

    Wątkowość: `requests.Session` puli połączenia i pula urllib3 jest
    bezpieczna wątkowo; nie mutujemy `session.headers` po starcie, a jedyny stan
    dzielony — identyfikator sesji MCP — chodzi pod lockiem.
    """

    #: Spec wymaga obu typów w Accept: serwer wybiera, czym odpowie.
    ACCEPT = "application/json, text/event-stream"

    def __init__(self, url: str, *, authorization: Optional[str] = None,
                 headers: Optional[dict] = None) -> None:
        self.url = (url or "").strip()
        if not self.url:
            raise McpError("empty MCP server URL")
        parsed = urlparse(self.url)
        if parsed.scheme not in ("http", "https"):
            raise McpError(f"unsupported MCP URL scheme: {parsed.scheme or '(none)'}")
        # Token w jawnym HTTP poza pętlą zwrotną leci przez sieć czytelny dla
        # każdego po drodze. Loopback nie opuszcza maszyny, więc tam `http` jest
        # w porządku — i to jest przypadek, dla którego ten transport powstał.
        if (authorization and parsed.scheme == "http"
                and (parsed.hostname or "") not in LOOPBACK_HOSTS):
            raise McpError(
                "refusing to send an authorization header over plain http to "
                f"{parsed.hostname or 'a remote host'}; use https")
        self._authorization = authorization or None
        self._extra_headers = {str(k): str(v) for k, v in (headers or {}).items()}
        self._session: Optional[requests.Session] = None
        self._session_id: Optional[str] = None
        self._lock = threading.Lock()
        self._on_message: Optional[Callable[[dict], None]] = None
        self._closed = False

    # --- kontrakt transportu ---
    def start(self, on_message: Callable[[dict], None]) -> None:
        self._on_message = on_message
        self._closed = False
        self._session = requests.Session()

    def send(self, message: dict, *, timeout: Optional[float] = None) -> None:
        session = self._session
        if session is None or self._closed:
            raise McpError("MCP server is not running")
        budget = timeout if (timeout and timeout > 0) else DEFAULT_CALL_TIMEOUT_S
        try:
            response = session.post(
                self.url,
                data=json.dumps(message, ensure_ascii=False).encode("utf-8"),
                headers=self._headers(),
                timeout=(HTTP_CONNECT_TIMEOUT_S, budget),
                stream=True,   # SSE musi być czytane strumieniowo
            )
        except requests.RequestException as exc:
            raise McpError(f"MCP HTTP request failed: {exc}")

        with self._lock:
            sid = response.headers.get("Mcp-Session-Id")
            if sid:
                self._session_id = sid

        try:
            self._dispatch_response(response)
        finally:
            response.close()

    def is_alive(self) -> bool:
        # Nie ma procesu do sprawdzenia i nie zgadujemy: „żywy" znaczy tu „nie
        # zamknięty". Padnięty endpoint ujawnia się błędem najbliższego żądania,
        # a nie zmyślonym statusem między nimi.
        return not self._closed and self._session is not None

    def close(self) -> None:
        self._closed = True
        session, self._session = self._session, None
        if session is None:
            return
        # Uprzejme zakończenie sesji (spec: DELETE). Serwer bezstanowy odpowie
        # 200 albo 405 — jedno i drugie jest w porządku, więc błąd pomijamy.
        try:
            if self._session_id:
                session.delete(self.url, headers=self._headers(),
                               timeout=(HTTP_CONNECT_TIMEOUT_S, 5))
        except requests.RequestException:
            log.debug("MCP HTTP session delete failed", exc_info=True)
        try:
            session.close()
        except Exception:  # noqa: BLE001
            pass

    def stderr_tail(self) -> str:
        return ""  # brak podprocesu — nie ma czego zbierać

    # --- środek ---
    def _headers(self) -> dict:
        headers = {
            "Content-Type": "application/json",
            "Accept": self.ACCEPT,
            # Deklarujemy tę wersję w handshake'u; spec 2025-06-18 chce jej też
            # w nagłówku kolejnych żądań.
            "MCP-Protocol-Version": PROTOCOL_VERSION,
            **self._extra_headers,
        }
        if self._authorization:
            headers["Authorization"] = self._authorization
        with self._lock:
            if self._session_id:
                headers["Mcp-Session-Id"] = self._session_id
        return headers

    def _dispatch_response(self, response: requests.Response) -> None:
        if response.status_code in (202, 204):
            return  # notyfikacja/odpowiedź przyjęta, nic nie wraca
        if response.status_code >= 400:
            raise McpError(_http_error_detail(response), code=response.status_code)

        kind = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if kind == "text/event-stream":
            self._dispatch_sse(response)
            return

        # `requests` zgaduje ISO-8859-1 przy braku charset, co psuje nie-ASCII
        # (konwencja projektu). Dekodujemy jawnie z bajtów.
        body = response.content
        if not body.strip():
            return
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise McpError(f"MCP HTTP reply is not JSON: {exc}")
        self._deliver(payload)

    def _dispatch_sse(self, response: requests.Response) -> None:
        """Zdarzenia SSE → ramki JSON-RPC. Pola `data:` łączy się nowymi liniami."""
        data: list[str] = []
        total = 0
        for raw in response.iter_lines(decode_unicode=False):
            if raw is None:
                continue
            line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
            if not line:                       # pusta linia = koniec zdarzenia
                if data:
                    self._deliver_text("\n".join(data))
                    data = []
                    total = 0
                continue
            if line.startswith(":"):
                continue                       # komentarz/keep-alive
            if not line.startswith("data:"):
                continue                       # `event:`/`id:` — nieistotne dla MCP
            chunk = line[5:].lstrip()
            total += len(chunk)
            if total > MAX_MCP_LINE_BYTES:
                raise McpError("MCP SSE event exceeds the size cap")
            data.append(chunk)
        if data:                               # strumień zamknięty bez pustej linii
            self._deliver_text("\n".join(data))

    def _deliver_text(self, text: str) -> None:
        try:
            payload = json.loads(text)
        except ValueError:
            log.debug("MCP SSE non-JSON data ignored: %.200s", text)
            return
        self._deliver(payload)

    def _deliver(self, payload: object) -> None:
        handler = self._on_message
        if handler is None:
            return
        # Batch wyszedł ze spec w 2025-06-18, ale serwer sprzed tej wersji nadal
        # może odpowiedzieć tablicą — przyjmujemy oba kształty.
        frames = payload if isinstance(payload, list) else [payload]
        for frame in frames:
            if not isinstance(frame, dict):
                continue
            try:
                handler(frame)
            except Exception:  # noqa: BLE001
                log.exception("MCP on_message handler failed")


def _http_error_detail(response: requests.Response) -> str:
    """Powód odmowy tak, jak podał go serwer — bez tego 401 jest nie do odróżnienia
    od 404 z perspektywy usera patrzącego na „nie wystartował"."""
    detail = ""
    try:
        body = response.content[:500].decode("utf-8", "replace").strip()
    except Exception:  # noqa: BLE001
        body = ""
    if body:
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict):
                detail = str(parsed.get("error") or parsed.get("message") or "")
        except ValueError:
            detail = body
    if not detail:
        detail = response.reason or ""
    return f"MCP HTTP {response.status_code}{': ' + detail if detail else ''}"


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
            # Budżet wędruje do transportu: po HTTP odpowiedź przychodzi w tym
            # samym żądaniu, więc gdyby `send()` go nie znało, `request(timeout=)`
            # ograniczałby tylko czekanie PO powrocie — czyli nic.
            self.transport.send(message, timeout=timeout)
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
