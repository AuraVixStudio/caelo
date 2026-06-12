"""Self-check klienta/menedżera MCP (M14-B1/B2) — bez sieci.

Spawnuje lokalny mock-serwer MCP (stdio, `_mcp_mock_server.py`) i weryfikuje:
1) Klient: handshake (initialize/initialized), list_tools, call_tool, czysty shutdown
   (podproces ubity — tree-kill jak run_command).
2) Menedżer: add/start/list/route/call, namespacing, klasyfikacja gate
   (readOnlyHint → READONLY; brak adnotacji → MUTATING), definicje function-calling.
3) Native remote MCP (B3): blok `tools=[{type:mcp,...}]`, maskowanie sekretów w UI.
4) Trwałość + korupcja: `caelo_mcp.json` zapisany atomowo; korupcja → backup `.corrupt`.

Kod wyjścia 0 = wszystkie asercje OK.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from caelo_core.mcp.client import McpClient, StdioTransport, flatten_tool_result  # noqa: E402
from caelo_core.mcp.manager import McpManager, _qualify  # noqa: E402

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
        cfg_path = Path(d) / "caelo_mcp.json"
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
        # S34-f-1: cap długości linii stdout zdefiniowany (bounded reader exercised powyżej
        # przez czytanie odpowiedzi mock-serwera — tu pilnujemy, że cap istnieje).
        from caelo_core.mcp.client import MAX_MCP_LINE_BYTES
        check("S34-f-1: MCP stdout line cap defined", MAX_MCP_LINE_BYTES > 0)


def test_concurrent_start() -> None:
    """S34-a: dwa równoległe start_server(sid) wołają srv.start() RAZ — bez tego oba
    wychodziły z locka i startowały ten sam serwer dwukrotnie (osierocony podproces)."""
    import threading
    import time
    with tempfile.TemporaryDirectory() as d:
        cfg_path = Path(d) / "caelo_mcp.json"
        mgr = McpManager(cfg_path)
        mgr.add_server({"id": "mock", "name": "Mock", "transport": "stdio", "command": MOCK_CMD})
        srv = mgr._servers["mock"]
        real_start = srv.start
        count = {"n": 0}
        clock = threading.Lock()

        def counting_start():
            with clock:
                count["n"] += 1
            time.sleep(0.05)  # poszerz okno wyścigu
            return real_start()

        srv.start = counting_start
        barrier = threading.Barrier(2)

        def worker():
            barrier.wait()
            mgr.start_server("mock")

        ts = [threading.Thread(target=worker) for _ in range(2)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(10)
        check("S34-a: concurrent start_server starts subprocess once", count["n"] == 1)
        check("S34-a: server ready after concurrent start", srv.is_ready())
        mgr.shutdown()


def test_remote() -> None:
    with tempfile.TemporaryDirectory() as d:
        mgr = McpManager(Path(d) / "caelo_mcp.json")
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
        cfg_path = Path(d) / "caelo_mcp.json"
        cfg_path.write_text("{ this is not valid json ", encoding="utf-8")
        mgr = McpManager(cfg_path)  # nie może rzucić
        check("corrupt config tolerated", mgr.all_status() == [])
        check("corrupt config backed up", cfg_path.with_suffix(".json.corrupt").exists())
        mgr.shutdown()


def test_interop() -> None:
    """B5 §1.2: scalanie serwerów MCP z ekosystemu (~/.claude.json + <ws>/.mcp.json).
    Importowane wchodzą WYŁĄCZONE (reżim M16); natywne i projektowe mają pierwszeństwo;
    import nie wycieka do caelo_mcp.json; sekrety (env/authorization) zamaskowane w UI."""
    import json
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        cfg_path = root / "caelo_mcp.json"
        ws_dir = root / "ws"
        ws_dir.mkdir()
        claude_json = root / ".claude.json"

        # Natywny serwer (autorytatywny) — kolizja id z globalnym importem "shared".
        cfg_path.write_text(json.dumps({"servers": [
            {"id": "shared", "name": "Native Shared", "transport": "stdio",
             "command": ["echo", "native"], "enabled": True},
        ]}), encoding="utf-8")
        # Global ~/.claude.json: stdio + remote + kolizja "shared" + kolizja "dup".
        claude_json.write_text(json.dumps({"mcpServers": {
            "global-stdio": {"command": "node", "args": ["server.js"], "env": {"SECRET": "x"}},
            "global-remote": {"type": "sse", "url": "https://example.com/mcp",
                              "authorization": "Bearer GLOBALSECRET"},
            "shared": {"command": "should-not-win"},
            "dup": {"command": "global-dup"},
        }}), encoding="utf-8")
        # Projekt <ws>/.mcp.json: projektowy serwer + kolizja "dup" (projekt wygrywa nad global).
        (ws_dir / ".mcp.json").write_text(json.dumps({"mcpServers": {
            "proj-stdio": {"command": "python", "args": ["-m", "thing"]},
            "dup": {"command": "project-dup"},
        }}), encoding="utf-8")

        mgr = McpManager(cfg_path, workspace_root=ws_dir, claude_json=claude_json)
        by_id = {s["id"]: s for s in mgr.all_status()}

        check("interop: native + global + project servers all visible",
              {"shared", "global-stdio", "global-remote", "proj-stdio", "dup"} <= set(by_id))
        check("interop: imported global stdio disabled (M16 regime)",
              by_id["global-stdio"]["enabled"] is False)
        check("interop: imported tagged with source",
              by_id["global-stdio"]["source"] == "claude-global"
              and by_id["proj-stdio"]["source"] == "claude-project")
        check("interop: native keeps precedence over global id collision",
              by_id["shared"]["source"] == "native" and by_id["shared"]["enabled"] is True
              and by_id["shared"]["command"] == ["echo", "native"])
        check("interop: project wins over global on id collision",
              by_id["dup"]["source"] == "claude-project")

        gs = mgr.public_config("global-stdio")
        check("interop: command+args mapped to argv", gs["command"] == ["node", "server.js"])
        check("interop: imported env values masked (keys only)", gs.get("env_keys") == ["SECRET"])

        gr = mgr.public_config("global-remote")
        check("interop: remote mapped (url + masked auth)",
              gr["transport"] == "remote" and gr["url"] == "https://example.com/mcp"
              and gr.get("has_authorization") is True and "authorization" not in gr)

        # _save (tu: set_enabled natywnego) NIE persistuje importowanych do caelo_mcp.json.
        mgr.set_enabled("shared", True)
        persisted = json.loads(cfg_path.read_text(encoding="utf-8"))
        persisted_ids = {s.get("id") for s in persisted.get("servers", [])}
        check("interop: import does not leak into caelo_mcp.json", persisted_ids == {"shared"})

        mgr.shutdown()

        # Brak źródeł interop (domyślne None) → tylko natywne (czyste zachowanie dla testów).
        mgr2 = McpManager(cfg_path)
        check("interop: no extra sources by default (native only)",
              {s["id"] for s in mgr2.all_status()} == {"shared"})
        mgr2.shutdown()

    # Niedestrukcyjność: uszkodzony plik ekosystemu NIE jest ruszany (nie nasz plik).
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        cfg_path = root / "caelo_mcp.json"
        bad_claude = root / ".claude.json"
        bad_claude.write_text("{ not valid json ", encoding="utf-8")
        mgr = McpManager(cfg_path, claude_json=bad_claude)  # nie może rzucić
        check("interop: corrupt external file tolerated", mgr.all_status() == [])
        check("interop: corrupt external file NOT modified (no .corrupt)",
              bad_claude.read_text(encoding="utf-8") == "{ not valid json "
              and not bad_claude.with_suffix(".json.corrupt").exists())
        mgr.shutdown()


def main() -> int:
    test_client()
    test_manager()
    test_concurrent_start()  # S34-a
    test_remote()
    test_corrupt_config()
    test_interop()

    print("\n=== MCP client/manager self-check (M14-B1/B2) ===")
    ok = True
    for name, passed in checks:
        print(f"  [{'OK' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    print(f"\n{'ALL PASSED' if ok else 'SOME FAILED'} ({sum(p for _, p in checks)}/{len(checks)})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
