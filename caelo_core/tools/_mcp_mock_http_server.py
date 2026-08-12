"""Minimalny mock serwera MCP po HTTP (Streamable HTTP) dla `mcp_check.py`.

Odpowiednik `_mcp_mock_server.py`, ale po HTTP — bo transport `http` różni się od
stdio dokładnie w tych miejscach, których stdio nie ma: kod odpowiedzi, typ treści
i nagłówki. Serwuje te same narzędzia (`echo` readOnlyHint=True, `write_thing` bez
adnotacji), więc klasyfikację bramki testuje się identycznie na obu transportach.

Trzy rzeczy są tu celowe, bo każda odpowiada gałęzi w `HttpTransport`:

* **`Content-Type` wybiera serwer, nie klient.** Spec dopuszcza `application/json`
  ALBO `text/event-stream` na to samo żądanie, więc mock potrafi jedno i drugie
  (`sse=True`). Bez tego gałąź SSE byłaby kodem, którego nic nie uruchamia.
* **Notyfikacja dostaje `202` bez treści** — klient nie może na nią czekać.
* **Zły token dostaje `401` z powodem w treści**, żeby sprawdzić, że powód
  serwera dociera do usera zamiast gołego „nie wystartował".

Wątek, nie podproces: nic tu nie trzeba izolować, a test ma być szybki.
Dev-only, nie pakowane.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

TOOLS = [
    {
        "name": "echo",
        "description": "Echo back the given text.",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "write_thing",
        "description": "Pretend to write a file (mutating).",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
]

ENDPOINT_PATH = "/mcp"
SESSION_ID = "mock-session-1"


def _result(mid, payload: dict) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "result": payload}


def _handle(message: dict) -> Optional[dict]:
    """Ramka wejściowa → ramka odpowiedzi, albo None dla notyfikacji."""
    method = message.get("method")
    mid = message.get("id")
    if method == "initialize":
        return _result(mid, {
            "protocolVersion": message.get("params", {}).get("protocolVersion", "2025-06-18"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "mock-mcp-http", "version": "1.0"},
        })
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return _result(mid, {"tools": TOOLS})
    if method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        if name == "echo":
            return _result(mid, {"content": [{"type": "text",
                                              "text": "echo: " + str(args.get("text", ""))}],
                                 "isError": False})
        if name == "write_thing":
            return _result(mid, {"content": [{"type": "text",
                                              "text": "wrote " + str(args.get("path", ""))}],
                                 "isError": False})
        return _result(mid, {"content": [{"type": "text", "text": "unknown tool"}],
                             "isError": True})
    if mid is not None:
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": -32601, "message": "method not found"}}
    return None


class MockMcpHttpServer:
    """Serwer w wątku. `url` wskazuje endpoint; `stop()` go zamyka."""

    def __init__(self, *, token: Optional[str] = None, sse: bool = False) -> None:
        self.token = token
        self.sse = sse
        self.requests = 0
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args) -> None:  # cisza w wyjściu selfchecku
                pass

            def _send(self, code: int, body: bytes = b"",
                      content_type: str = "application/json") -> None:
                self.send_response(code)
                if body:
                    self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Mcp-Session-Id", SESSION_ID)
                self.end_headers()
                if body:
                    self.wfile.write(body)

            def do_DELETE(self) -> None:  # noqa: N802 - nazwa wymagana przez BaseHTTPRequestHandler
                self._send(200)

            def do_POST(self) -> None:  # noqa: N802
                outer.requests += 1
                if self.path != ENDPOINT_PATH:
                    self._send(404, b'{"error":"unknown endpoint"}')
                    return
                if outer.token and self.headers.get("Authorization") != f"Bearer {outer.token}":
                    self._send(401, b'{"error":"a valid Bearer token is required"}')
                    return
                length = int(self.headers.get("Content-Length") or 0)
                try:
                    message = json.loads(self.rfile.read(length).decode("utf-8"))
                except ValueError:
                    self._send(400, b'{"error":"not JSON"}')
                    return
                reply = _handle(message)
                if reply is None:
                    self._send(202)   # notyfikacja przyjęta, nic nie wraca
                    return
                payload = json.dumps(reply, ensure_ascii=False)
                if outer.sse:
                    body = f"event: message\ndata: {payload}\n\n".encode("utf-8")
                    self._send(200, body, "text/event-stream")
                else:
                    self._send(200, payload.encode("utf-8"), "application/json")

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}{ENDPOINT_PATH}"

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
