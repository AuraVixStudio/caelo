"""Minimalny mock serwera MCP (stdio) dla `mcp_check.py`.

Implementuje tylko tyle JSON-RPC 2.0, ile testuje selfcheck: handshake
(initialize/initialized), tools/list, tools/call. Dwa narzędzia: `echo`
(readOnlyHint=True → READONLY) i `write_thing` (bez adnotacji → MUTATING).
Dev-only, nie pakowane.
"""

import json
import os
import sys

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
    {
        "name": "cwd",
        "description": "Return the server process working directory (for cwd tests).",
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": {"readOnlyHint": True},
    },
]


def _send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        mid = msg.get("id")
        method = msg.get("method")
        if method == "initialize":
            _send({"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "mock-mcp", "version": "0.1"},
            }})
        elif method == "notifications/initialized":
            pass  # notyfikacja — bez odpowiedzi
        elif method == "tools/list":
            _send({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            params = msg.get("params") or {}
            name = params.get("name")
            args = params.get("arguments") or {}
            if name == "echo":
                _send({"jsonrpc": "2.0", "id": mid, "result": {
                    "content": [{"type": "text", "text": "echo: " + str(args.get("text", ""))}],
                    "isError": False}})
            elif name == "write_thing":
                _send({"jsonrpc": "2.0", "id": mid, "result": {
                    "content": [{"type": "text", "text": "wrote " + str(args.get("path", ""))}],
                    "isError": False}})
            elif name == "cwd":
                _send({"jsonrpc": "2.0", "id": mid, "result": {
                    "content": [{"type": "text", "text": os.getcwd()}],
                    "isError": False}})
            else:
                _send({"jsonrpc": "2.0", "id": mid, "result": {
                    "content": [{"type": "text", "text": "unknown tool"}], "isError": True}})
        elif mid is not None:
            _send({"jsonrpc": "2.0", "id": mid,
                   "error": {"code": -32601, "message": "method not found"}})


if __name__ == "__main__":
    main()
