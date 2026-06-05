"""Self-check klienta/menedżera MCP (M14-B1/B2) — bez sieci.

Spawnuje lokalny mock-serwer MCP (stdio, `_mcp_mock_server.py`) i weryfikuje:
1) Klient: handshake (initialize/initialized), list_tools, call_tool, czysty shutdown
   (podproces ubity — tree-kill jak run_command).
2) Menedżer: add/start/list/route/call, namespacing, klasyfikacja gate
   (readOnlyHint → READONLY; brak adnotacji → MUTATING), definicje function-calling.
3) Native remote MCP (B3): blok `tools=[{type:mcp,...}]`, maskowanie sekretów w UI.
4) Trwałość + korupcja: `grok_mcp.json` zapisany atomowo; korupcja → backup `.corrupt`.

Kod wyjścia 0 = wszystkie asercje OK.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from grok_core.mcp.client import McpClient, StdioTransport, flatten_tool_result  # noqa: E402
from grok_core.mcp.manager import McpManager, _qualify  # noqa: E402

MOCK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_mcp_mock_server.py")
MOCK_CMD = [sys.executable, MOCK]

checks: list[tuple[str, bool]] = []


def check(name: str, passed: bool) -> None:
    checks.append((name, bool(passed)))


def test_client() -> None:
    client = McpClient(StdioTransport(MOCK_CMD), name="mock")
    info = client.connect()
    check("client handshake returns serverInfo", info.get("serverInfo", {}).get("name") == "mock-mcp")
    check("client transport alive after connect", client.is_alive())

    tools = client.list_tools()
    names = {t.get("name") for t in tools}
    check("client list_tools finds both tools", names == {"echo", "write_thing"})

    res = client.call_tool("echo", {"text": "hi"})
    check("client call_tool echo works", flatten_tool_result(res) == "echo: hi")

    transport = client.transport
    client.close()
    time.sleep(0.2)
    check("client shutdown kills subprocess", not transport.is_alive())


def test_manager() -> None:
    with tempfile.TemporaryDirectory() as d:
        cfg_path = Path(d) / "grok_mcp.json"
        mgr = McpManager(cfg_path)
        mgr.add_server({"id": "mock", "name": "Mock", "transport": "stdio", "command": MOCK_CMD})
        check("manager add_server persists", cfg_path.is_file())

        status = mgr.start_server("mock")
        check("manager start_server ready", status.get("status") == "ready")
        check("manager discovered tools", status.get("tool_count") == 2)

        tools = mgr.list_tools()
        qnames = {t["qualified_name"] for t in tools}
        echo_q = _qualify("mock", "echo")
        write_q = _qualify("mock", "write_thing")
        check("manager namespaces tools", {echo_q, write_q} <= qnames)

        check("manager classifies readonly tool", mgr.is_mutating(echo_q) is False)
        check("manager classifies mutating tool", mgr.is_mutating(write_q) is True)
        check("manager flags mcp tool", mgr.is_mcp_tool(echo_q) and not mgr.is_mcp_tool("read_file"))

        out = mgr.call_tool(echo_q, {"text": "yo"})
        check("manager call routes to server", out == "echo: yo")

        defs = mgr.tool_defs_for_responses()
        def_names = {d["function"]["name"] for d in defs}
        check("manager builds function-call defs", {echo_q, write_q} <= def_names)
        check("manager defs carry schema",
              any(d["function"]["parameters"].get("type") == "object" for d in defs))

        desc = mgr.describe_tool(write_q)
        check("manager describe_tool resolves", desc.get("server_id") == "mock" and desc.get("name") == "write_thing")

        # Czysty stop — serwer już nie figuruje jako gotowy, narzędzia znikają z routingu.
        mgr.stop_server("mock")
        check("manager stop drops tools from routing", not mgr.is_mcp_tool(echo_q))

        # Reload z dysku — serwer w configu (zatrzymany), nie wystartowany automatycznie tu.
        mgr2 = McpManager(cfg_path)
        reloaded_ids = {s["id"] for s in mgr2.all_status()}
        check("manager reloads config", "mock" in reloaded_ids)
        mgr2.shutdown()


def test_remote() -> None:
    with tempfile.TemporaryDirectory() as d:
        mgr = McpManager(Path(d) / "grok_mcp.json")
        mgr.add_server({"id": "rmt", "name": "Remote", "transport": "remote",
                        "url": "https://example.com/mcp", "authorization": "Bearer SECRET123",
                        "server_label": "rmt"})
        blocks = mgr.remote_tool_blocks()
        check("remote produces mcp tool block", len(blocks) == 1 and blocks[0]["type"] == "mcp")
        check("remote block has url+label", blocks[0]["server_url"] == "https://example.com/mcp"
              and blocks[0]["server_label"] == "rmt")
        check("remote block carries authorization", blocks[0].get("authorization") == "Bearer SECRET123")

        pub = mgr.public_config("rmt")
        check("remote public_config masks secret",
              pub.get("has_authorization") is True and "authorization" not in pub)
        mgr.shutdown()


def test_corrupt_config() -> None:
    with tempfile.TemporaryDirectory() as d:
        cfg_path = Path(d) / "grok_mcp.json"
        cfg_path.write_text("{ this is not valid json ", encoding="utf-8")
        mgr = McpManager(cfg_path)  # nie może rzucić
        check("corrupt config tolerated", mgr.all_status() == [])
        check("corrupt config backed up", cfg_path.with_suffix(".json.corrupt").exists())
        mgr.shutdown()


def main() -> int:
    test_client()
    test_manager()
    test_remote()
    test_corrupt_config()

    print("\n=== MCP client/manager self-check (M14-B1/B2) ===")
    ok = True
    for name, passed in checks:
        print(f"  [{'OK' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    print(f"\n{'ALL PASSED' if ok else 'SOME FAILED'} ({sum(p for _, p in checks)}/{len(checks)})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
