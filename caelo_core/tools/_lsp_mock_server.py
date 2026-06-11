"""Mock serwer LSP (ramkowanie Content-Length) do self-checku M19-B3.

Minimalny serwer po stdio: odpowiada na initialize/definition/hover/documentSymbol/
shutdown, a na didOpen/didChange wysyła publishDiagnostics (jedna diagnostyka). Binarne
stdio (bajt-dokładne ramkowanie). Uruchamiany jako podproces przez `lsp_check.py`.
"""
import json
import sys


def _read():
    length = 0
    line = sys.stdin.buffer.readline()
    if not line:
        return None
    while line not in (b"\r\n", b"\n"):
        if b":" in line:
            k, v = line.split(b":", 1)
            if k.strip().lower() == b"content-length":
                try:
                    length = int(v.strip())
                except ValueError:
                    length = 0
        line = sys.stdin.buffer.readline()
        if not line:
            return None
    # P1-C: read(n) na pipe może zwrócić < n bajtów — doczytaj do końca ciała
    body = bytearray()
    while length and len(body) < length:
        chunk = sys.stdin.buffer.read(length - len(body))
        if not chunk:
            return None  # EOF w trakcie ciała
        body.extend(chunk)
    if not body:
        return None
    try:
        return json.loads(body.decode("utf-8"))
    except Exception:
        return None


def _send(obj):
    body = json.dumps(obj).encode("utf-8")
    sys.stdout.buffer.write(b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n\r\n" + body)
    sys.stdout.buffer.flush()


def _publish(uri):
    _send({"jsonrpc": "2.0", "method": "textDocument/publishDiagnostics", "params": {
        "uri": uri, "diagnostics": [{
            "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 3}},
            "severity": 1, "message": "mock problem", "source": "mock"}]}})


def main():
    while True:
        msg = _read()
        if msg is None:
            break
        m = msg.get("method")
        mid = msg.get("id")
        if m == "initialize":
            _send({"jsonrpc": "2.0", "id": mid, "result": {"capabilities": {}}})
        elif m in ("textDocument/didOpen", "textDocument/didChange"):
            _publish(msg["params"]["textDocument"]["uri"])
        elif m == "textDocument/definition":
            uri = msg["params"]["textDocument"]["uri"]
            _send({"jsonrpc": "2.0", "id": mid, "result": {
                "uri": uri, "range": {"start": {"line": 5, "character": 0},
                                      "end": {"line": 5, "character": 4}}}})
        elif m == "textDocument/hover":
            _send({"jsonrpc": "2.0", "id": mid, "result": {"contents": "mock hover"}})
        elif m == "textDocument/documentSymbol":
            # P1-C: `pad` rozdmuchuje ciało > bufora pipe (~64 KB) → wymusza wielokrotne
            # read() po stronie klienta; bez `_read_exact` ciało przyszłoby obcięte.
            _send({"jsonrpc": "2.0", "id": mid, "result": [{
                "name": "foo", "kind": 12, "pad": "x" * 262144,
                "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 3}},
                "selectionRange": {"start": {"line": 0, "character": 0},
                                   "end": {"line": 0, "character": 3}}}]})
        elif m == "shutdown":
            _send({"jsonrpc": "2.0", "id": mid, "result": None})
        elif m == "exit":
            break
        elif mid is not None:
            _send({"jsonrpc": "2.0", "id": mid, "result": None})


if __name__ == "__main__":
    main()
