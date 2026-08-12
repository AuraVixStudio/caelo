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
    check("client list_tools finds the tools", names == {"echo", "write_thing", "cwd"})

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
        check("manager discovered tools", status.get("tool_count") == 3)

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


def test_start_enabled() -> None:
    """Faza-G (LIVE): start_enabled() startuje serwery WŁĄCZONE i pomija wyłączone.
    Metoda byla MARTWYM kodem (nikt jej nie wolal) -> po restarcie sidecara / przebudowie
    menedzera (zmiana workspace) wlaczone serwery nie wstawaly i ich narzedzia znikaly
    (czat „nie ma" narzedzia MCP mimo Enabled). Backend.mcp wola ja teraz po (prze)budowie."""
    with tempfile.TemporaryDirectory() as d:
        mgr = McpManager(Path(d) / "caelo_mcp.json")
        mgr.add_server({"id": "on", "name": "On", "transport": "stdio",
                        "command": MOCK_CMD, "enabled": True})
        mgr.add_server({"id": "off", "name": "Off", "transport": "stdio",
                        "command": MOCK_CMD, "enabled": False})
        # add_server NIE startuje — oba „stopped" tuz po dodaniu (jak po restarcie).
        check("before start_enabled: enabled server not ready", not mgr._servers["on"].is_ready())
        mgr.start_enabled()
        check("start_enabled starts enabled stdio server", mgr._servers["on"].is_ready())
        check("start_enabled skips disabled server", not mgr._servers["off"].is_ready())
        # narzedzia wlaczonego serwera widoczne dla czatu/agenta (function defs).
        on_def_names = {d["function"]["name"] for d in mgr.tool_defs_for_responses()}
        check("start_enabled -> enabled server tools exposed",
              _qualify("on", "echo") in on_def_names)
        check("start_enabled -> disabled server tools NOT exposed",
              _qualify("off", "echo") not in on_def_names)
        mgr.shutdown()


def test_workspace_cwd_default() -> None:
    """Faza-G (LIVE): serwer stdio bez jawnego `cwd` startuje w korzeniu workspace
    (a nie w CWD sidecara), więc ścieżki względne rozwiązują się w workspace. Jawny
    `cfg['cwd']` ma pierwszeństwo. Mock-serwer zwraca własne os.getcwd() narzędziem `cwd`."""
    with tempfile.TemporaryDirectory() as ws, tempfile.TemporaryDirectory() as d:
        ws_real = os.path.realpath(ws)
        # 1) bez jawnego cwd → domyślnie korzeń workspace menedżera
        mgr = McpManager(Path(d) / "caelo_mcp.json", workspace_root=Path(ws_real))
        mgr.add_server({"id": "mock", "name": "Mock", "transport": "stdio", "command": MOCK_CMD})
        mgr.start_server("mock")
        got = os.path.realpath(mgr.call_tool(_qualify("mock", "cwd"), {}))
        check("stdio server defaults cwd to workspace root", got == ws_real)
        mgr.shutdown()

        # 2) jawny cfg['cwd'] ma pierwszeństwo nad domyślnym workspace
        with tempfile.TemporaryDirectory() as explicit:
            explicit_real = os.path.realpath(explicit)
            mgr2 = McpManager(Path(d) / "caelo_mcp.json", workspace_root=Path(ws_real))
            mgr2.add_server({"id": "m2", "name": "M2", "transport": "stdio",
                             "command": MOCK_CMD, "cwd": explicit_real})
            mgr2.start_server("m2")
            got2 = os.path.realpath(mgr2.call_tool(_qualify("m2", "cwd"), {}))
            check("explicit cfg cwd overrides workspace default", got2 == explicit_real)
            mgr2.shutdown()


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

        def counting_start(default_cwd=None):
            with clock:
                count["n"] += 1
            time.sleep(0.05)  # poszerz okno wyścigu
            return real_start(default_cwd)

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


def test_catalog() -> None:
    """Faza-G/TOP4: kurowany katalog MCP — wpisy dobrze uformowane, id unikalne/slug-safe,
    inputy spójne (token placeholder w command dla 'arg'; env_key dla 'env'), `catalog()`
    zwraca kopię, a „install" reużywa add_server z enabled=False (install != autostart)."""
    import re as _re

    from caelo_core.mcp.catalog import catalog

    entries = catalog()
    check("TOP4: catalog is non-empty", len(entries) > 0)
    ids = [e.get("id") for e in entries]
    check("TOP4: catalog ids unique + slug-safe",
          len(ids) == len(set(ids))
          and all(_re.fullmatch(r"[a-z0-9][a-z0-9-]*", i or "") for i in ids))

    ok_entries = True
    for e in entries:
        transport = e.get("transport")
        # 28c/28d: wpis to albo lokalny proces (`command`), albo lokalny serwer
        # HTTP (`url`). Poprzednia wersja tej asercji mówiła „stdio + command" —
        # co było prawdą tylko dopóki katalog miał jeden transport.
        if transport == "stdio" and not e.get("command"):
            ok_entries = False
        elif transport == "http" and not e.get("url"):
            ok_entries = False
        elif transport not in ("stdio", "http"):
            ok_entries = False
        for inp in e.get("inputs") or []:
            if inp.get("target") not in ("arg", "env", "auth"):
                ok_entries = False
            if inp.get("target") == "env" and not inp.get("env_key"):
                ok_entries = False
            # token placeholder dla 'arg' MUSI istnieć w command (renderer go podstawia)
            if inp.get("target") == "arg" and ("{" + (inp.get("key") or "") + "}") not in (e.get("command") or []):
                ok_entries = False
            # 'auth' ma sens wyłącznie tam, gdzie żądanie wysyłamy MY
            if inp.get("target") == "auth" and transport != "http":
                ok_entries = False
    check("TOP4: catalog entries well-formed (command or url, inputs consistent)", ok_entries)
    check("TOP4: catalog() returns a fresh copy", catalog() is not entries and catalog() == entries)

    # install != autostart: dodanie wpisu z enabled=False NIE startuje serwera.
    fs = next(e for e in entries if e["id"] == "filesystem")
    with tempfile.TemporaryDirectory() as d:
        mgr = McpManager(Path(d) / "caelo_mcp.json")
        cmd = ["/tmp" if t == "{path}" else t for t in fs["command"]]  # renderer podstawia {path}
        cfg = mgr.add_server({"id": fs["id"], "name": fs["name"], "transport": "stdio",
                              "command": cmd, "enabled": False})
        check("TOP4: catalog install adds server disabled (install != autostart)",
              cfg["enabled"] is False and cfg.get("status") != "ready")
        mgr.shutdown()


def test_http_transport() -> None:
    """28c: lokalny transport `http` — my wołamy serwer, nie xAI.

    Cztery rzeczy, których stdio nie ma i które dlatego mogą być zepsute tylko
    tutaj: kod odpowiedzi (202 na notyfikację), typ treści (JSON vs SSE), token
    w nagłówku i powód odmowy. Handshake i klasyfikacja bramki są sprawdzane tak
    samo jak dla stdio — bo to ma być ten sam produkt, tylko innym kanałem.
    """
    from caelo_core.mcp.client import HttpTransport, McpError
    from caelo_core.tools._mcp_mock_http_server import MockMcpHttpServer

    # --- JSON, bez tokenu ---
    server = MockMcpHttpServer()
    try:
        client = McpClient(HttpTransport(server.url), name="mock-http")
        info = client.connect()
        check("http: handshake returns serverInfo",
              info.get("serverInfo", {}).get("name") == "mock-mcp-http")
        # `notifications/initialized` poszło w handshake'u i dostało 202 bez treści;
        # gdyby transport tego nie odróżnił, connect() by tu wisiał do timeoutu.
        check("http: a notification answered with 202 does not hang", client.is_alive())
        tools = client.list_tools()
        check("http: list_tools finds the tools",
              {t.get("name") for t in tools} == {"echo", "write_thing"})
        check("http: call_tool works",
              flatten_tool_result(client.call_tool("echo", {"text": "hi"})) == "echo: hi")
        client.close()
        check("http: transport is closed after close()", not client.is_alive())
    finally:
        server.stop()

    # --- SSE: ten sam serwer, inny typ treści ---
    server = MockMcpHttpServer(sse=True)
    try:
        client = McpClient(HttpTransport(server.url), name="mock-sse")
        client.connect()
        check("http: an SSE reply is read as a JSON-RPC frame",
              flatten_tool_result(client.call_tool("echo", {"text": "sse"})) == "echo: sse")
        client.close()
    finally:
        server.stop()

    # --- token: dobry przechodzi, zły wraca z POWODEM serwera ---
    server = MockMcpHttpServer(token="s3cret")
    try:
        good = McpClient(HttpTransport(server.url, authorization="Bearer s3cret"))
        good.connect()
        check("http: a correct bearer token is accepted", len(good.list_tools()) == 2)
        good.close()

        bad = McpClient(HttpTransport(server.url, authorization="Bearer wrong"))
        detail = ""
        try:
            bad.connect()
        except McpError as exc:
            detail = str(exc)
        # Nie samo „nie wystartował": user musi widzieć, że chodzi o token, a nie
        # o zły adres albo niedziałający serwer.
        check("http: a refused token reports the server's own reason",
              "401" in detail and "token" in detail.lower())
        bad.close()
    finally:
        server.stop()

    # --- menedżer: add/start/route/gate, tak samo jak dla stdio ---
    server = MockMcpHttpServer(token="s3cret")
    try:
        with tempfile.TemporaryDirectory() as d:
            mgr = McpManager(Path(d) / "caelo_mcp.json")
            cfg = mgr.add_server({"id": "mockhttp", "name": "Mock HTTP", "transport": "http",
                                  "url": server.url, "authorization": "Bearer s3cret",
                                  "headers": {"X-Trace": "1"}})
            check("http: add_server accepts an http server", cfg["transport"] == "http")
            check("http: the token never comes back to the UI",
                  cfg.get("has_authorization") is True and "authorization" not in cfg)
            check("http: header names come back, values do not",
                  cfg.get("header_keys") == ["X-Trace"] and "headers" not in cfg)

            status = mgr.start_server("mockhttp")
            check("http: the server reaches ready", status["status"] == "ready")

            qualified = _qualify("mockhttp", "echo")
            check("http: the tool is routed under its namespaced name",
                  qualified in {t["qualified_name"] for t in mgr.list_tools()})
            # Menedżer oddaje już spłaszczony tekst (to on rozmawia z modelem).
            check("http: a call through the manager works",
                  mgr.call_tool(qualified, {"text": "via manager"}) == "echo: via manager")
            # Klasyfikacja bramki jest własnością narzędzia, nie transportu.
            check("http: readOnlyHint still means no gate", not mgr.is_mutating(qualified))
            check("http: a tool with no annotation is still gated",
                  mgr.is_mutating(_qualify("mockhttp", "write_thing")))

            # Restart po zatrzymaniu — sesja HTTP musi dać się otworzyć ponownie.
            mgr.stop_server("mockhttp")
            check("http: stop leaves the server not ready",
                  mgr.status("mockhttp")["status"] != "ready")
            check("http: it can be started again",
                  mgr.start_server("mockhttp")["status"] == "ready")
            mgr.shutdown()
    finally:
        server.stop()

    # --- odmowy, których nie wolno przyjąć do configu ---
    with tempfile.TemporaryDirectory() as d:
        mgr = McpManager(Path(d) / "caelo_mcp.json")
        refused = False
        try:
            mgr.add_server({"id": "nourl", "transport": "http"})
        except ValueError:
            refused = True
        check("http: a server with no url is refused", refused)

        refused = False
        try:
            # Token w jawnym HTTP poza pętlą zwrotną leciałby przez sieć czytelny.
            mgr.add_server({"id": "plain", "transport": "http",
                            "url": "http://example.com/mcp",
                            "authorization": "Bearer x"})
        except ValueError:
            refused = True
        check("http: a token over plain http to a public host is refused", refused)
        check("http: the same over loopback is allowed",
              mgr.add_server({"id": "loop", "transport": "http",
                              "url": "http://127.0.0.1:9/mcp",
                              "authorization": "Bearer x"})["transport"] == "http")
        mgr.shutdown()


def test_loopback_import_is_local() -> None:
    """28c: serwer z `~/.claude.json` na pętli zwrotnej to transport LOKALNY.

    Zmapowany na `remote` wyglądałby na skonfigurowany i nie mógłby zadziałać
    nigdy: native remote MCP wykonuje xAI po swojej stronie, a chmura nie widzi
    `127.0.0.1` tej maszyny.
    """
    from caelo_core.mcp.manager import _claude_server_to_cfg

    local = _claude_server_to_cfg("x", "x", {"url": "http://127.0.0.1:8772/mcp"}, "claude")
    check("interop: a loopback url is imported as http", local["transport"] == "http")
    check("interop: an imported server still arrives disabled", local["enabled"] is False)

    public = _claude_server_to_cfg("y", "y", {"url": "https://mcp.example.com/mcp"}, "claude")
    check("interop: a public url is still remote (xAI-side)", public["transport"] == "remote")


def test_sceneagent_catalog_entries() -> None:
    """28d: obie edycje SceneAgent MCP są w katalogu i różnią się transportem."""
    from caelo_core.mcp.catalog import catalog

    entries = {e["id"]: e for e in catalog()}
    pro = entries.get("sceneagent-mcp")
    plugin = entries.get("sceneagent-mcp-plugin")
    check("28d: both SceneAgent editions are in the catalogue",
          pro is not None and plugin is not None)
    if pro is None or plugin is None:
        return

    check("28d: Pro is stdio, Plugin Edition is local http",
          pro["transport"] == "stdio" and plugin["transport"] == "http")
    check("28d: the Plugin Edition points at loopback",
          (plugin.get("url") or "").startswith("http://127.0.0.1:"))
    check("28d: its token is a secret input on the auth target",
          [i for i in plugin.get("inputs") or []
           if i["target"] == "auth" and i.get("secret")] != [])

    # Wykrycie instalacji: albo mamy gotową komendę (i wtedy NIE pytamy o ścieżkę),
    # albo jej nie mamy (i wtedy pytamy). Trzeci stan — komenda z niepodstawionym
    # tokenem i bez pola do wpisania — byłby serwerem, którego nie da się wystartować.
    has_placeholder = any("{bridge}" in part for part in pro.get("command") or [])
    asks_for_path = any(i["key"] == "bridge" for i in pro.get("inputs") or [])
    check("28d: the Pro entry either resolves the bridge or asks for it, never neither",
          has_placeholder == asks_for_path)


def main() -> int:
    test_client()
    test_manager()
    test_start_enabled()  # Faza-G: auto-start włączonych serwerów (start_enabled wiring)
    test_workspace_cwd_default()  # Faza-G: domyślny cwd = workspace root
    test_concurrent_start()  # S34-a
    test_remote()
    test_corrupt_config()
    test_interop()
    test_catalog()           # Faza-G/TOP4
    test_http_transport()          # 28c: lokalny Streamable HTTP
    test_loopback_import_is_local()  # 28c: loopback z ~/.claude.json != remote
    test_sceneagent_catalog_entries()  # 28d

    print("\n=== MCP client/manager self-check (M14-B1/B2) ===")
    ok = True
    for name, passed in checks:
        print(f"  [{'OK' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    print(f"\n{'ALL PASSED' if ok else 'SOME FAILED'} ({sum(p for _, p in checks)}/{len(checks)})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
