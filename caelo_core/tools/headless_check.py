"""Self-check trybu headless (M19-B1) — bez sieci xAI (mock LLM) i bez I/O Backendu
(stub backend na temp workspace; `headless._run` wstrzykiwany backend).

Sprawdza: formaty wyjścia (plain/json/streaming-json + delty), zawężanie narzędzi
(--tools/--disallowed-tools, blokada delegacji), fail-closed (mutacja bez zgody odrzucona),
bypass (mutacja wykonana), reguły --allow (B4), oraz minimalną persystencję sesji (-s/-c/-r).
Kod wyjścia 0 = wszystkie asercje OK.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import config  # type: ignore  # noqa: E402
from caelo_core import headless as H  # noqa: E402
from caelo_core.agent import llm as LLM  # noqa: E402
from caelo_core.agent.permissions import PermissionGate  # noqa: E402
from caelo_core.agent.workspace import Workspace  # noqa: E402

checks: list[tuple[str, bool]] = []


def check(name: str, passed: bool) -> None:
    checks.append((name, bool(passed)))


class StubBackend:
    """Minimalny backend dla AgentRunner (bez I/O / sieci) — to, czego dotyka prosta tura."""

    def __init__(self) -> None:
        self.permissions = PermissionGate(None)
        self.mcp = self.hooks = self.skills = None
        self._ws = None
        self.recorded: list = []

    def set_workspace(self, p):
        self._ws = Workspace(p)
        return self._ws

    def get_workspace(self):
        return self._ws

    def get_api_key(self):
        return "k"

    def get_checkpoints(self):
        return None

    def read_settings(self):
        return {}

    def record_event(self, **kw):
        self.recorded.append(kw)


def _mock_text(content: str):
    """LLM bez narzędzi: emuluje kumulację treści (on_text dostaje pełny tekst narastająco)."""
    def fn(api_key, base_url, messages, model, temperature, tools, on_text=None, stop_flag=None):
        if on_text:
            on_text(content[: max(1, len(content) // 2)])
            on_text(content)
        return {"role": "assistant", "content": content}
    return fn


def _mock_one_tool(name: str, args: dict):
    """LLM: pierwsza tura = jedno wywołanie narzędzia, druga = koniec."""
    calls = {"n": 0}

    def fn(api_key, base_url, messages, model, temperature, tools, on_text=None, stop_flag=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"role": "assistant", "content": None, "tool_calls": [
                {"id": "c1", "type": "function",
                 "function": {"name": name, "arguments": json.dumps(args)}}]}
        return {"role": "assistant", "content": "done"}
    return fn


def _mock_capture(seen: dict):
    """LLM bez narzędzi, ale przechwytuje przekazany reasoning_effort (M19-B9).
    `**kw` ⇒ działa też, gdy session NIE przekazuje kwargu (brak effortu)."""
    def fn(api_key, base_url, messages, model, temperature, tools,
           on_text=None, stop_flag=None, **kw):
        seen["effort"] = kw.get("reasoning_effort", "MISSING")
        return {"role": "assistant", "content": "ok"}
    return fn


def _run(argv: list, mock, backend=None):
    """Uruchom headless._run z podmienionym LLM; zwróć (rc, stdout, backend)."""
    orig = LLM.stream_chat_with_tools
    LLM.stream_chat_with_tools = mock  # AgentRunner importuje leniwie → łapie podmianę
    try:
        opts = H._build_parser().parse_args(argv)
        b = backend or StubBackend()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = H._run(opts, b)
        return rc, buf.getvalue(), b
    finally:
        LLM.stream_chat_with_tools = orig


def test_formats() -> None:
    with tempfile.TemporaryDirectory() as d:
        rc, out, _ = _run(["-p", "hi", "--cwd", d, "--output-format", "plain"], _mock_text("Hello world"))
        check("plain: prints final text", out.strip() == "Hello world" and rc == 0)

        rc, out, _ = _run(["-p", "hi", "--cwd", d, "--output-format", "json"], _mock_text("Hello world"))
        obj = json.loads(out.strip())
        check("json: text/stopReason/sessionId",
              obj["text"] == "Hello world" and obj["stopReason"] == "EndTurn" and bool(obj["sessionId"]))

        rc, out, _ = _run(["-p", "hi", "--cwd", d, "--output-format", "streaming-json"], _mock_text("Hello world"))
        lines = [json.loads(line) for line in out.splitlines() if line.strip()]
        texts = "".join(e["data"] for e in lines if e.get("type") == "text")
        end = [e for e in lines if e.get("type") == "end"]
        check("streaming-json: deltas reconstruct text", texts == "Hello world")
        check("streaming-json: end event", bool(end) and end[0]["stopReason"] == "EndTurn")


def test_permission_and_tools() -> None:
    write = lambda: _mock_one_tool("write_file", {"path": "a.txt", "content": "hi"})  # noqa: E731

    with tempfile.TemporaryDirectory() as d:
        _run(["-p", "x", "--cwd", d, "--output-format", "json"], write())
        check("fail-closed: ask mode rejects write (no file)", not (Path(d) / "a.txt").exists())

    with tempfile.TemporaryDirectory() as d:
        _run(["-p", "x", "--cwd", d, "--always-approve", "--output-format", "json"], write())
        check("bypass: write applied", (Path(d) / "a.txt").read_text(encoding="utf-8") == "hi")

    with tempfile.TemporaryDirectory() as d:
        _run(["-p", "x", "--cwd", d, "--always-approve", "--tools", "read_file",
              "--output-format", "json"], write())
        check("--tools allowlist blocks unlisted write", not (Path(d) / "a.txt").exists())

    with tempfile.TemporaryDirectory() as d:
        _run(["-p", "x", "--cwd", d, "--always-approve", "--disallowed-tools", "write_file",
              "--output-format", "json"], write())
        check("--disallowed-tools blocks write", not (Path(d) / "a.txt").exists())

    with tempfile.TemporaryDirectory() as d:
        _run(["-p", "x", "--cwd", d, "--allow", "Write(**)", "--output-format", "json"], write())
        check("--allow rule auto-accepts write (ask mode)",
              (Path(d) / "a.txt").read_text(encoding="utf-8") == "hi")


def test_resolve_tools() -> None:
    check("tools: allowlist narrows", H._resolve_tools("read_file,grep", None)[0] == {"read_file", "grep"})
    check("tools: none = all (None)", H._resolve_tools(None, None) == (None, True))
    check("tools: disallow removes one", H._resolve_tools(None, "write_file")[0] == H._FILE_TOOLS - {"write_file"})
    check("tools: Agent blocks delegate", H._resolve_tools(None, "Agent")[1] is False)
    check("tools: Agent(role) blocks delegate", H._resolve_tools(None, "Agent(researcher)")[1] is False)


def test_sessions() -> None:
    with tempfile.TemporaryDirectory() as data, tempfile.TemporaryDirectory() as wsd:
        orig = config.DATA_DIR
        config.DATA_DIR = Path(data)  # _sessions_dir() czyta DATA_DIR live
        try:
            rc, out, _ = _run(["-p", "hello", "--cwd", wsd, "-s", "s1", "--output-format", "json"], _mock_text("ok"))
            obj = json.loads(out.strip())
            check("session: sessionId echoes -s", obj["sessionId"] == "s1")
            h1 = H._load_session("s1")
            check("session: persisted history (user+assistant)",
                  len(h1) == 2 and h1[0]["role"] == "user")

            _run(["-p", "again", "--cwd", wsd, "-s", "s1", "--output-format", "json"], _mock_text("ok2"))
            check("session: resume appends (history grew)", len(H._load_session("s1")) == 4)
            check("session: -c finds latest", H._latest_session() == "s1")

            rc, _, _ = _run(["-p", "x", "--cwd", wsd, "-r", "nope", "--output-format", "json"], _mock_text("ok"))
            check("session: -r missing -> rc 2", rc == 2)
        finally:
            config.DATA_DIR = orig


def test_effort() -> None:
    """M19-B9: --effort dociera do llm_fn; bez flagi/ustawienia → brak kwargu (no regression)."""
    with tempfile.TemporaryDirectory() as d:
        seen: dict = {}
        _run(["-p", "hi", "--cwd", d, "--effort", "high", "--output-format", "json"],
             _mock_capture(seen))
        check("effort: --effort high reaches llm_fn", seen.get("effort") == "high")

        seen.clear()
        _run(["-p", "hi", "--cwd", d, "--output-format", "json"], _mock_capture(seen))
        check("effort: no --effort -> no reasoning_effort kwarg (no regression)",
              seen.get("effort") == "MISSING")


def test_export() -> None:
    """M19-B10: --export-md zapisuje historię sesji do Markdown (czysta ścieżka, bez backendu)."""
    with tempfile.TemporaryDirectory() as data, tempfile.TemporaryDirectory() as wsd:
        orig = config.DATA_DIR
        config.DATA_DIR = Path(data)  # _sessions_dir() / _session_path czytają DATA_DIR live
        try:
            # utwórz sesję (jedna tura) → historia user + assistant
            _run(["-p", "hello there", "--cwd", wsd, "-s", "exp1", "--output-format", "json"],
                 _mock_text("Hi! Done."))
            out_md = Path(data) / "out.md"
            opts = H._build_parser().parse_args(["--export-md", str(out_md), "-s", "exp1"])
            rc = H._export_session(opts)
            md = out_md.read_text(encoding="utf-8") if out_md.exists() else ""
            check("export: rc 0 + file written", rc == 0 and out_md.exists())
            check("export: md has user + assistant content",
                  "## User" in md and "hello there" in md
                  and "## Assistant" in md and "Hi! Done." in md)

            opts2 = H._build_parser().parse_args(["--export-md", str(out_md), "-s", "nope"])
            check("export: missing session -> rc 2", H._export_session(opts2) == 2)

            # pure serializer: tool-call + tool result obecne
            md2 = H.history_to_markdown([
                {"role": "user", "content": "do it"},
                {"role": "assistant", "content": "", "tool_calls": [
                    {"function": {"name": "read_file", "arguments": "{}"}}]},
                {"role": "tool", "content": "file contents here"},
            ])
            check("export: history_to_markdown renders tool calls + results",
                  "read_file" in md2 and "Tool result" in md2 and "file contents here" in md2)
        finally:
            config.DATA_DIR = orig


def test_worktree_flag() -> None:
    """M19-B12: --worktree włącza config.AGENT_GIT_WORKTREE dla biegu (parytet --sandbox)."""
    with tempfile.TemporaryDirectory() as d:
        prev = config.AGENT_GIT_WORKTREE
        config.AGENT_GIT_WORKTREE = False
        try:
            _run(["-p", "hi", "--cwd", d, "--worktree", "--output-format", "json"], _mock_text("ok"))
            check("worktree: --worktree enables git worktree for the run",
                  config.AGENT_GIT_WORKTREE is True)
        finally:
            config.AGENT_GIT_WORKTREE = prev


def test_project_root_flag() -> None:
    """M19-B14: --project-root ustawia workspace na korzeń repo (najbliższy .git w górę)."""
    with tempfile.TemporaryDirectory() as d:
        repo = Path(d) / "r"
        sub = repo / "a" / "b"
        sub.mkdir(parents=True)
        (repo / ".git").mkdir()
        b = StubBackend()
        _run(["-p", "hi", "--cwd", str(sub), "--project-root", "--output-format", "json"],
             _mock_text("ok"), backend=b)
        ws = b.get_workspace()
        check("B14: --project-root sets workspace to git root",
              ws is not None and Path(ws.root).resolve() == repo.resolve())

        # bez flagi: workspace = --cwd (bez regresji)
        b2 = StubBackend()
        _run(["-p", "hi", "--cwd", str(sub), "--output-format", "json"],
             _mock_text("ok"), backend=b2)
        ws2 = b2.get_workspace()
        check("B14: without --project-root workspace stays at --cwd",
              ws2 is not None and Path(ws2.root).resolve() == sub.resolve())


def main() -> int:
    test_formats()
    test_permission_and_tools()
    test_resolve_tools()
    test_sessions()
    test_effort()
    test_export()
    test_worktree_flag()
    test_project_root_flag()
    ok = True
    for name, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    print("RESULT:", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
