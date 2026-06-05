"""Self-check silnika agenta (Faza 4) — bez sieci xAI.

1) Narzędzia plikowe na tymczasowym workspace (read/write/edit/list/glob/grep/run_command).
2) Sandbox: odrzucenie ucieczki poza workspace.
3) Pętla AgentSession z MOCKIEM modelu: scenariusz write_file -> done,
   z bramką zatwierdzania (auto-accept) i zbieraniem zdarzeń.
4) Bezpieczeństwo run_command (P0-1): łańcuchowanie nie obchodzi allowlisty,
   metaznaki powłoki odrzucane przed uruchomieniem.
5) Sandbox glob (P0-2): wzorce `..`/absolutne nie enumerują plików poza workspace.
6) Limity grep (P0-3): timeout ReDoS, pomijanie plików dużych i binarnych.
7) Stop run_command (P0-4): Stop przerywa komendę i jej drzewo procesów.
8) Spójność historii (P0-5): każdy tool_call ma odpowiedź tool (też przy Stop).
9) Scrub środowiska (P0-6): run_command nie ujawnia sekretów (token/API key).
10) Atomowość i symlinki (P0-7): zapisy atomowe, enumeratory nie wychodzą poza root.
11) Skaner metaznaków na POSIX (P0-10): model `sh` zamyka dziurę parzystości `\"`.
12) Most WS (P0-9/P2-12): WsStream ma ograniczoną kolejkę i dołącza workera.
Kod wyjścia 0 = wszystkie asercje OK.
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from grok_core.agent import tools as T  # noqa: E402
from grok_core.agent.permissions import PermissionGate, command_metachars  # noqa: E402
from grok_core.agent.session import AgentSession  # noqa: E402
from grok_core.agent.workspace import Workspace, WorkspaceError  # noqa: E402

checks: list[tuple[str, bool]] = []


def check(name: str, passed: bool) -> None:
    checks.append((name, bool(passed)))


def test_tools() -> None:
    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)

        check("write_file creates file", "Wrote" in T.write_file(ws, "src/a.py", "print('hi')\nx = 1\n"))
        check("read_file returns numbered", T.read_file(ws, "src/a.py").startswith("1\t"))
        check("list_dir shows dir", "src/" in T.list_dir(ws, "."))
        check("glob finds py", "src/a.py" in T.glob(ws, "**/*.py"))
        check("grep finds match", "src/a.py:1:" in T.grep(ws, r"print"))

        edit_ok = T.edit_file(ws, "src/a.py", "x = 1", "x = 2")
        check("edit_file unique replace", "Edited" in edit_ok)
        check("edit applied", "x = 2" in (ws.root / "src/a.py").read_text(encoding="utf-8"))

        nf = T.edit_file(ws, "src/a.py", "NOPE", "z")
        check("edit_file missing -> error", nf.startswith("Error"))

        cmd = "echo hello-agent" if os.name == "nt" else "echo hello-agent"
        out = T.run_command(ws, cmd)
        check("run_command runs", "hello-agent" in out and "exit 0" in out)

        prev = T.preview_change(ws, "edit_file", {"path": "src/a.py", "old_string": "x = 2", "new_string": "x = 3"})
        check("preview diff produced", bool(prev) and prev.get("kind") == "diff" and "x = 3" in prev.get("diff", ""))


def test_sandbox() -> None:
    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        escaped = False
        try:
            ws.resolve("../../etc/passwd")
        except WorkspaceError:
            escaped = True
        check("sandbox rejects escape", escaped)


def test_agent_loop() -> None:
    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        gate = PermissionGate()
        events: list[dict] = []

        calls = {"n": 0}

        def mock_llm(api_key, base_url, messages, model, temperature, tools, on_text=None, stop_flag=None):
            calls["n"] += 1
            if calls["n"] == 1:
                # poproś o utworzenie pliku
                return {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": "call_1", "type": "function",
                        "function": {"name": "write_file",
                                     "arguments": '{"path": "hello.txt", "content": "hi from agent"}'},
                    }],
                }
            # druga tura: brak tool_calls -> koniec
            return {"role": "assistant", "content": "Created hello.txt."}

        def request_approval(call_id, name, detail):
            events.append({"type": "approval_request", "id": call_id, "name": name, "detail": detail})
            return "accept"

        session = AgentSession(
            ws, gate, mock_llm, lambda: "test-key", "http://unused",
            emit=events.append, request_approval=request_approval,
        )
        session.run_turn("create hello.txt", model="mock")

        types = [e.get("type") for e in events]
        check("loop emits tool_call", "tool_call" in types)
        check("loop requests approval (write)", "approval_request" in types)
        check("loop emits tool_result", "tool_result" in types)
        check("loop finishes (assistant_done)", "assistant_done" in types)
        check("agent wrote file", (ws.root / "hello.txt").read_text(encoding="utf-8") == "hi from agent")
        check("mock called twice", calls["n"] == 2)


def test_interrupted_tool_calls() -> None:
    """P0-5: Stop w środku batcha nie zostawia tool_call bez odpowiedzi `tool`."""
    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        gate = PermissionGate()
        events: list[dict] = []
        handled = {"n": 0}

        def mock_llm(api_key, base_url, messages, model, temperature, tools, on_text=None, stop_flag=None):
            # jedna tura: assistant z DWOMA tool_calls
            return {
                "role": "assistant", "content": None,
                "tool_calls": [
                    {"id": "c1", "type": "function",
                     "function": {"name": "read_file", "arguments": '{"path": "a.txt"}'}},
                    {"id": "c2", "type": "function",
                     "function": {"name": "read_file", "arguments": '{"path": "b.txt"}'}},
                ],
            }

        def emit(ev):
            events.append(ev)
            if ev.get("type") == "tool_result":
                handled["n"] += 1

        session = AgentSession(ws, gate, mock_llm, lambda: "k", "http://unused",
                               emit=emit, request_approval=lambda *a: "accept")
        # Stop aktywuje się po obsłużeniu PIERWSZEGO tool_calla (c2 zostaje przerwany)
        session.run_turn("read files", model="mock", stop_flag=lambda: handled["n"] >= 1)

        asst = [m for m in session.history if m.get("role") == "assistant" and m.get("tool_calls")]
        want_ids = {tc["id"] for m in asst for tc in m["tool_calls"]}
        got_ids = {m.get("tool_call_id") for m in session.history if m.get("role") == "tool"}
        check("interrupted: assistant batch recorded", len(asst) == 1 and want_ids == {"c1", "c2"})
        check("interrupted: every tool_call answered", want_ids <= got_ids)
        check("interrupted: stopped emitted", any(e.get("type") == "stopped" for e in events))
        synth = [m for m in session.history
                 if m.get("role") == "tool" and m.get("tool_call_id") == "c2"]
        check("interrupted: synthetic result present",
              bool(synth) and "interrupt" in synth[0]["content"].lower())


def test_history_balanced_after_tools() -> None:
    """P0-5: po zwykłej turze z narzędziami self.history ma odpowiedzi `tool`
    (kontrakt xAI: każdy tool_call ↔ tool), więc kolejna tura nie da 400."""
    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        gate = PermissionGate()
        calls = {"n": 0}

        def mock_llm(api_key, base_url, messages, model, temperature, tools, on_text=None, stop_flag=None):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"role": "assistant", "content": None, "tool_calls": [
                    {"id": "w1", "type": "function",
                     "function": {"name": "write_file",
                                  "arguments": '{"path": "x.txt", "content": "hi"}'}}]}
            return {"role": "assistant", "content": "done"}

        session = AgentSession(ws, gate, mock_llm, lambda: "k", "http://unused",
                               emit=lambda ev: None, request_approval=lambda *a: "accept")
        session.run_turn("make x", model="mock")

        # każdy tool_call w historii musi mieć odpowiadającą wiadomość tool
        want = {tc["id"] for m in session.history
                if m.get("role") == "assistant" for tc in (m.get("tool_calls") or [])}
        got = {m.get("tool_call_id") for m in session.history if m.get("role") == "tool"}
        check("history: tool_call answered in history", want and want <= got)


def test_permission_path_norm() -> None:
    """P0-7: klucz allowlisty normalizuje ścieżkę (src/a.py == ./src/a.py)."""
    gate = PermissionGate()
    gate.allow("write_file", {"path": "src/a.py"})
    check("path key: exact", not gate.needs_approval("write_file", {"path": "src/a.py"}))
    check("path key: ./ prefix", not gate.needs_approval("write_file", {"path": "./src/a.py"}))
    check("path key: ./ middle", not gate.needs_approval("write_file", {"path": "src/./a.py"}))


def test_permissions_persistence() -> None:
    with tempfile.TemporaryDirectory() as d:
        store = Path(d) / "grok_permissions.json"

        gate = PermissionGate(store)
        check("fresh gate needs approval", gate.needs_approval("write_file", {"path": "a.py"}))
        gate.allow("write_file", {"path": "a.py"})
        check("allowed rule skips approval", not gate.needs_approval("write_file", {"path": "a.py"}))
        check("rule listed", "tool:write_file:a.py" in gate.rules())
        check("store file written", store.exists())

        reloaded = PermissionGate(store)
        check("rule survives reload", not reloaded.needs_approval("write_file", {"path": "a.py"}))

        reloaded.clear()
        check("clear empties rules", reloaded.rules() == [])
        check("clear persists", PermissionGate(store).rules() == [])


def test_glob_sandbox() -> None:
    """P0-2: glob nie może enumerować plików poza workspace."""
    with tempfile.TemporaryDirectory() as parent:
        secret = Path(parent) / "secret.txt"
        secret.write_text("TOPSECRET", encoding="utf-8")
        wsdir = Path(parent) / "ws"
        (wsdir / "pkg").mkdir(parents=True)
        (wsdir / "pkg" / "inside.py").write_text("x = 1\n", encoding="utf-8")
        ws = Workspace(str(wsdir))

        check("glob finds inside file", "pkg/inside.py" in T.glob(ws, "**/*.py"))

        esc = T.glob(ws, "../**/*")
        check("glob '..' does not leak outside", "secret.txt" not in esc and "TOPSECRET" not in esc)
        check("glob '..' rejected", esc.startswith("Error"))

        absp = T.glob(ws, str(Path(parent) / "*"))
        check("glob absolute does not leak outside", "secret.txt" not in absp)
        check("glob absolute rejected", absp.startswith("Error"))


def test_grep_limits() -> None:
    """P0-3: grep ma timeout ReDoS oraz pomija pliki duże i binarne."""
    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)

        # ReDoS: katastrofalny wzorzec ma być przerwany timeoutem, nie wisieć.
        # Tail 'b' uniemożliwia dopasowanie → wymusza wykładniczy backtracking.
        (ws.root / "redos.txt").write_text("a" * 4000 + "b\n", encoding="utf-8")
        res = T.grep(ws, r"(a|a)*$")
        check("grep ReDoS times out", res.startswith("Error") and "timed out" in res)

        # plik binarny (bajt NUL) pomijany
        (ws.root / "blob.bin").write_bytes(b"needle\x00needle")
        check("grep skips binary file", "blob.bin" not in T.grep(ws, "needle"))

        # plik > limitu pomijany mimo trafienia w treści
        big = ws.root / "big.txt"
        big.write_text("needle\n" * (T.GREP_MAX_FILE_BYTES // 7 + 1000), encoding="utf-8")
        big_res = T.grep(ws, "needle")
        check("grep skips oversized file", "big.txt" not in big_res and "skipped" in big_res)

        # zwykłe trafienie nadal działa
        (ws.root / "ok.txt").write_text("find me here\n", encoding="utf-8")
        check("grep still matches normal file", "ok.txt:1:" in T.grep(ws, "find me"))


def test_run_command_stop() -> None:
    """P0-4: Stop przerywa działającą komendę (i jej drzewo) bez czekania na koniec."""
    import time as _t
    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        cmd = "ping -n 10 127.0.0.1" if os.name == "nt" else "sleep 10"
        start = _t.monotonic()
        stop_at = start + 0.5
        out = T.run_command(ws, cmd, timeout=30, stop_flag=lambda: _t.monotonic() > stop_at)
        elapsed = _t.monotonic() - start
        check("run_command honors stop", "[stopped]" in out)
        check("run_command stops promptly (tree-kill)", elapsed < 5)


def test_atomic_write() -> None:
    """P0-7: write_file/edit_file zapisują atomowo, bez plików tymczasowych."""
    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        T.write_file(ws, "sub/f.txt", "hello")
        check("atomic write content", (ws.root / "sub/f.txt").read_text(encoding="utf-8") == "hello")
        T.edit_file(ws, "sub/f.txt", "hello", "world")
        check("atomic edit content", (ws.root / "sub/f.txt").read_text(encoding="utf-8") == "world")
        leftovers = list((ws.root / "sub").glob(".grok-*.tmp"))
        check("no temp file left behind", leftovers == [])


def test_symlink_sandbox() -> None:
    """P0-7: enumeratory nie podążają za symlinkiem/junctionem poza workspace."""
    import subprocess as _sp
    with tempfile.TemporaryDirectory() as parent:
        secret_dir = Path(parent) / "secret"
        secret_dir.mkdir()
        (secret_dir / "leak.txt").write_text("TOPSECRET_GREP\n", encoding="utf-8")
        wsdir = Path(parent) / "ws"
        wsdir.mkdir()
        (wsdir / "ok.txt").write_text("TOPSECRET_GREP visible here\n", encoding="utf-8")

        link = wsdir / "escape"
        made = False
        try:
            if os.name == "nt":
                r = _sp.run(["cmd", "/c", "mklink", "/J", str(link), str(secret_dir)],
                            stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
                made = r.returncode == 0
            else:
                os.symlink(str(secret_dir), str(link))
                made = True
        except Exception:
            made = False

        ws = Workspace(str(wsdir))
        if made:
            res = T.grep(ws, "TOPSECRET_GREP")
            check("grep does not follow link outside", "leak.txt" not in res)
            check("grep still finds in-workspace match", "ok.txt:1:" in res)
            check("list_dir skips escaping link", "escape" not in T.list_dir(ws, "."))
        else:
            check("symlink/junction test skipped (no privilege)", True)


def test_run_command_env_scrub() -> None:
    """P0-6: run_command nie ujawnia sekretów (GROK_CORE_TOKEN, XAI_API_KEY) modelowi."""
    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        keys = ("GROK_CORE_TOKEN", "XAI_API_KEY", "GROK_VISIBLE")
        saved = {k: os.environ.get(k) for k in keys}
        try:
            os.environ["GROK_CORE_TOKEN"] = "LEAKTOKEN_should_not_appear"
            os.environ["XAI_API_KEY"] = "sk-LEAKKEY_should_not_appear"
            os.environ["GROK_VISIBLE"] = "VISIBLE_marker_ok"

            env = T.scrubbed_env()
            check("env scrub removes token", "GROK_CORE_TOKEN" not in env)
            check("env scrub removes api key", "XAI_API_KEY" not in env)
            check("env scrub keeps normal var", env.get("GROK_VISIBLE") == "VISIBLE_marker_ok")

            dump = "set" if os.name == "nt" else "env"
            out = T.run_command(ws, dump)
            check("run_command hides token", "LEAKTOKEN_should_not_appear" not in out)
            check("run_command hides api key", "sk-LEAKKEY_should_not_appear" not in out)
            check("run_command keeps normal var", "VISIBLE_marker_ok" in out)
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


def test_command_security() -> None:
    """P0-1: łańcuchowanie komend nie obchodzi allowlisty „Always allow"."""
    # detektor metaznaków — świadomy cudzysłowów
    check("metachars: plain command safe", command_metachars("git status") == set())
    check("metachars: && flagged", "&" in command_metachars("git status && rm -rf x"))
    check("metachars: pipe flagged", "|" in command_metachars("cat a | sh"))
    check("metachars: semicolon flagged", ";" in command_metachars("git; curl evil"))
    check("metachars: $() flagged", "$" in command_metachars("echo $(whoami)"))
    check("metachars: backtick flagged", "`" in command_metachars("echo `id`"))
    check("metachars: quoted parens safe", command_metachars('python -c "print(1)"') == set())
    check("metachars: quoted path safe", command_metachars('cd "C:\\Program Files"') == set())
    check("metachars: unbalanced quote rejected", '"' in command_metachars('echo "oops'))

    # P0-10: model POSIX zamyka dziurę parzystości cudzysłowów. Ten sam payload
    # (`\"` przed `&&`) jest PUSTY dla modelu cmd.exe, a NIEPUSTY dla `sh` — bo w
    # `sh` `\"` jest literałem i NIE przełącza cudzysłowu, więc `&&` jest poza nim.
    parity = 'git \\" && echo hi"'
    check("metachars: cmd.exe model misses \\\" parity payload",
          command_metachars(parity, posix=False) == set())
    check("metachars: posix model catches \\\" parity payload",
          bool(command_metachars(parity, posix=True)))
    check("metachars: posix single-quote is literal",
          command_metachars("echo 'a && b'", posix=True) == set())
    check("metachars: posix backslash-escaped char then chain still flagged",
          "&" in command_metachars("echo \\a && b", posix=True))

    # bramka uprawnień: klucz po pełnej komendzie, nie po nazwie exe
    with tempfile.TemporaryDirectory() as d:
        store = Path(d) / "grok_permissions.json"
        gate = PermissionGate(store)

        check("run_command needs approval (fresh)",
              gate.needs_approval("run_command", {"command": "git status"}))
        gate.allow("run_command", {"command": "git status"})
        check("allowed exact command skips approval",
              not gate.needs_approval("run_command", {"command": "git status"}))
        check("whitespace variant matches allowlist",
              not gate.needs_approval("run_command", {"command": "git   status"}))
        # KLUCZOWE: inna podkomenda tego samego exe NIE jest auto-dopuszczona
        check("different git subcommand still asks",
              gate.needs_approval("run_command", {"command": "git push --force"}))
        # KLUCZOWE: doklejony payload NIE jest auto-dopuszczony mimo `git status`
        check("chained payload still asks",
              gate.needs_approval("run_command", {"command": "git status && rm -rf x"}))

        # komendy z metaznakami nie da się dopuścić („Always allow")
        gate.allow("run_command", {"command": "git status && rm -rf x"})
        check("dangerous command not allowlisted",
              gate.needs_approval("run_command", {"command": "git status && rm -rf x"}))
        check("no dangerous rule persisted",
              all("&" not in r and "rm -rf" not in r for r in gate.rules()))

    # egzekutor odrzuca metaznaki PRZED uruchomieniem (nic za && się nie wykona)
    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        chained = T.run_command(ws, "echo first && echo second")
        check("run_command rejects chaining",
              chained.startswith("Error") and "second" not in chained)
        check("run_command rejects pipe", T.run_command(ws, "echo a | sh").startswith("Error"))
        safe = T.run_command(ws, "echo hello-agent")
        check("run_command still runs safe command", "hello-agent" in safe and "exit 0" in safe)


def test_ws_stream() -> None:
    """P0-9/P2-12: WsStream ma OGRANICZONĄ kolejkę i DOŁĄCZA workera na zamknięciu
    (worker nie działa po rozłączeniu; ramki są dostarczane do momentu zamknięcia)."""
    import asyncio as _aio

    class _FakeWS:
        def __init__(self) -> None:
            self.sent: list = []

        async def send_json(self, item) -> None:
            self.sent.append(item)

    async def _run() -> None:
        from grok_core.routes._ws import WsStream

        ws = _FakeWS()
        holder: dict = {}
        async with WsStream(ws, maxsize=8) as stream:
            check("wsstream: bounded queue", stream.out_q.maxsize == 8)

            def worker() -> None:
                for i in range(3):
                    stream.emit({"type": "frame", "i": i})

            t = threading.Thread(target=worker, daemon=True)
            holder["t"] = t
            stream.track(t)
            t.start()
            await _aio.sleep(0.2)  # pozwól pętli opróżnić kolejkę do sendera
        # po wyjściu z async with: sender domknięty, worker dołączony
        check("wsstream: worker joined on close", not holder["t"].is_alive())
        check("wsstream: frames delivered",
              sum(1 for m in ws.sent if m.get("type") == "frame") == 3)

    _aio.run(_run())


def test_diff_binary() -> None:
    """M13-B1: preview_change — diff dla write/edit, nowy plik (`created`), binarny."""
    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)

        # nowy plik → diff jako same dodania + flaga created
        prev_new = T.preview_change(ws, "write_file", {"path": "new.txt", "content": "line1\nline2\n"})
        check("B1: new file preview is created diff",
              prev_new and prev_new["kind"] == "diff" and prev_new.get("created") is True
              and "+line1" in prev_new["diff"])

        # nadpisanie istniejącego pliku tekstowego → diff z usunięciem i dodaniem
        T.write_file(ws, "a.txt", "old line\n")
        prev_ov = T.preview_change(ws, "write_file", {"path": "a.txt", "content": "new line\n"})
        check("B1: overwrite text preview is diff (not created)",
              prev_ov and prev_ov["kind"] == "diff" and prev_ov.get("created") is False
              and "-old line" in prev_ov["diff"] and "+new line" in prev_ov["diff"])

        # plik binarny → znacznik „binary", BEZ diffa
        (ws.root / "blob.bin").write_bytes(b"\x00\x01\x02BINARY\x00data")
        prev_bin = T.preview_change(ws, "write_file", {"path": "blob.bin", "content": "x"})
        check("B1: binary file preview is 'binary' marker with size",
              prev_bin and prev_bin["kind"] == "binary" and prev_bin.get("bytes", 0) > 0
              and "diff" not in prev_bin)

        # edit_file na istniejącym → diff
        prev_edit = T.preview_change(ws, "edit_file",
                                     {"path": "a.txt", "old_string": "old line", "new_string": "z"})
        check("B1: edit preview is diff", prev_edit and prev_edit["kind"] == "diff")


def test_plan_mode() -> None:
    """M13-B2: w trybie planowania mutacje są blokowane, READONLY działa, plan nie
    tworzy checkpointu."""
    from grok_core.agent.checkpoints import CheckpointManager

    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        (ws.root / "a.txt").write_text("orig\n", encoding="utf-8")
        gate = PermissionGate()
        cpm = CheckpointManager(ws.root)
        events: list[dict] = []
        approvals = {"n": 0}

        calls = {"n": 0}

        def mock_llm(api_key, base_url, messages, model, temperature, tools, on_text=None, stop_flag=None):
            calls["n"] += 1
            if calls["n"] == 1:  # READONLY — dozwolone w plan mode
                return {"role": "assistant", "content": None, "tool_calls": [
                    {"id": "r1", "type": "function",
                     "function": {"name": "read_file", "arguments": '{"path": "a.txt"}'}}]}
            if calls["n"] == 2:  # MUTATING — blokowane w plan mode
                return {"role": "assistant", "content": None, "tool_calls": [
                    {"id": "w1", "type": "function",
                     "function": {"name": "write_file",
                                  "arguments": '{"path": "blocked.txt", "content": "nope"}'}}]}
            return {"role": "assistant", "content": "Plan: 1) do X 2) do Y"}

        def request_approval(call_id, name, detail):
            approvals["n"] += 1  # w plan mode NIE powinno paść żadne pytanie o mutację
            return "accept"

        session = AgentSession(
            ws, gate, mock_llm, lambda: "k", "http://unused",
            emit=events.append, request_approval=request_approval,
            checkpoints_provider=lambda: cpm,
        )
        session.run_turn("change something", model="mock", mode="plan")

        results = [e for e in events if e.get("type") == "tool_result"]
        read_ok = any(e["id"] == "r1" and e["ok"] for e in results)
        write_blocked = any(e["id"] == "w1" and not e["ok"]
                            and "plan mode" in (e.get("summary") or "").lower() for e in results)
        check("B2: READONLY tool runs in plan mode", read_ok)
        check("B2: MUTATING tool blocked in plan mode", write_blocked)
        check("B2: no approval prompt in plan mode", approvals["n"] == 0)
        check("B2: blocked write did not create file", not (ws.root / "blocked.txt").exists())
        check("B2: plan mode creates no checkpoint", cpm.list()["checkpoints"] == [])

        # po przełączeniu (plan=False) mutacja przechodzi (te same narzędzia, bramka jak zwykle)
        calls["n"] = 0
        events.clear()

        def mock_exec(api_key, base_url, messages, model, temperature, tools, on_text=None, stop_flag=None):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"role": "assistant", "content": None, "tool_calls": [
                    {"id": "w2", "type": "function",
                     "function": {"name": "write_file",
                                  "arguments": '{"path": "done.txt", "content": "ok"}'}}]}
            return {"role": "assistant", "content": "done"}

        session.llm_fn = mock_exec
        session.run_turn("now do it", model="mock", mode="ask")
        check("B2: MUTATING allowed after switching to execute",
              (ws.root / "done.txt").read_text(encoding="utf-8") == "ok")


def test_agent_modes() -> None:
    """M13: tryby agenta — accept-edits auto-akceptuje write/edit (ale pyta o komendę),
    bypass auto-akceptuje wszystko; zmiany nadal trafiają do checkpointów."""
    from grok_core.agent.checkpoints import CheckpointManager

    def build(mode: str):
        d = tempfile.mkdtemp()
        ws = Workspace(d)
        gate = PermissionGate()
        cpm = CheckpointManager(ws.root)
        asked: list[str] = []

        calls = {"n": 0}

        def mock_llm(api_key, base_url, messages, model, temperature, tools, on_text=None, stop_flag=None):
            i = calls["n"]
            calls["n"] += 1
            if i == 0:
                return {"role": "assistant", "content": None, "tool_calls": [
                    {"id": "w", "type": "function",
                     "function": {"name": "write_file",
                                  "arguments": '{"path": "f.txt", "content": "hi"}'}}]}
            if i == 1:
                return {"role": "assistant", "content": None, "tool_calls": [
                    {"id": "c", "type": "function",
                     "function": {"name": "run_command",
                                  "arguments": '{"command": "echo hi-mode"}'}}]}
            return {"role": "assistant", "content": "done"}

        def request_approval(call_id, name, detail):
            asked.append(name)
            return "accept"

        session = AgentSession(ws, gate, mock_llm, lambda: "k", "http://unused",
                               emit=lambda ev: None, request_approval=request_approval,
                               checkpoints_provider=lambda: cpm)
        session.run_turn("go", model="mock", mode=mode)
        return ws, cpm, asked

    # accept-edits: write auto-zaakceptowany, ale komenda PYTANA
    ws, cpm, asked = build("accept-edits")
    check("modes: accept-edits auto-accepts write (no prompt for write)",
          "write_file" not in asked and (ws.root / "f.txt").read_text(encoding="utf-8") == "hi")
    check("modes: accept-edits still asks for run_command", "run_command" in asked)
    check("modes: accept-edits still snapshots edits (undo works)",
          cpm.list()["checkpoints"] and cpm.list()["checkpoints"][0]["files"] >= 1)

    # bypass: nic nie pytane (ani write, ani komenda)
    ws, cpm, asked = build("bypass")
    check("modes: bypass auto-accepts everything (no prompts)", asked == [])
    check("modes: bypass applied the write", (ws.root / "f.txt").read_text(encoding="utf-8") == "hi")


def test_checkpoints() -> None:
    """M13-B3: snapshot przed zapisem, undo (restore + usunięcie utworzonych),
    sandbox, oznaczenie „partial" przy run_command, undo do wskazanego checkpointu."""
    from grok_core.agent.checkpoints import CheckpointManager

    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        for n in ("a.txt", "b.txt", "e.txt"):
            (ws.root / n).write_text(f"orig {n}\n", encoding="utf-8")
        gate = PermissionGate()
        cpm = CheckpointManager(ws.root)
        events: list[dict] = []

        # Tura: edytuj 3 pliki + utwórz 1 (write c.txt) — wszystko auto-accept.
        steps = [
            ("edit_file", '{"path": "a.txt", "old_string": "orig a.txt", "new_string": "EDIT a"}'),
            ("edit_file", '{"path": "b.txt", "old_string": "orig b.txt", "new_string": "EDIT b"}'),
            ("write_file", '{"path": "e.txt", "content": "OVERWRITTEN e"}'),
            ("write_file", '{"path": "c.txt", "content": "NEW c"}'),
        ]
        calls = {"n": 0}

        def mock_llm(api_key, base_url, messages, model, temperature, tools, on_text=None, stop_flag=None):
            i = calls["n"]
            calls["n"] += 1
            if i < len(steps):
                nm, ar = steps[i]
                return {"role": "assistant", "content": None, "tool_calls": [
                    {"id": f"c{i}", "type": "function",
                     "function": {"name": nm, "arguments": ar}}]}
            return {"role": "assistant", "content": "edited 4 files"}

        session = AgentSession(
            ws, gate, mock_llm, lambda: "k", "http://unused",
            emit=events.append, request_approval=lambda *a: "accept",
            checkpoints_provider=lambda: cpm,
        )
        session.run_turn("edit files", model="mock")

        check("B3: checkpoint created on first mutation", len(cpm.list()["checkpoints"]) == 1)
        check("B3: checkpoint event emitted", any(e.get("type") == "checkpoint" for e in events))
        check("B3: edits + create applied",
              (ws.root / "a.txt").read_text(encoding="utf-8") == "EDIT a\n"
              and (ws.root / "c.txt").exists()
              and (ws.root / "e.txt").read_text(encoding="utf-8") == "OVERWRITTEN e")

        res = cpm.undo_to()  # cofnij całą sesję
        check("B3: undo restores edited files",
              (ws.root / "a.txt").read_text(encoding="utf-8") == "orig a.txt\n"
              and (ws.root / "b.txt").read_text(encoding="utf-8") == "orig b.txt\n"
              and (ws.root / "e.txt").read_text(encoding="utf-8") == "orig e.txt\n")
        check("B3: undo deletes created file", not (ws.root / "c.txt").exists())
        check("B3: undo summary lists restored + deleted",
              "a.txt" in res["restored"] and "c.txt" in res["deleted"])
        check("B3: checkpoints cleared after full undo", cpm.list()["checkpoints"] == [])

    # run_command oznacza turę jako „partial undo"
    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        cpm = CheckpointManager(ws.root)
        cpm.begin_turn(label="t")
        cpm.snapshot("x.txt")          # otwiera checkpoint
        cpm.mark_command()
        check("B3: run_command marks session partial", cpm.list()["partial"] is True)
        check("B3: run_command marks checkpoint partial",
              cpm.list()["checkpoints"][0]["has_command"] is True)

    # sandbox: snapshot ścieżki spoza workspace jest ignorowany (nie kopiuje)
    with tempfile.TemporaryDirectory() as parent:
        wsdir = Path(parent) / "ws"
        wsdir.mkdir()
        ws = Workspace(str(wsdir))
        cpm = CheckpointManager(ws.root)
        cpm.begin_turn()
        cpm.snapshot("../../etc/passwd")
        cps = cpm.list()["checkpoints"]
        check("B3: out-of-sandbox snapshot ignored",
              cps == [] or all(c["files"] == 0 for c in cps))

    # undo do KONKRETNEGO checkpointu (dwie tury, cofnij tylko drugą)
    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(str(d))
        (ws.root / "f.txt").write_text("v0\n", encoding="utf-8")
        cpm = CheckpointManager(ws.root)
        cpm.begin_turn(label="turn1")
        cpm.snapshot("f.txt")
        T.write_file(ws, "f.txt", "v1\n")
        cpm.begin_turn(label="turn2")
        cpm.snapshot("f.txt")
        T.write_file(ws, "f.txt", "v2\n")
        cp2 = cpm.list()["checkpoints"][1]["id"]
        cpm.undo_to(cp2)  # cofnij tylko drugą turę → stan po turze 1
        check("B3: undo to checkpoint restores that point",
              (ws.root / "f.txt").read_text(encoding="utf-8") == "v1\n")
        check("B3: earlier checkpoint remains after partial undo",
              len(cpm.list()["checkpoints"]) == 1)


def test_grok_md() -> None:
    """M13-B4: GROK.md wczytany i wstrzyknięty, cap rozmiaru, brak pliku OK,
    workspace nadpisuje (idzie po) global."""
    from grok_core.agent.grokmd import (
        MAX_GROK_MD_BYTES, build_system_prompt, load_grok_md,
    )

    with tempfile.TemporaryDirectory() as wsd, tempfile.TemporaryDirectory() as gd:
        ws_root, global_dir = Path(wsd), Path(gd)

        check("B4: no GROK.md -> empty", load_grok_md(ws_root, global_dir) == "")

        (global_dir / "GROK.md").write_text("GLOBAL_RULE_X", encoding="utf-8")
        (ws_root / "GROK.md").write_text("WS_RULE_Y", encoding="utf-8")
        loaded = load_grok_md(ws_root, global_dir)
        check("B4: both global + workspace loaded",
              "GLOBAL_RULE_X" in loaded and "WS_RULE_Y" in loaded)
        check("B4: workspace placed after global (override)",
              loaded.index("WS_RULE_Y") > loaded.index("GLOBAL_RULE_X"))

        base = "BASE_PROMPT"
        prompt = build_system_prompt(base, ws_root, global_dir)
        check("B4: injected into system prompt",
              prompt.startswith(base) and "WS_RULE_Y" in prompt and "GROK.md" in prompt)

        # brak reguł → bazowy prompt bez zmian
        check("B4: empty rules keep base prompt unchanged",
              build_system_prompt(base, Path(wsd) / "nope", Path(gd) / "nope") == base)

        # cap rozmiaru
        (ws_root / "GROK.md").write_text("Z" * (MAX_GROK_MD_BYTES + 5000), encoding="utf-8")
        capped = load_grok_md(ws_root, None)
        check("B4: oversize GROK.md capped",
              len(capped) <= MAX_GROK_MD_BYTES + 200 and "truncated" in capped)


def main() -> int:
    test_tools()
    test_sandbox()
    test_agent_loop()
    test_interrupted_tool_calls()
    test_history_balanced_after_tools()
    test_permission_path_norm()
    test_permissions_persistence()
    test_glob_sandbox()
    test_grep_limits()
    test_run_command_stop()
    test_run_command_env_scrub()
    test_atomic_write()
    test_symlink_sandbox()
    test_command_security()
    test_ws_stream()
    # M13 — agent: zaufanie (diff / plan / checkpoint / GROK.md / tryby)
    test_diff_binary()
    test_plan_mode()
    test_agent_modes()
    test_checkpoints()
    test_grok_md()
    ok = True
    for name, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    print("RESULT:", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
