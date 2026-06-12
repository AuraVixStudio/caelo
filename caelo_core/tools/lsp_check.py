"""Self-check integracji LSP (M19-B3) — bez prawdziwego serwera języka (mock LSP po
stdio z ramkowaniem Content-Length). Sprawdza: klient (handshake/diagnostyka/definition/
hover), menedżer (routing per rozszerzenie), URI round-trip, oraz integrację z agentem
(narzędzie `lsp` READONLY + pasywna diagnostyka po edycie) na atrapie menedżera.
Kod wyjścia 0 = wszystkie asercje OK.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from caelo_core.lsp.client import LspClient, path_to_uri, uri_to_path  # noqa: E402
from caelo_core.lsp.manager import LspManager  # noqa: E402

checks: list[tuple[str, bool]] = []
_MOCK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_lsp_mock_server.py")


def check(name: str, passed: bool) -> None:
    checks.append((name, bool(passed)))


def _mock_cmd() -> list:
    return [sys.executable, _MOCK]


def test_uri_roundtrip() -> None:
    with tempfile.TemporaryDirectory() as d:
        p = str(Path(d) / "sub" / "a.py")
        Path(p).parent.mkdir(parents=True, exist_ok=True)
        Path(p).write_text("x = 1\n", encoding="utf-8")
        uri = path_to_uri(p)
        check("uri starts with file://", uri.startswith("file://"))
        check("uri round-trips to path", os.path.normcase(uri_to_path(uri)) == os.path.normcase(str(Path(p).resolve())))


def test_client() -> None:
    with tempfile.TemporaryDirectory() as d:
        fp = str(Path(d) / "a.py")
        Path(fp).write_text("def foo():\n    return 1\n", encoding="utf-8")
        c = LspClient("mock", _mock_cmd(), cwd=d)
        started = True
        try:
            c.start()
        except Exception:
            started = False
        check("client starts + initialize handshake", started)

        diags = c.wait_diagnostics(fp, "def foo():\n    return 1\n", "python", timeout=3.0)
        check("client receives publishDiagnostics", len(diags) == 1 and diags[0]["message"] == "mock problem")

        loc = c.query("definition", fp, "x", "python", 1, 4)
        check("client definition returns Location",
              isinstance(loc, dict) and loc.get("range", {}).get("start", {}).get("line") == 5)

        hov = c.query("hover", fp, "x", "python", 0, 0)
        check("client hover returns contents", isinstance(hov, dict) and hov.get("contents") == "mock hover")

        syms = c.query("documentSymbol", fp, "x", "python", 0, 0)
        check("client documentSymbol returns list", isinstance(syms, list) and syms and syms[0]["name"] == "foo")
        # P1-C: duże ciało (256 KB `pad`) musi przyjść w całości — bez `_read_exact`
        # short-read obcina je, json.loads pada, query() timeoutuje (None/brak `pad`).
        check("P1-C: lsp reassembles large body (no short-read truncation)",
              isinstance(syms, list) and syms and len(syms[0].get("pad", "")) == 262144)
        c.stop()
        check("client stops (not alive)", not c.alive)


def test_manager() -> None:
    with tempfile.TemporaryDirectory() as d:
        fp = str(Path(d) / "a.py")
        Path(fp).write_text("y = 2\n", encoding="utf-8")
        configs = {"mockpy": {"command": sys.executable, "args": [_MOCK],
                              "extensionToLanguage": {".py": "python"}}}
        mgr = LspManager(configs, workspace_root=Path(d))
        check("manager enabled when configs present", mgr.enabled())
        check("manager disabled when empty", not LspManager({}, workspace_root=Path(d)).enabled())

        diags = mgr.diagnostics(fp, "y = 2\n", timeout=3.0)
        check("manager routes diagnostics by extension", len(diags) == 1)

        loc = mgr.query("definition", fp, "y = 2\n", 0, 0)
        check("manager routes query by extension", isinstance(loc, dict) and "range" in loc)

        listed = mgr.list_servers()
        check("manager lists server (running)", listed and listed[0]["name"] == "mockpy" and listed[0]["running"])

        # nieznane rozszerzenie → brak klienta, brak wywrotki
        check("manager: unknown ext -> no diagnostics", mgr.diagnostics(str(Path(d) / "a.xyz"), "z", timeout=0.2) == [])
        mgr.shutdown()
        check("manager shutdown clears running", not mgr.list_servers()[0]["running"])


def test_concurrent_ensure() -> None:
    """S34-b: równoległe diagnostics na pliku tego samego języka spawnują serwer RAZ —
    bez locka `_ensure` (check-then-spawn) startował dwa podprocesy, osierocając pierwszy."""
    import threading
    import time
    from caelo_core.lsp.client import LspClient
    with tempfile.TemporaryDirectory() as d:
        fp = str(Path(d) / "a.py")
        Path(fp).write_text("y = 2\n", encoding="utf-8")
        configs = {"mockpy": {"command": sys.executable, "args": [_MOCK],
                              "extensionToLanguage": {".py": "python"}}}
        mgr = LspManager(configs, workspace_root=Path(d))
        real_start = LspClient.start
        count = {"n": 0}
        clock = threading.Lock()

        def counting_start(self):
            with clock:
                count["n"] += 1
            time.sleep(0.05)  # poszerz okno wyścigu
            return real_start(self)

        LspClient.start = counting_start
        try:
            barrier = threading.Barrier(2)

            def worker():
                barrier.wait()
                mgr.diagnostics(fp, "y = 2\n", timeout=3.0)

            ts = [threading.Thread(target=worker) for _ in range(2)]
            for t in ts:
                t.start()
            for t in ts:
                t.join(10)
            check("S34-b: concurrent _ensure spawns LSP server once", count["n"] == 1)
            check("S34-b: exactly one client registered", len(mgr._clients) == 1)
        finally:
            LspClient.start = real_start
            mgr.shutdown()


def test_restart_budget_resets() -> None:
    """S34-f-3: serwer, który działał STABILNIE (>próg), po crashu dostaje wyzerowany
    budżet restartów; szybkie crashe (świeży start) nadal trafiają w cap."""
    import time
    import types
    from caelo_core.lsp.client import MAX_LSP_BODY_BYTES, STOP_EXIT_WAIT_S
    from caelo_core.lsp.manager import _STABLE_RUN_S

    configs = {"mockpy": {"command": sys.executable, "args": [_MOCK],
                          "extensionToLanguage": {".py": "python"}}}
    with tempfile.TemporaryDirectory() as d:
        mgr = LspManager(configs, workspace_root=Path(d))
        # stabilny bieg (>próg temu) + budżet wyczerpany → reset i re-spawn
        mgr._clients["mockpy"] = types.SimpleNamespace(alive=False)
        mgr._restarts["mockpy"] = 3
        mgr._started_at["mockpy"] = time.monotonic() - (_STABLE_RUN_S + 60)
        c = mgr._ensure("mockpy")
        check("S34-f-3: stable run resets restart budget (re-spawns)",
              c is not None and mgr._restarts["mockpy"] == 1)
        mgr.shutdown()
        # świeży start (crash-loop) → cap trzyma
        mgr._clients["mockpy"] = types.SimpleNamespace(alive=False)
        mgr._restarts["mockpy"] = 3
        mgr._started_at["mockpy"] = time.monotonic()
        c2 = mgr._ensure("mockpy")
        check("S34-f-3: rapid crashes still trip the cap",
              c2 is None and mgr._restarts["mockpy"] == 3)
        check("S34-f-1/f-2: LSP body cap + clean-exit window defined",
              MAX_LSP_BODY_BYTES > 0 and STOP_EXIT_WAIT_S > 0)
        mgr.shutdown()


def test_agent_lsp_tool() -> None:
    """Integracja z pętlą: narzędzie `lsp` (READONLY, bez bramki) + pasywna diagnostyka
    po edycie. Atrapa menedżera (bez podprocesu) wstrzyknięta przez lsp_provider."""
    from caelo_core.agent.session import AgentSession
    from caelo_core.agent.permissions import PermissionGate
    from caelo_core.agent.workspace import Workspace

    class FakeLsp:
        def enabled(self):
            return True

        def query(self, action, abs_path, text, line, character):
            return {"action": action, "line": line}

        def diagnostics(self, abs_path, text, timeout=1.5):
            return [{"range": {"start": {"line": 0, "character": 0}}, "severity": 1,
                     "message": "fake problem", "source": "fake"}]

    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        (ws.root / "a.py").write_text("x = 1\n", encoding="utf-8")
        gate = PermissionGate()
        events: list = []
        calls = {"n": 0}

        def llm(api_key, base_url, messages, model, temperature, tools, on_text=None, stop_flag=None):
            calls["n"] += 1
            if calls["n"] == 1:  # wywołaj narzędzie lsp (READONLY)
                return {"role": "assistant", "content": None, "tool_calls": [{
                    "id": "l1", "type": "function", "function": {
                        "name": "lsp",
                        "arguments": json.dumps({"action": "definition", "path": "a.py",
                                                 "line": 0, "character": 0})}}]}
            if calls["n"] == 2:  # edytuj plik → pasywna diagnostyka
                return {"role": "assistant", "content": None, "tool_calls": [{
                    "id": "w1", "type": "function", "function": {
                        "name": "write_file",
                        "arguments": json.dumps({"path": "a.py", "content": "x = 2\n"})}}]}
            return {"role": "assistant", "content": "done"}

        sess = AgentSession(ws, gate, llm, lambda: "k", "http://unused",
                            emit=events.append, request_approval=lambda *a: "accept",
                            lsp_provider=lambda: FakeLsp())
        # advertised tools muszą zawierać `lsp` (enabled)
        names = [t["function"]["name"] for t in sess._all_tools()]
        check("lsp tool advertised when enabled", "lsp" in names)

        sess.run_turn("use lsp then edit", model="mock", mode="bypass")
        approvals = [e for e in events if e.get("type") == "approval_request"]
        lsp_res = [e for e in events if e.get("type") == "tool_result" and e.get("id") == "l1"]
        diag = [e for e in events if e.get("type") == "diagnostics"]
        check("lsp tool runs READONLY (no approval)", not any(a.get("name") == "lsp" for a in approvals)
              and bool(lsp_res) and lsp_res[0]["ok"])
        check("passive diagnostics frame emitted after edit",
              bool(diag) and diag[0]["path"].endswith("a.py") and diag[0]["items"][0]["message"] == "fake problem")

    # narzędzie ukryte, gdy LSP niedostępne
    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        sess = AgentSession(ws, PermissionGate(), lambda *a, **k: {"role": "assistant", "content": "x"},
                            lambda: "k", "http://unused", emit=lambda e: None,
                            request_approval=lambda *a: "reject")
        names = [t["function"]["name"] for t in sess._all_tools()]
        check("lsp tool hidden when no provider", "lsp" not in names)


def main() -> int:
    test_uri_roundtrip()
    test_client()
    test_manager()
    test_concurrent_ensure()  # S34-b
    test_restart_budget_resets()  # S34-f-3 (+ S34-f-1/f-2 caps)
    test_agent_lsp_tool()
    ok = True
    for name, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    print("RESULT:", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
