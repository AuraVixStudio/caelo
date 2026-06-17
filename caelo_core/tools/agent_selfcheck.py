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

import json
import os
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from caelo_core.agent import tools as T  # noqa: E402
from caelo_core.agent.permissions import PermissionGate, command_metachars  # noqa: E402
from caelo_core.agent.session import AgentSession  # noqa: E402
from caelo_core.agent.workspace import Workspace, WorkspaceError  # noqa: E402

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

        # edit_file odporny na różnice wcięć/białych znaków (najczęstsza pętla agenta):
        # plik z tabem, model podaje old_string ze spacjami → flexible match trafia.
        T.write_file(ws, "src/ind.py", "def f():\n\treturn 1\n")  # wcięcie tabem
        flex = T.edit_file(ws, "src/ind.py", "    return 1", "    return 2")  # model dał spacje
        check("edit_file tolerates indent (tab vs spaces)", "Edited" in flex)
        check("edit_file flexible applied", "return 2" in (ws.root / "src/ind.py").read_text(encoding="utf-8"))
        # CRLF w old_string a plik znormalizowany do LF → też trafia.
        T.write_file(ws, "src/crlf.py", "a = 1\nb = 2\n")
        crlf = T.edit_file(ws, "src/crlf.py", "a = 1\r\nb = 2", "a = 9\nb = 2")
        check("edit_file tolerates CRLF old_string", "Edited" in crlf)
        # Flexible ambiguous: old_string nie pasuje dokładnie (trailing space), ale po strip
        # zgadza się z 2 liniami → NIE zgaduj, zwróć błąd.
        T.write_file(ws, "src/dup.py", "  foo\n    foo\n")
        amb = T.edit_file(ws, "src/dup.py", "foo ", "bar")
        check("edit_file ambiguous flexible still errors", amb.startswith("Error"))

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

        def mock_llm(api_key, base_url, messages, model, temperature, tools, on_text=None, stop_flag=None, **_):
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

        def mock_llm(api_key, base_url, messages, model, temperature, tools, on_text=None, stop_flag=None, **_):
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

        def mock_llm(api_key, base_url, messages, model, temperature, tools, on_text=None, stop_flag=None, **_):
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
        store = Path(d) / "caelo_permissions.json"

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


def test_device_and_read_cap() -> None:
    """3.3-a: Workspace.resolve odrzuca urządzenia Windows (CON…); read_file ma cap rozmiaru."""
    from caelo_core.agent.workspace import WorkspaceError
    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        if os.name == "nt":
            raised = False
            try:
                ws.resolve("CON")
            except WorkspaceError:
                raised = True
            check("3.3-a: resolve rejects CON device (Windows)", raised)
            # read_file deleguje rzucanie do execute_tool (jak escape) → Error string
            check("3.3-a: read_file (via execute_tool) rejects CON device",
                  T.execute_tool(ws, "read_file", {"path": "CON"}).startswith("Error"))
        else:
            check("3.3-a: device-name guard is Windows-only (skipped on POSIX)", True)
        # cap rozmiaru — portable; tymczasowo obniżamy stałą, by nie pisać 16 MB
        prev = T.READ_FILE_MAX_BYTES
        T.READ_FILE_MAX_BYTES = 10
        try:
            (ws.root / "big.bin").write_text("0123456789ABCDEF", encoding="utf-8")  # 16 > 10
            check("3.3-a: read_file rejects oversize file (cap)",
                  T.read_file(ws, "big.bin").startswith("Error"))
            (ws.root / "small.txt").write_text("hi", encoding="utf-8")
            check("3.3-a: read_file reads small file under cap",
                  not T.read_file(ws, "small.txt").startswith("Error"))
        finally:
            T.READ_FILE_MAX_BYTES = prev


def test_run_command_no_false_timeout() -> None:
    """3.3-f: szybka komenda kończąca exit 0 nie dostaje fałszywego [timeout]."""
    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        cmd = "cmd /c exit 0" if os.name == "nt" else "true"
        ok = True
        for _ in range(20):
            out = T.run_command(ws, cmd, timeout=1)
            if "[timeout]" in out or not out.startswith("(exit 0)"):
                ok = False
                break
        check("3.3-f: run_command never falsely reports timeout on fast exit", ok)


def test_web_fetch_dns_rebinding() -> None:
    """3.3-g: host rozwiązujący się na prywatne IP jest blokowany (DNS rebinding)."""
    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        prev = T.socket.getaddrinfo
        T.socket.getaddrinfo = lambda host, *a, **k: [(2, 1, 6, "", ("10.0.0.5", 443))]
        try:
            res = T.web_fetch(ws, url="https://rebind.example.com/x")
            check("3.3-g: web_fetch blocks host resolving to private IP",
                  isinstance(res, str) and "refused" in res)
        finally:
            T.socket.getaddrinfo = prev


def test_atomic_write() -> None:
    """P0-7: write_file/edit_file zapisują atomowo, bez plików tymczasowych."""
    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        T.write_file(ws, "sub/f.txt", "hello")
        check("atomic write content", (ws.root / "sub/f.txt").read_text(encoding="utf-8") == "hello")
        T.edit_file(ws, "sub/f.txt", "hello", "world")
        check("atomic edit content", (ws.root / "sub/f.txt").read_text(encoding="utf-8") == "world")
        leftovers = list((ws.root / "sub").glob(".caelo-*.tmp"))
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
    """P0-6: run_command nie ujawnia sekretów (CAELO_CORE_TOKEN, XAI_API_KEY) modelowi."""
    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        keys = ("CAELO_CORE_TOKEN", "XAI_API_KEY", "CAELO_VISIBLE")
        saved = {k: os.environ.get(k) for k in keys}
        try:
            os.environ["CAELO_CORE_TOKEN"] = "LEAKTOKEN_should_not_appear"
            os.environ["XAI_API_KEY"] = "sk-LEAKKEY_should_not_appear"
            os.environ["CAELO_VISIBLE"] = "VISIBLE_marker_ok"

            env = T.scrubbed_env()
            check("env scrub removes token", "CAELO_CORE_TOKEN" not in env)
            check("env scrub removes api key", "XAI_API_KEY" not in env)
            check("env scrub keeps normal var", env.get("CAELO_VISIBLE") == "VISIBLE_marker_ok")

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
        store = Path(d) / "caelo_permissions.json"
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
        from caelo_core.routes._ws import WsStream

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
    from caelo_core.agent.checkpoints import CheckpointManager

    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        (ws.root / "a.txt").write_text("orig\n", encoding="utf-8")
        gate = PermissionGate()
        cpm = CheckpointManager(ws.root)
        events: list[dict] = []
        approvals = {"n": 0}

        calls = {"n": 0}

        def mock_llm(api_key, base_url, messages, model, temperature, tools, on_text=None, stop_flag=None, **_):
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

        def mock_exec(api_key, base_url, messages, model, temperature, tools, on_text=None, stop_flag=None, **_):
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
    from caelo_core.agent.checkpoints import CheckpointManager

    def build(mode: str):
        d = tempfile.mkdtemp()
        ws = Workspace(d)
        gate = PermissionGate()
        cpm = CheckpointManager(ws.root)
        asked: list[str] = []

        calls = {"n": 0}

        def mock_llm(api_key, base_url, messages, model, temperature, tools, on_text=None, stop_flag=None, **_):
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
    from caelo_core.agent.checkpoints import CheckpointManager

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

        def mock_llm(api_key, base_url, messages, model, temperature, tools, on_text=None, stop_flag=None, **_):
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


def test_caelo_md() -> None:
    """M13-B4: CAELO.md wczytany i wstrzyknięty, cap rozmiaru, brak pliku OK,
    workspace nadpisuje (idzie po) global."""
    from caelo_core.agent.caelomd import (
        MAX_CAELO_MD_BYTES, build_system_prompt, load_caelo_md,
    )

    with tempfile.TemporaryDirectory() as wsd, tempfile.TemporaryDirectory() as gd:
        ws_root, global_dir = Path(wsd), Path(gd)

        check("B4: no CAELO.md -> empty", load_caelo_md(ws_root, global_dir) == "")

        (global_dir / "CAELO.md").write_text("GLOBAL_RULE_X", encoding="utf-8")
        (ws_root / "CAELO.md").write_text("WS_RULE_Y", encoding="utf-8")
        loaded = load_caelo_md(ws_root, global_dir)
        check("B4: both global + workspace loaded",
              "GLOBAL_RULE_X" in loaded and "WS_RULE_Y" in loaded)
        check("B4: workspace placed after global (override)",
              loaded.index("WS_RULE_Y") > loaded.index("GLOBAL_RULE_X"))

        base = "BASE_PROMPT"
        prompt = build_system_prompt(base, ws_root, global_dir)
        check("B4: injected into system prompt",
              prompt.startswith(base) and "WS_RULE_Y" in prompt and "CAELO.md" in prompt)

        # brak reguł → bazowy prompt bez zmian
        check("B4: empty rules keep base prompt unchanged",
              build_system_prompt(base, Path(wsd) / "nope", Path(gd) / "nope") == base)

        # cap rozmiaru
        (ws_root / "CAELO.md").write_text("Z" * (MAX_CAELO_MD_BYTES + 5000), encoding="utf-8")
        capped = load_caelo_md(ws_root, None)
        check("B4: oversize CAELO.md capped",
              len(capped) <= MAX_CAELO_MD_BYTES + 200 and "truncated" in capped)

    # --- M19-Tier2 B5 §1.1: interop AGENTS.md / CLAUDE.md ---
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        # Bez natywnego CAELO.md — same pliki ekosystemu.
        (root / "AGENTS.md").write_text("AGENTS_RULE_A", encoding="utf-8")
        (root / "CLAUDE.md").write_text("CLAUDE_RULE_C", encoding="utf-8")
        loaded = load_caelo_md(root, None)
        check("B5: AGENTS.md + CLAUDE.md both loaded (no CAELO.md)",
              "AGENTS_RULE_A" in loaded and "CLAUDE_RULE_C" in loaded)
        check("B5: source annotation per file",
              "From AGENTS.md" in loaded and "From CLAUDE.md" in loaded)
        check("B5: AGENTS.md placed before CLAUDE.md (priority order)",
              loaded.index("AGENTS_RULE_A") < loaded.index("CLAUDE_RULE_C"))

        # Dodaj natywny CAELO.md — ma pierwszeństwo (idzie pierwszy), reszta dołączona.
        (root / "CAELO.md").write_text("NATIVE_RULE_N", encoding="utf-8")
        loaded2 = load_caelo_md(root, None)
        check("B5: CAELO.md takes priority over interop files",
              loaded2.index("NATIVE_RULE_N") < loaded2.index("AGENTS_RULE_A")
              and loaded2.index("NATIVE_RULE_N") < loaded2.index("CLAUDE_RULE_C"))
        check("B5: interop files still appended alongside CAELO.md",
              "AGENTS_RULE_A" in loaded2 and "CLAUDE_RULE_C" in loaded2)

    # Legacy GROK.md pozostaje czystym fallbackiem: czytany TYLKO gdy brak CAELO.md.
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "GROK.md").write_text("LEGACY_GROK_G", encoding="utf-8")
        check("B5: GROK.md read when CAELO.md absent",
              "LEGACY_GROK_G" in load_caelo_md(root, None))
        (root / "CAELO.md").write_text("NATIVE_RULE_N", encoding="utf-8")
        with_native = load_caelo_md(root, None)
        check("B5: GROK.md ignored once CAELO.md exists (no double native)",
              "NATIVE_RULE_N" in with_native and "LEGACY_GROK_G" not in with_native)

    # --- IZOLACJA: interop (CLAUDE.md/AGENTS.md) jest WORKSPACE-only, NIE globalny ---
    # Regresja realnego bledu: w dev DATA_DIR == repo Caelo, wiec jego CLAUDE.md
    # (instrukcje dewelopera) wstrzykiwal sie do agenta nad KAZDYM, obcym projektem.
    with tempfile.TemporaryDirectory() as gd2, tempfile.TemporaryDirectory() as wsd2:
        gdir, wdir = Path(gd2), Path(wsd2)
        (gdir / "CLAUDE.md").write_text("DEV_REPO_CLAUDE_MD", encoding="utf-8")
        (gdir / "AGENTS.md").write_text("DEV_REPO_AGENTS_MD", encoding="utf-8")
        out = load_caelo_md(wdir, gdir)
        check("B5/iso: global CLAUDE.md/AGENTS.md NOT injected (interop is workspace-only)",
              "DEV_REPO_CLAUDE_MD" not in out and "DEV_REPO_AGENTS_MD" not in out and out == "")
        # ...ale globalny natywny CAELO.md dziala normalnie
        (gdir / "CAELO.md").write_text("GLOBAL_NATIVE_OK", encoding="utf-8")
        out2 = load_caelo_md(wdir, gdir)
        check("B5/iso: global native CAELO.md still injected",
              "GLOBAL_NATIVE_OK" in out2 and "DEV_REPO_CLAUDE_MD" not in out2)
        # ...a interop w WORKSPACE nadal dziala (workspace > global)
        (wdir / "CLAUDE.md").write_text("WS_CLAUDE_OK", encoding="utf-8")
        out3 = load_caelo_md(wdir, gdir)
        check("B5/iso: workspace CLAUDE.md still injected (interop ok in workspace)",
              "WS_CLAUDE_OK" in out3 and "DEV_REPO_CLAUDE_MD" not in out3)


class _FakeMcp:
    """Stub menedżera MCP (duck-typed kontrakt z caelo_core/mcp/manager.py) — bez sieci.
    Dwa narzędzia: lookup (readonly) i write (mutating)."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def tool_defs_for_responses(self) -> list:
        return [
            {"type": "function", "function": {
                "name": "mcp__t__lookup", "description": "readonly lookup",
                "parameters": {"type": "object", "properties": {"q": {"type": "string"}}}}},
            {"type": "function", "function": {
                "name": "mcp__t__write", "description": "mutating write",
                "parameters": {"type": "object", "properties": {"v": {"type": "string"}}}}},
        ]

    def is_mcp_tool(self, name: str) -> bool:
        return name in ("mcp__t__lookup", "mcp__t__write")

    def is_mutating(self, name: str) -> bool:
        return name == "mcp__t__write"

    def describe_tool(self, name: str) -> dict:
        return {"qualified_name": name, "name": name.split("__")[-1], "server_id": "t",
                "description": "desc", "readonly": name == "mcp__t__lookup"}

    def call_tool(self, name: str, args: dict) -> str:
        self.calls.append((name, dict(args or {})))
        return f"mcp-result:{name}"


def test_mcp_in_agent() -> None:
    """M14-B2: narzędzia MCP w pętli agenta — odkryte, readonly bez zgody, mutujące
    przez bramkę (klucz `mcp:` „Always allow"), wynik wraca do historii, plan mode
    blokuje mutujące."""
    # 1) tryb ask: advertise + gate + route + persist
    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        store = Path(d) / "perm.json"
        gate = PermissionGate(store)
        mcp = _FakeMcp()
        events: list[dict] = []
        asked: list[tuple] = []
        seen: dict = {}
        calls = {"n": 0}

        def mock_llm(api_key, base_url, messages, model, temperature, tools, on_text=None, stop_flag=None, **_):
            i = calls["n"]
            calls["n"] += 1
            seen["names"] = {t["function"]["name"] for t in tools if t.get("type") == "function"}
            if i == 0:
                return {"role": "assistant", "content": None, "tool_calls": [
                    {"id": "m1", "type": "function",
                     "function": {"name": "mcp__t__lookup", "arguments": '{"q": "hi"}'}}]}
            if i == 1:
                return {"role": "assistant", "content": None, "tool_calls": [
                    {"id": "m2", "type": "function",
                     "function": {"name": "mcp__t__write", "arguments": '{"v": "x"}'}}]}
            return {"role": "assistant", "content": "done"}

        def request_approval(call_id, name, detail):
            asked.append((name, detail))
            return "always"

        session = AgentSession(ws, gate, mock_llm, lambda: "k", "http://unused",
                               emit=events.append, request_approval=request_approval, mcp=mcp)
        session.run_turn("use mcp", model="mock", mode="ask")

        check("B2-mcp: MCP tools advertised to model",
              {"mcp__t__lookup", "mcp__t__write"} <= seen.get("names", set()))
        check("B2-mcp: file tools still advertised", "read_file" in seen.get("names", set()))
        asked_names = [a[0] for a in asked]
        check("B2-mcp: readonly MCP tool runs without approval", "mcp__t__lookup" not in asked_names)
        check("B2-mcp: mutating MCP tool requests approval", "mcp__t__write" in asked_names)
        detail = next((a[1] for a in asked if a[0] == "mcp__t__write"), {})
        check("B2-mcp: approval detail is mcp_tool_call",
              detail.get("kind") == "mcp_tool_call" and detail.get("server") == "t")
        check("B2-mcp: both MCP tools executed", {c[0] for c in mcp.calls} == {"mcp__t__lookup", "mcp__t__write"})
        tool_msgs = [m for m in session.history if m.get("role") == "tool"]
        check("B2-mcp: MCP result returned to history",
              any("mcp-result:mcp__t__write" in (m.get("content") or "") for m in tool_msgs))
        check("B2-mcp: always-allow persists mcp key", "mcp:mcp__t__write" in gate.rules())
        check("B2-mcp: persisted approval survives reload",
              not PermissionGate(store).needs_approval_key("mcp:mcp__t__write"))

    # 2) plan mode: mutujące MCP zablokowane, readonly MCP działa
    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        gate = PermissionGate()
        mcp = _FakeMcp()
        events = []
        approvals = {"n": 0}
        calls = {"n": 0}

        def mock_llm2(api_key, base_url, messages, model, temperature, tools, on_text=None, stop_flag=None, **_):
            i = calls["n"]
            calls["n"] += 1
            if i == 0:
                return {"role": "assistant", "content": None, "tool_calls": [
                    {"id": "p1", "type": "function",
                     "function": {"name": "mcp__t__lookup", "arguments": '{"q": "a"}'}}]}
            if i == 1:
                return {"role": "assistant", "content": None, "tool_calls": [
                    {"id": "p2", "type": "function",
                     "function": {"name": "mcp__t__write", "arguments": '{"v": "b"}'}}]}
            return {"role": "assistant", "content": "plan ready"}

        session = AgentSession(ws, gate, mock_llm2, lambda: "k", "http://unused",
                               emit=events.append,
                               request_approval=lambda *a: (approvals.__setitem__("n", approvals["n"] + 1), "accept")[1],
                               mcp=mcp)
        session.run_turn("plan it", model="mock", mode="plan")
        results = [e for e in events if e.get("type") == "tool_result"]
        check("B2-mcp: readonly MCP runs in plan mode",
              any(e["id"] == "p1" and e["ok"] for e in results))
        check("B2-mcp: mutating MCP blocked in plan mode",
              any(e["id"] == "p2" and not e["ok"] and "plan mode" in (e.get("summary") or "").lower()
                  for e in results))
        check("B2-mcp: blocked MCP tool not executed", "mcp__t__write" not in {c[0] for c in mcp.calls})
        check("B2-mcp: no approval prompt in plan mode", approvals["n"] == 0)


def test_hooks() -> None:
    """M14-B5: hooki (uogólniony PermissionGate) — pre_tool blokuje groźną komendę
    PRZED bramką, post_tool audytuje, run_script odpala po pasującym narzędziu;
    allowlista nienaruszona (P0 bez regresji)."""
    from caelo_core.hooks import HookManager

    # 1) unit: dopasowanie wzorca + domyślne hooki
    with tempfile.TemporaryDirectory() as d:
        hm = HookManager(Path(d) / "caelo_hooks.json", Path(d) / "audit.log")
        ids = {h["id"] for h in hm.list_hooks()}
        check("B5: default hooks present (block + audit)",
              "block-dangerous-commands" in ids and "audit-all" in ids)
        check("B5: pre_tool blocks rm -rf",
              hm.run_pre_tool("run_command", {"command": "rm -rf important"}) is not None)
        check("B5: pre_tool allows safe command",
              hm.run_pre_tool("run_command", {"command": "git status"}) is None)
        check("B5: pre_tool blocks force push",
              hm.run_pre_tool("run_command", {"command": "git push origin main --force"}) is not None)
        # S31-l: domknięte luki wzorców (git push -f, rd /s, del /f)
        check("S31-l: pre_tool blocks git push -f",
              hm.run_pre_tool("run_command", {"command": "git push origin main -f"}) is not None)
        check("S31-l: pre_tool blocks rd /s",
              hm.run_pre_tool("run_command", {"command": "rd /s /q C:\\x"}) is not None)
        check("S31-l: pre_tool blocks del /f",
              hm.run_pre_tool("run_command", {"command": "del /f /q x"}) is not None)
        # S31-l: matcher bloku jest FAIL-CLOSED (zły wzorzec/timeout → zablokuj)
        hit, err = HookManager._matches_blocking("(", "anything")
        check("S31-l: block matcher fails closed on bad pattern", hit is True and err is True)
        # disable → przepuszcza
        hm.set_enabled("block-dangerous-commands", False)
        check("B5: disabled block hook no longer blocks",
              hm.run_pre_tool("run_command", {"command": "rm -rf important"}) is None)
        hm.set_enabled("block-dangerous-commands", True)
        # audyt zapisuje wpisy (post_tool)
        hm.run_post_tool("write_file", {"path": "x.py"}, ok=True, result="Wrote")
        tail = hm.audit_tail()
        check("B5: audit logs tool call", any(e.get("action") == "tool" and e.get("tool") == "write_file"
                                              for e in tail))

    # 2) integracja: hook blokuje w pętli agenta PRZED bramką (no approval, not executed)
    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        gate = PermissionGate()
        hm = HookManager(Path(d) / "h.json", Path(d) / "a.log")
        events: list[dict] = []
        asked: list[str] = []
        calls = {"n": 0}

        def mock_llm(api_key, base_url, messages, model, temperature, tools, on_text=None, stop_flag=None, **_):
            i = calls["n"]
            calls["n"] += 1
            if i == 0:
                return {"role": "assistant", "content": None, "tool_calls": [
                    {"id": "c1", "type": "function",
                     "function": {"name": "run_command", "arguments": '{"command": "rm -rf important"}'}}]}
            return {"role": "assistant", "content": "done"}

        session = AgentSession(ws, gate, mock_llm, lambda: "k", "http://unused",
                               emit=events.append,
                               request_approval=lambda cid, n, det: (asked.append(n), "accept")[1],
                               hooks=hm)
        session.run_turn("danger", model="mock", mode="ask")
        results = [e for e in events if e.get("type") == "tool_result"]
        check("B5: hook-blocked command reported not-ok",
              any(e["id"] == "c1" and not e["ok"] for e in results))
        check("B5: hook blocks BEFORE gate (no approval asked)", "run_command" not in asked)
        check("B5: hook event emitted", any(e.get("type") == "hook" and e.get("action") == "blocked"
                                            for e in events))
        check("B5: block leaves allowlist untouched (no P0 regression)", gate.rules() == [])
        check("B5: blocked command logged to audit",
              any(e.get("action") == "blocked" for e in hm.audit_tail()))

    # 2b) S34-e: tryb bypass NIE omija pre_tool hooka (block-dangerous-commands) — hooki
    # są niezależne od trybu i poprzedzają pominięcie bramki (`already-fixed` w analizie).
    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        gate = PermissionGate()
        hm = HookManager(Path(d) / "hb.json", Path(d) / "ab.log")
        events = []
        asked = []
        calls = {"n": 0}

        def mock_llm_b(api_key, base_url, messages, model, temperature, tools, on_text=None, stop_flag=None, **_):
            i = calls["n"]
            calls["n"] += 1
            if i == 0:
                return {"role": "assistant", "content": None, "tool_calls": [
                    {"id": "cb", "type": "function",
                     "function": {"name": "run_command", "arguments": '{"command": "rm -rf important"}'}}]}
            return {"role": "assistant", "content": "done"}

        session = AgentSession(ws, gate, mock_llm_b, lambda: "k", "http://unused",
                               emit=events.append,
                               request_approval=lambda cid, n, det: (asked.append(n), "accept")[1],
                               hooks=hm)
        session.run_turn("danger", model="mock", mode="bypass")
        results = [e for e in events if e.get("type") == "tool_result"]
        check("S34-e: bypass does NOT skip block-dangerous-commands hook",
              any(e["id"] == "cb" and not e["ok"] for e in results)
              and "run_command" not in asked
              and any(e.get("type") == "hook" and e.get("action") == "blocked" for e in events))

    # 3) run_script post hook odpala po write_file
    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        gate = PermissionGate()
        hm = HookManager(Path(d) / "h2.json", Path(d) / "a2.log")
        # skrypt: utwórz marker w workspace (cwd = root)
        hm.add_hook({"id": "marker", "event": "post_tool", "type": "run_script",
                     "enabled": True, "match_tools": ["write_file"],
                     "command": [sys.executable, "-c", "open('hook_ran.txt','w').write('x')"]})
        calls = {"n": 0}

        def mock_llm2(api_key, base_url, messages, model, temperature, tools, on_text=None, stop_flag=None, **_):
            i = calls["n"]
            calls["n"] += 1
            if i == 0:
                return {"role": "assistant", "content": None, "tool_calls": [
                    {"id": "w", "type": "function",
                     "function": {"name": "write_file", "arguments": '{"path": "f.txt", "content": "hi"}'}}]}
            return {"role": "assistant", "content": "done"}

        session = AgentSession(ws, gate, mock_llm2, lambda: "k", "http://unused",
                               emit=lambda ev: None, request_approval=lambda *a: "accept",
                               hooks=hm)
        session.run_turn("write it", model="mock", mode="bypass")
        check("B5: run_script post hook executed (marker created)",
              (ws.root / "hook_ran.txt").exists())


# ----------------------------------------------------------------------------
# M17 — subagenci / zespół (B1 izolacja, B2 delegate+role, B3 równoległość+
# worktree, B4 scalanie, B5 limity, B6 telemetria). Mock LLM gra orkiestratora
# I subagentów (rozróżnia po system prompcie roli / dostępnym narzędziu delegate).
# ----------------------------------------------------------------------------
def _find_user(messages: list) -> str:
    for m in messages:
        if m.get("role") == "user":
            c = m.get("content")
            return c if isinstance(c, str) else ""
    return ""


def _n_assist(messages: list) -> int:
    return sum(1 for m in messages if m.get("role") == "assistant")


def _tool_names(tools: list) -> set:
    return {t["function"]["name"] for t in tools if t.get("type") == "function"}


def _make_registry(d: str, limits: dict | None = None):
    from caelo_core.agent.roles import RoleRegistry
    reg = RoleRegistry(Path(d) / "subagents.json")
    if limits:
        reg.set_limits(limits)
    return reg


def _make_team(reg, ws, gate, llm, *, emit=None, approval=None, stop=None,
               mcp=None, store=None, reports=None):
    from caelo_core.agent.team import MergeStore, TeamManager
    store = store if store is not None else MergeStore(ws.root)
    team = TeamManager(
        registry=reg, gate=gate, llm_fn=llm, api_key_provider=lambda: "k",
        base_url="http://unused", mcp=mcp, hooks=None,
        emit=emit or (lambda e: None), request_approval=approval or (lambda *a: "accept"),
        orchestrator_stop=stop or (lambda: False), merges_provider=lambda: store,
        on_report=(reports.append if reports is not None else None),
    )
    team.worktrees_base = Path(tempfile.mkdtemp())  # nie pisz do repo
    return team, store


def test_team_isolation_and_roles() -> None:
    """M17-B1/B2: subagent w izolacji zwraca streszczenie; rola egzekwuje zakres
    narzędzi (researcher NIE zapisze, brak `delegate` u subagenta = głębia 1);
    kontekst rodzica = jedno streszczenie, nie transkrypt."""
    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        gate = PermissionGate()
        reg = _make_registry(d)
        seen: dict[str, set] = {}

        def llm(api_key, base_url, messages, model, temperature, tools, on_text=None, stop_flag=None, **_):
            sys = messages[0]["content"]
            names = _tool_names(tools)
            if "delegate" in names:  # ORKIESTRATOR
                seen["orchestrator"] = names
                if _n_assist(messages) == 0:
                    return {"role": "assistant", "content": None, "tool_calls": [
                        {"id": "d1", "type": "function", "function": {
                            "name": "delegate", "arguments":
                            '{"tasks":[{"role":"researcher","task":"find X"},'
                            '{"role":"reviewer","task":"review Y"}]}'}}]}
                return {"role": "assistant", "content": "Integrated 2 subagent findings."}
            if "RESEARCH subagent" in sys:
                seen["researcher"] = names
                if _n_assist(messages) == 0:  # spróbuj zapis (poza rolą) → odrzucone
                    return {"role": "assistant", "content": None, "tool_calls": [
                        {"id": "r1", "type": "function", "function": {
                            "name": "write_file",
                            "arguments": '{"path":"sneaky.txt","content":"x"}'}}]}
                return {"role": "assistant", "content": "Research summary: found X."}
            if "CODE REVIEW subagent" in sys:
                seen["reviewer"] = names
                return {"role": "assistant", "content": "Review summary: looks fine."}
            return {"role": "assistant", "content": "done"}

        team, _store = _make_team(reg, ws, gate, llm)
        summary = team.run(
            [{"role": "researcher", "task": "find X"}, {"role": "reviewer", "task": "review Y"}],
            model="mock", workspace=ws, mode="ask")

        check("B1: subagent summaries returned to orchestrator",
              "Research summary" in summary and "Review summary" in summary)
        check("B2: role tool scope — researcher has no write_file",
              "write_file" not in seen.get("researcher", set())
              and {"read_file", "grep"} <= seen.get("researcher", set()))
        check("B5: subagent has no delegate (depth = 1)",
              "delegate" not in seen.get("researcher", set())
              and "delegate" not in seen.get("reviewer", set()))
        check("B2: out-of-scope write by researcher rejected (no escalation)",
              not (ws.root / "sneaky.txt").exists())

        # parent context clean: pełna sesja orkiestratora — delegate → JEDNO tool message
        orch_gate = PermissionGate()
        team2, _ = _make_team(reg, ws, orch_gate, llm)
        sess = AgentSession(ws, orch_gate, llm, lambda: "k", "http://unused",
                            emit=lambda e: None, request_approval=lambda *a: "accept",
                            delegate_fn=lambda tasks: team2.run(tasks, model="mock",
                                                                workspace=ws, mode="ask"))
        sess.run_turn("coordinate the work", model="mock", mode="ask")
        tool_msgs = [m for m in sess.history if m.get("role") == "tool"]
        check("B1: parent gets one delegate tool message (summary, not transcript)",
              len(tool_msgs) == 1 and "Research summary" in (tool_msgs[0].get("content") or ""))
        check("B1: parent history stays small (no subagent transcript)",
              len(sess.history) <= 4)  # user, assistant(delegate), tool, assistant(done)
        check("B2: orchestrator advertised delegate", "delegate" in seen.get("orchestrator", set()))


def test_team_parallel_stop_budget() -> None:
    """M17-B3/B5: dwa implementery edytują RÓŻNE pliki w równoległych worktree bez
    kolizji (realny workspace nietknięty); stop kaskaduje; budżet tur zatrzymuje."""
    from caelo_core.agent.team import MergeStore

    # --- równoległość + izolacja worktree ---
    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        (ws.root / "base.txt").write_text("base\n", encoding="utf-8")
        gate = PermissionGate()
        reg = _make_registry(d, {"max_parallel": 2})
        store = MergeStore(ws.root)

        def llm(api_key, base_url, messages, model, temperature, tools, on_text=None, stop_flag=None, **_):
            sys = messages[0]["content"]
            if "IMPLEMENTER subagent" in sys:
                task = _find_user(messages)
                fname = task.split("WRITEFILE:")[-1].strip()
                if _n_assist(messages) == 0:
                    return {"role": "assistant", "content": None, "tool_calls": [
                        {"id": "w", "type": "function", "function": {
                            "name": "write_file",
                            "arguments": json.dumps({"path": fname, "content": "from " + fname})}}]}
                return {"role": "assistant", "content": "wrote " + fname}
            return {"role": "assistant", "content": "done"}

        team, _ = _make_team(reg, ws, gate, llm, store=store)
        team.run([{"role": "implementer", "task": "WRITEFILE:a_out.txt"},
                  {"role": "implementer", "task": "WRITEFILE:b_out.txt"}],
                 model="mock", workspace=ws, mode="ask")

        merges = store.list()
        paths = sorted(p["path"] for m in merges for p in m["files"])
        check("B3: two worktrees produced two pending merges", len(merges) == 2)
        check("B3: each worktree isolated to its own file (no cross-writes)",
              paths == ["a_out.txt", "b_out.txt"])
        check("B3: real workspace untouched until merge",
              not (ws.root / "a_out.txt").exists() and not (ws.root / "b_out.txt").exists())
        check("B4: no conflict for disjoint files",
              all(m["conflicts"] == [] for m in merges))
        store.clear()

    # --- stop kaskadowy: stop orkiestratora cancel'uje subagentów ---
    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        gate = PermissionGate()
        reg = _make_registry(d)
        stopped = {"v": True}

        def llm_loop(api_key, base_url, messages, model, temperature, tools, on_text=None, stop_flag=None, **_):
            # researcher pętli się w nieskończoność (gdyby nie stop/budżet)
            return {"role": "assistant", "content": None, "tool_calls": [
                {"id": "r", "type": "function", "function": {
                    "name": "read_file", "arguments": '{"path":"nope.txt"}'}}]}

        team, _ = _make_team(reg, ws, gate, llm_loop, stop=lambda: stopped["v"])
        summary = team.run([{"role": "researcher", "task": "loop"}],
                           model="mock", workspace=ws, mode="ask")
        check("B3/B5: cascade stop cancels subagent before work",
              "cancelled" in summary)

    # --- budżet tur zatrzymuje pętlącego subagenta ---
    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        gate = PermissionGate()
        reg = _make_registry(d, {"max_total_turns": 2, "max_iters": 16})

        def llm_loop(api_key, base_url, messages, model, temperature, tools, on_text=None, stop_flag=None, **_):
            return {"role": "assistant", "content": None, "tool_calls": [
                {"id": "r", "type": "function", "function": {
                    "name": "read_file", "arguments": '{"path":"nope.txt"}'}}]}

        reports: list = []
        team, _ = _make_team(reg, ws, gate, llm_loop, reports=reports)
        team.run([{"role": "researcher", "task": "loop forever"}],
                 model="mock", workspace=ws, mode="ask")
        turns = reports[0]["totals"]["turns"] if reports else 999
        check("B5: budget caps total turns (< max_iters)", 0 < turns <= 3)


def test_team_merge() -> None:
    """M17-B4: compute_changes (jeden diff), apply (snapshot→checkpoint→aplikacja),
    reject (sandbox-safe), wykrycie konfliktu, undo scalenia przez M13."""
    from caelo_core.agent.checkpoints import CheckpointManager
    from caelo_core.agent.team import MergeStore
    from caelo_core.agent import worktree as WT

    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        (ws.root / "x.txt").write_text("orig x\n", encoding="utf-8")
        (ws.root / "keep.txt").write_text("keep\n", encoding="utf-8")

        # compute_changes: kopia worktree + modyfikacja + nowy + usunięty
        wt = Path(tempfile.mkdtemp()) / "wt"
        WT.copy_worktree(ws.root, wt)
        (wt / "x.txt").write_text("changed x\n", encoding="utf-8")  # modified
        (wt / "y.txt").write_text("new y\n", encoding="utf-8")      # created
        (wt / "keep.txt").unlink()                                  # deleted
        ch = WT.compute_changes(ws.root, wt)
        kinds = {f["path"]: f["kind"] for f in ch["files"]}
        check("B4: compute_changes detects modified/created/deleted",
              kinds.get("x.txt") == "modified" and kinds.get("y.txt") == "created"
              and kinds.get("keep.txt") == "deleted")
        check("B4: one combined diff covers the changes",
              "+changed x" in ch["diff"] and "+new y" in ch["diff"])

        # MergeStore: add A (x.txt,y.txt) + B (x.txt) → konflikt na x.txt
        store = MergeStore(ws.root)
        mA = store.add(agent_id="sa1", role="implementer", task="A",
                       worktree_dir=str(wt), files=ch["files"], diff=ch["diff"], created_at=0)
        wtB = Path(tempfile.mkdtemp()) / "wtB"
        WT.copy_worktree(ws.root, wtB)
        (wtB / "x.txt").write_text("B's x\n", encoding="utf-8")
        chB = WT.compute_changes(ws.root, wtB)
        mB = store.add(agent_id="sa2", role="implementer", task="B",
                       worktree_dir=str(wtB), files=chB["files"], diff=chB["diff"], created_at=0)
        listed = {m["id"]: m for m in store.list()}
        check("B4: conflict detected on overlapping path",
              "x.txt" in listed[mA.id]["conflicts"] and "x.txt" in listed[mB.id]["conflicts"])

        # apply A z checkpointem → aplikuje + cofalne
        cpm = CheckpointManager(ws.root)
        res = store.apply(mA.id, ws, checkpoints=cpm)
        check("B4: apply merges accepted changes",
              (ws.root / "x.txt").read_text(encoding="utf-8") == "changed x\n"
              and (ws.root / "y.txt").exists()
              and not (ws.root / "keep.txt").exists())
        check("B4: applied worktree discarded", not wt.exists())
        check("B4: apply summary lists applied/deleted",
              "x.txt" in res["applied"] and "keep.txt" in res["deleted"])
        check("B4: merge undoable via M13 checkpoint",
              cpm.undo_to() and (ws.root / "x.txt").read_text(encoding="utf-8") == "orig x\n"
              and (ws.root / "keep.txt").exists() and not (ws.root / "y.txt").exists())

        # reject B → sandbox-safe (workspace nietknięty, worktree wyrzucony)
        store.reject(mB.id)
        check("B4: reject discards worktree, workspace untouched",
              not wtB.exists() and (ws.root / "x.txt").read_text(encoding="utf-8") == "orig x\n")
        check("B4: store empty after apply+reject", store.list() == [])

    # sandbox scalania: ścieżka uciekająca poza workspace pomijana
    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        wt = Path(tempfile.mkdtemp()) / "wt"
        wt.mkdir(parents=True)
        (wt / "ok.txt").write_text("ok\n", encoding="utf-8")
        res = WT.apply_changes(ws, wt, [{"path": "ok.txt", "kind": "created"},
                                        {"path": "../escape.txt", "kind": "created"}])
        check("B4: merge sandbox skips path escaping workspace",
              "ok.txt" in res["applied"] and "../escape.txt" in res["skipped"]
              and not (Path(d).parent / "escape.txt").exists())


def test_team_cost() -> None:
    """M17-B6: agregacja kosztu/telemetrii po orkiestratorze + subagentach
    (tury, wywołania narzędzi, tokeny z usage), rozbicie per subagent."""
    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        gate = PermissionGate()
        reg = _make_registry(d)
        reports: list = []

        def llm(api_key, base_url, messages, model, temperature, tools, on_text=None, stop_flag=None, **_):
            sys = messages[0]["content"]
            if "RESEARCH subagent" in sys:
                if _n_assist(messages) == 0:
                    return {"role": "assistant", "content": None,
                            "usage": {"input_tokens": 10, "output_tokens": 5},
                            "tool_calls": [{"id": "r", "type": "function", "function": {
                                "name": "read_file", "arguments": '{"path":"nope.txt"}'}}]}
                return {"role": "assistant", "content": "found it",
                        "usage": {"input_tokens": 7, "output_tokens": 3}}
            return {"role": "assistant", "content": "done"}

        team, _ = _make_team(reg, ws, gate, llm, reports=reports)
        team.run([{"role": "researcher", "task": "investigate"}],
                 model="mock", workspace=ws, mode="ask")
        check("B6: team report recorded", bool(reports))
        rep = reports[0]
        sub = rep["subagents"][0]
        check("B6: per-subagent telemetry (turns + tool_calls)",
              sub["turns"] == 2 and sub["tool_calls"] == 1)
        check("B6: per-subagent tokens aggregated from usage",
              sub["input_tokens"] == 17 and sub["output_tokens"] == 8)
        check("B6: totals aggregate across subagents",
              rep["totals"]["input_tokens"] == 17 and rep["totals"]["tool_calls"] == 1
              and rep["totals"]["subagents"] == 1)


def test_permission_rules() -> None:
    """M19-B4: reguły glob (ToolPrefix), deny>allow, `*` vs `**`, oraz integracja w
    pętli agenta — deny blokuje też READONLY i tryb bypass; allow auto-akceptuje;
    P0-1 (metaznaki run_command) NIE jest obchodzone regułą allow."""
    from caelo_core.agent.permission_rules import RuleSet, parse_rule, _match_webfetch

    # --- jednostkowo: parser + dopasowanie ---
    check("B4: parse ToolPrefix(glob)", parse_rule("Bash(npm*)") == ("Bash", "npm*"))
    check("B4: bare prefix = match-all", parse_rule("Bash") == ("Bash", "**"))
    check("B4: invalid rule rejected", parse_rule("Nope(x)") is None and parse_rule("Bash(x") is None)
    check("B4: deny beats allow",
          RuleSet(allow=["Bash(**)"], deny=["Bash(rm*)"]).evaluate_tool(
              "run_command", {"command": "rm -rf x"}) == "deny")
    rs_star = RuleSet(deny=["Edit(src/*)"])
    check("B4: '*' stays within one path segment",
          rs_star.evaluate_tool("edit_file", {"path": "src/a.py"}) == "deny"
          and rs_star.evaluate_tool("edit_file", {"path": "src/a/b.py"}) is None)
    check("B4: '**' spans path segments",
          RuleSet(deny=["Edit(src/**)"]).evaluate_tool("edit_file", {"path": "src/a/b.py"}) == "deny")
    check("B4: write_file checks both Write and Edit",
          RuleSet(allow=["Write(out/**)"]).evaluate_tool("write_file", {"path": "out/x"}) == "allow"
          and RuleSet(allow=["Edit(out/**)"]).evaluate_tool("write_file", {"path": "out/x"}) == "allow")
    check("B4: MCPTool matches qualified name",
          RuleSet(deny=["MCPTool(gh__*)"]).evaluate_tool("gh__issue", {}, is_mcp=True) == "deny")
    check("B4: WebFetch domain + subdomain",
          _match_webfetch("domain:x.ai", "https://api.x.ai/v1")
          and _match_webfetch("domain:docs.rs", "https://docs.rs/foo")
          and not _match_webfetch("domain:evil.com", "https://x.ai"))
    check("B4: empty ruleset = no effect (pre-B4 behavior)",
          RuleSet().evaluate_tool("run_command", {"command": "rm -rf /"}) is None)

    # --- integracja w pętli agenta: jedno narzędzie -> done ---
    def _run_one_tool(ws, gate, tool_name, args, mode="ask"):
        events: list[dict] = []
        approvals = {"n": 0}
        calls = {"n": 0}

        def mock_llm(api_key, base_url, messages, model, temperature, tools, on_text=None, stop_flag=None, **_):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"role": "assistant", "content": None, "tool_calls": [
                    {"id": "c1", "type": "function",
                     "function": {"name": tool_name, "arguments": json.dumps(args)}}]}
            return {"role": "assistant", "content": "done"}

        def req(call_id, name, detail):
            approvals["n"] += 1
            return "accept"

        AgentSession(ws, gate, mock_llm, lambda: "k", "http://unused",
                     emit=events.append, request_approval=req).run_turn("go", model="mock", mode=mode)
        return events, approvals["n"]

    # deny blokuje narzędzie READONLY (read_file) — treść nie wraca do modelu
    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        (ws.root / "secret").mkdir()
        (ws.root / "secret" / "k.txt").write_text("TOPSECRET", encoding="utf-8")
        gate = PermissionGate()
        gate.set_rules(deny=["Read(secret/**)"])
        events, _ = _run_one_tool(ws, gate, "read_file", {"path": "secret/k.txt"})
        tr = [e for e in events if e.get("type") == "tool_result"]
        check("B4: deny blocks a READONLY read",
              bool(tr) and tr[0].get("ok") is False
              and tr[0].get("summary") == "Blocked by permission rule")
        check("B4: denied read leaks no file content",
              all("TOPSECRET" not in (e.get("summary") or "") for e in events))

        # P1-B: deny chroni TREŚĆ/NAZWY też przed narzędziami przeszukującymi (filtr na
        # WYNIKACH, nie tylko na argumencie). Bez fixu grep("TOPSECRET",".") zwracał linię
        # z secret/, a glob/list_dir — ścieżki/nazwy z deny-listowanego katalogu.
        gate.set_rules(deny=["Read(secret/**)"])
        events, _ = _run_one_tool(ws, gate, "grep", {"pattern": "TOPSECRET", "path": "."})
        check("P1-B: grep does not leak content from deny-listed path",
              all("TOPSECRET" not in (e.get("summary") or "") for e in events)
              and all("secret/k.txt" not in (e.get("summary") or "") for e in events))
        events, _ = _run_one_tool(ws, gate, "glob", {"pattern": "**/*"})
        check("P1-B: glob omits deny-listed result paths",
              all("secret/k.txt" not in (e.get("summary") or "") for e in events))
        # ukrycie samej NAZWY katalogu wymaga reguły Read(<dir>) (matcher segmentowy)
        gate.set_rules(deny=["Read(secret)", "Read(secret/**)"])
        events, _ = _run_one_tool(ws, gate, "list_dir", {"path": "."})
        check("P1-B: list_dir hides deny-listed entry name",
              all("secret" not in (e.get("summary") or "") for e in events))

    # allow auto-akceptuje write (bez dialogu zatwierdzenia)
    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        gate = PermissionGate()
        gate.set_rules(allow=["Write(out/**)"])
        events, n_appr = _run_one_tool(ws, gate, "write_file",
                                       {"path": "out/x.txt", "content": "hi"}, mode="ask")
        check("B4: allow auto-accepts write (no approval dialog)", n_appr == 0)
        check("B4: allowed write is applied",
              (ws.root / "out" / "x.txt").read_text(encoding="utf-8") == "hi")

    # deny ma pierwszeństwo nad trybem bypass (twardy zakaz)
    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        gate = PermissionGate()
        gate.set_rules(deny=["Edit(**)"])
        events, _ = _run_one_tool(ws, gate, "write_file",
                                  {"path": "a.txt", "content": "x"}, mode="bypass")
        check("B4: deny overrides bypass mode (write blocked)", not (ws.root / "a.txt").exists())
        tr = [e for e in events if e.get("type") == "tool_result"]
        check("B4: deny-in-bypass emits blocked result",
              bool(tr) and tr[0].get("summary") == "Blocked by permission rule")

    # P0-1: allow Bash(**) NIE może dopuścić komendy z metaznakami (łańcuchowanie)
    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        (ws.root / "victim.txt").write_text("alive", encoding="utf-8")
        gate = PermissionGate()
        gate.set_rules(allow=["Bash(**)"])
        cmd = "echo hi & del victim.txt" if os.name == "nt" else "echo hi && rm victim.txt"
        events, n_appr = _run_one_tool(ws, gate, "run_command", {"command": cmd})
        check("B4: allow does NOT bypass P0-1 (metachar cmd not executed)",
              (ws.root / "victim.txt").exists())
        tr = [e for e in events if e.get("type") == "tool_result"]
        check("B4: metachar cmd refused (ok=False), no approval dialog",
              bool(tr) and tr[0].get("ok") is False and n_appr == 0)


def test_orchestration_roles() -> None:
    """M19-B6: nowe role orkiestracji zarejestrowane; klasyfikacja READONLY vs worktree
    poprawna; `effective_tools` NIGDY nie eskaluje ponad narzędzia rodzica."""
    from caelo_core.agent.permissions import MUTATING
    from caelo_core.agent.roles import (
        ALL_FILE_TOOLS, RoleRegistry, effective_tools, role_is_mutating,
    )
    with tempfile.TemporaryDirectory() as d:
        reg = RoleRegistry(Path(d) / "subagents.json")
        ids = {r["id"] for r in reg.list()}
        check("B6: orchestration roles registered",
              {"design-doc-writer", "design-doc-reviewer",
               "security-auditor", "test-writer"} <= ids)

        for rid in ("design-doc-reviewer", "security-auditor"):
            r = reg.get(rid)
            check(f"B6: {rid} is read-only (no mutation, no worktree)",
                  r is not None and not role_is_mutating(r) and r["worktree"] is False
                  and not (set(r["tools"]) & MUTATING))

        for rid in ("design-doc-writer", "test-writer"):
            r = reg.get(rid)
            check(f"B6: {rid} mutates in an isolated worktree",
                  r is not None and role_is_mutating(r) and r["worktree"] is True)

        # Brak eskalacji: rola ∩ rodzic ⊆ rodzic; pod readonly-rodzicem writer traci write.
        writer = reg.get("design-doc-writer")
        ro_parent = {"read_file", "list_dir", "glob", "grep"}
        eff_ro = effective_tools(writer, ro_parent)
        check("B6: effective_tools never exceeds a read-only parent (no escalation)",
              set(eff_ro) <= ro_parent and "write_file" not in eff_ro)
        # Pod pełnym rodzicem writer zachowuje narzędzia mutujące.
        eff_full = effective_tools(writer, set(ALL_FILE_TOOLS))
        check("B6: writer keeps its write tools under a full parent",
              {"write_file", "edit_file"} <= set(eff_full))
        # test-writer: run_command tylko jeśli rodzic je ma.
        check("B6: test-writer run_command dropped when parent lacks it",
              "run_command" not in effective_tools(reg.get("test-writer"), ro_parent))


def test_memory_injection() -> None:
    """M19-B8: na 1. turze AgentSession wstrzykuje blok pamięci (mock memory) do system
    promptu; tylko raz na sesję; `memory=None` → brak bloku (zero regresji)."""
    class FakeMemory:
        def __init__(self) -> None:
            self.calls = 0

        def injected_text(self, query, project_id=None):
            self.calls += 1
            return ("--- Relevant memory ---\n- [chat] earlier you set up the parser"
                    if "parser" in (query or "") else "")

    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        gate = PermissionGate()
        seen: dict = {"systems": []}

        def mock_llm(api_key, base_url, messages, model, temperature, tools,
                     on_text=None, stop_flag=None):
            seen["systems"].append(messages[0]["content"])
            return {"role": "assistant", "content": "ok"}

        mem = FakeMemory()
        session = AgentSession(ws, gate, mock_llm, lambda: "k", "http://unused",
                               emit=lambda ev: None, request_approval=lambda *a: "accept",
                               memory=mem)
        session.run_turn("fix the parser bug", model="mock")
        check("B8: memory injected into system prompt on first turn",
              "Relevant memory" in seen["systems"][-1] and "parser" in seen["systems"][-1])

        session.run_turn("now run tests", model="mock")
        check("B8: memory recall happens once per session (first turn only)", mem.calls == 1)
        check("B8: cached memory block persists across later turns",
              "Relevant memory" in seen["systems"][-1])

        s2 = AgentSession(ws, gate, mock_llm, lambda: "k", "http://unused",
                          emit=lambda ev: None, request_approval=lambda *a: "accept")
        s2.run_turn("hello", model="mock")
        check("B8: no memory provider -> no memory block (no regression)",
              "Relevant memory" not in seen["systems"][-1])


def test_reasoning_effort() -> None:
    """M19-B9: reasoning_effort dochodzi do llm_fn (domyślny sesji + override per tura);
    brak/niepoprawny → brak kwargu (zero regresji); role mają poprawny effort + walidacja;
    payload chat/completions niesie pole tylko gdy poprawne."""
    import types as _types

    from caelo_core import validation as V
    from caelo_core.agent import llm as _llm
    from caelo_core.agent.roles import RoleRegistry, _clean_role

    check("B9: normalize_effort accepts valid (case-insensitive)",
          V.normalize_effort("HIGH") == "high" and V.normalize_effort("low") == "low")
    check("B9: normalize_effort rejects junk/empty/None",
          V.normalize_effort("turbo") is None and V.normalize_effort("") is None
          and V.normalize_effort(None) is None)

    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        gate = PermissionGate()
        seen: dict = {"effort": "MISSING"}

        def mock_llm(api_key, base_url, messages, model, temperature, tools,
                     on_text=None, stop_flag=None, **kw):
            seen["effort"] = kw.get("reasoning_effort", "MISSING")
            return {"role": "assistant", "content": "ok"}

        s = AgentSession(ws, gate, mock_llm, lambda: "k", "http://unused",
                         emit=lambda e: None, request_approval=lambda *a: "accept",
                         reasoning_effort="high")
        s.run_turn("hi", model="mock")
        check("B9: session default effort reaches llm_fn", seen["effort"] == "high")

        s.run_turn("again", model="mock", reasoning_effort="low")
        check("B9: per-turn effort overrides session default", seen["effort"] == "low")

        s.run_turn("again2", model="mock")
        check("B9: per-turn None keeps session default", seen["effort"] == "high")

        # Brak effortu → kwarg NIE jest przekazany (mock BEZ **kw również działa).
        ran = {"ok": False}

        def mock_strict(api_key, base_url, messages, model, temperature, tools,
                        on_text=None, stop_flag=None):
            ran["ok"] = True
            return {"role": "assistant", "content": "ok"}

        s2 = AgentSession(ws, gate, mock_strict, lambda: "k", "http://unused",
                          emit=lambda e: None, request_approval=lambda *a: "accept")
        s2.run_turn("no effort", model="mock")
        check("B9: no effort -> llm_fn called without reasoning_effort kwarg (no regression)",
              ran["ok"] is True)

    # Role: wartości wbudowane + walidacja user-roli.
    with tempfile.TemporaryDirectory() as d:
        reg = RoleRegistry(Path(d) / "subagents.json")
        researcher = reg.get("researcher")
        tester = reg.get("tester")
        check("B9: builtin roles carry reasoning_effort",
              researcher and researcher.get("reasoning_effort") == "high"
              and tester and tester.get("reasoning_effort") == "low")
        check("B9: _clean_role drops invalid effort to ''",
              _clean_role({"id": "x", "reasoning_effort": "TURBO"})["reasoning_effort"] == "")
        check("B9: _clean_role normalizes valid effort",
              _clean_role({"id": "y", "reasoning_effort": "Medium"})["reasoning_effort"] == "medium")

    # llm.py: payload chat/completions niesie reasoning_effort tylko gdy poprawne.
    captured: dict = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def raise_for_status(self):
            pass

        def iter_lines(self, decode_unicode=False):
            return iter([b'data: {"choices":[{"delta":{"content":"hi"}}]}', b"data: [DONE]"])

    def _post(url, **kw):
        captured["json"] = kw.get("json")
        return _Resp()

    orig = _llm.requests
    _llm.requests = _types.SimpleNamespace(post=_post, get=getattr(orig, "get", None))
    try:
        _llm.stream_chat_with_tools("k", "http://x", [{"role": "user", "content": "hi"}],
                                    "grok", 0.2, [], reasoning_effort="high")
        with_eff = (captured.get("json") or {}).get("reasoning_effort")
        _llm.stream_chat_with_tools("k", "http://x", [{"role": "user", "content": "hi"}],
                                    "grok", 0.2, [], reasoning_effort="bogus")
        omitted = "reasoning_effort" not in (captured.get("json") or {})
    finally:
        _llm.requests = orig
    check("B9: llm payload carries valid reasoning_effort", with_eff == "high")
    check("B9: llm payload omits invalid reasoning_effort", omitted)

    # M19-B9 fix: reasoning_effort jest ZALEŻNY OD MODELU — grok-4 / grok-build-0.1 zwracają 4xx,
    # gdy pole jest obecne. Agent PONAWIA wtedy raz BEZ niego (best-effort: tura nie pada).
    fb_calls: list = []

    class _RespFb:
        def __init__(self, status, lines=()):
            self.status_code = status
            self._lines = list(lines)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def raise_for_status(self):
            if self.status_code >= 400:
                raise orig.HTTPError(str(self.status_code))

        def iter_lines(self, decode_unicode=False):
            return iter(self._lines)

        def close(self):
            pass

    def _post_fb(url, **kw):
        has_eff = "reasoning_effort" in (kw.get("json") or {})
        fb_calls.append(has_eff)
        if has_eff:
            return _RespFb(400)  # model (np. grok-build-0.1) odrzuca reasoning_effort
        return _RespFb(200, [b'data: {"choices":[{"delta":{"content":"hi"}}]}', b"data: [DONE]"])

    _llm.requests = _types.SimpleNamespace(post=_post_fb, get=getattr(orig, "get", None),
                                           HTTPError=orig.HTTPError)
    try:
        msg = _llm.stream_chat_with_tools("k", "http://x", [{"role": "user", "content": "hi"}],
                                          "grok-build-0.1", 0.2, [], reasoning_effort="high")
    finally:
        _llm.requests = orig
    check("B9: reasoning_effort 4xx -> retry WITHOUT it (turn survives unsupported model)",
          msg.get("content") == "hi" and fb_calls == [True, False])


def test_persona_io() -> None:
    """M19-B11: persona (instructions) + kontrakt I/O (inputs/outputs) — walidacja,
    fallback prompt→instructions, złożenie system promptu, normalizacja builtinów,
    round-trip user roli przez rejestr."""
    from caelo_core.agent.roles import (
        RoleRegistry, _clean_role, role_io_contract, role_persona, role_system_prompt,
    )

    cleaned = _clean_role({
        "id": "x", "instructions": "Be precise.",
        "inputs": [{"name": "spec", "io_type": "file", "required": True, "description": "d"},
                   {"description": "no name -> dropped"}],
        "outputs": [{"name": "report", "io_type": "weird"}],
    })
    check("B11: _clean_role keeps instructions", cleaned["instructions"] == "Be precise.")
    check("B11: _clean_role drops I/O field without name + normalizes io_type/required",
          len(cleaned["inputs"]) == 1 and cleaned["inputs"][0]["name"] == "spec"
          and cleaned["outputs"][0]["io_type"] == "text"
          and cleaned["outputs"][0]["required"] is False)

    check("B11: persona prefers instructions over prompt",
          role_persona({"instructions": "I", "prompt": "P"}) == "I")
    check("B11: persona falls back to prompt (legacy M17 roles)",
          role_persona({"prompt": "P"}) == "P")

    contract = role_io_contract(cleaned)
    check("B11: I/O contract mentions inputs + outputs",
          "Inputs you may be given" in contract and "Outputs to produce" in contract
          and "spec" in contract and "report" in contract)
    sysp = role_system_prompt(cleaned)
    check("B11: system prompt = persona + contract",
          sysp.startswith("Be precise.") and "Outputs to produce" in sysp)
    check("B11: role with neither persona nor I/O -> empty system prompt",
          role_system_prompt({}) == "")

    with tempfile.TemporaryDirectory() as d:
        reg = RoleRegistry(Path(d) / "subagents.json")
        rev = reg.get("reviewer")
        check("B11: builtin role normalized (inputs/outputs/instructions keys present)",
              isinstance(rev.get("inputs"), list) and isinstance(rev.get("outputs"), list)
              and "instructions" in rev)
        check("B11: reviewer declares findings + verdict outputs",
              {o["name"] for o in rev["outputs"]} >= {"findings", "verdict"})
        check("B11: builtin reviewer system prompt includes its I/O contract",
              "Outputs to produce" in role_system_prompt(rev))

        reg.upsert_role({"id": "io-role", "instructions": "Do X",
                         "outputs": [{"name": "result", "required": True}]})
        got = reg.get("io-role")
        check("B11: user role round-trips instructions + outputs",
              got["instructions"] == "Do X" and got["outputs"][0]["name"] == "result"
              and got["outputs"][0]["required"] is True)


def test_autocompact() -> None:
    """M19-B10: compact_history zwija najstarsze tury (balans tool_call↔tool zachowany);
    off / pod progiem = bez zmian; AgentSession kompaktuje gdy AGENT_AUTOCOMPACT + próg."""
    import config as CFG
    from caelo_core.agent.session import (
        AgentSession, COMPACT_SUMMARY_HEADER, _history_chars, compact_history,
    )

    def turn(q, a, tool=False):
        msgs = [{"role": "user", "content": q}]
        if tool:
            msgs.append({"role": "assistant", "content": "", "tool_calls": [
                {"id": "t", "type": "function",
                 "function": {"name": "read_file", "arguments": "{}"}}]})
            msgs.append({"role": "tool", "tool_call_id": "t", "content": "R" * 400})
        msgs.append({"role": "assistant", "content": a})
        return msgs

    big = (turn("q1 " + "x" * 400, "a1 " + "y" * 400, tool=True)
           + turn("q2 " + "x" * 400, "a2 " + "y" * 400, tool=True)
           + turn("q3 latest", "a3 latest"))

    def balanced(h):
        for i, m in enumerate(h):
            if m.get("role") == "assistant" and m.get("tool_calls"):
                k = len(m["tool_calls"])
                if any(i + j >= len(h) or h[i + j].get("role") != "tool"
                       for j in range(1, k + 1)):
                    return False
        return True

    out = compact_history(big, threshold_chars=300)
    check("B10: compaction shrinks history over threshold", len(out) < len(big))
    check("B10: first message is the summary block",
          out[0].get("role") == "user" and COMPACT_SUMMARY_HEADER in (out[0].get("content") or ""))
    check("B10: compacted history stays balanced (no split tool pairs)", balanced(out))
    check("B10: total size not increased", _history_chars(out) <= _history_chars(big))
    check("B10: current (last) turn preserved verbatim", out[-1] == big[-1])
    check("B10: threshold 0 = no change (off)", compact_history(big, threshold_chars=0) is big)
    small = turn("only", "one")
    check("B10: under threshold = unchanged",
          compact_history(small, threshold_chars=100000) is small)

    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        gate = PermissionGate()

        def mock_llm(api_key, base_url, messages, model, temperature, tools,
                     on_text=None, stop_flag=None, **_):
            return {"role": "assistant", "content": "ok"}

        prev_on, prev_th = CFG.AGENT_AUTOCOMPACT, CFG.AGENT_COMPACT_THRESHOLD_CHARS
        CFG.AGENT_AUTOCOMPACT = True
        CFG.AGENT_COMPACT_THRESHOLD_CHARS = 300
        try:
            s = AgentSession(ws, gate, mock_llm, lambda: "k", "http://unused",
                             emit=lambda e: None, request_approval=lambda *a: "accept")
            s.history = list(big)
            s.run_turn("new question", model="mock")
            joined = "\n".join(str(m.get("content") or "") for m in s.history)
            check("B10: AgentSession compacts when enabled + over threshold",
                  COMPACT_SUMMARY_HEADER in joined and len(s.history) < len(big))
        finally:
            CFG.AGENT_AUTOCOMPACT, CFG.AGENT_COMPACT_THRESHOLD_CHARS = prev_on, prev_th

        CFG.AGENT_AUTOCOMPACT = False
        s2 = AgentSession(ws, gate, mock_llm, lambda: "k", "http://unused",
                          emit=lambda e: None, request_approval=lambda *a: "accept")
        s2.history = list(big)
        s2.run_turn("another", model="mock")
        joined2 = "\n".join(str(m.get("content") or "") for m in s2.history)
        check("B10: no compaction when disabled (off = no change)",
              COMPACT_SUMMARY_HEADER not in joined2)


def test_git_worktree() -> None:
    """M19-B12: realny git worktree jako OPCJA obok kopii — fallback do kopii poza repo,
    kształt zwrotu compute_changes identyczny dla obu wariantów, discard sprząta. Ścieżka
    git pod guardem: brak gita w środowisku → testuje tylko kopię/fallback (bez fail)."""
    import shutil as _sh
    import subprocess as _sp

    from caelo_core.agent import worktree as WT

    # 1) fallback: use_git=True, ale katalog NIE jest repo → wariant "copy"
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "ws"
        src.mkdir()
        (src / "a.txt").write_text("hello\n", encoding="utf-8")
        dest = Path(d) / "wt"
        kind = WT.create_worktree(src, dest, use_git=True)
        check("B12: non-repo + use_git falls back to copy", kind == "copy" and dest.exists())
        check("B12: copy worktree mirrors files",
              (dest / "a.txt").read_text(encoding="utf-8") == "hello\n")
        (dest / "a.txt").write_text("hello world\n", encoding="utf-8")
        (dest / "b.txt").write_text("new\n", encoding="utf-8")
        ch = WT.compute_changes(src, dest, kind="copy")
        kinds = {f["path"]: f["kind"] for f in ch["files"]}
        check("B12: copy compute_changes shape + kinds",
              set(ch.keys()) == {"files", "diff", "paths"}
              and kinds.get("a.txt") == "modified" and kinds.get("b.txt") == "created")
        WT.discard_worktree(dest, kind="copy")
        check("B12: copy discard removes dir", not dest.exists())

    if _sh.which("git") is None:
        check("B12: git unavailable -> git path skipped (note)", True)
        return

    # 2) wariant git na realnym repo
    with tempfile.TemporaryDirectory() as d:
        repo = Path(d) / "repo"
        repo.mkdir()

        def g(*args):
            return _sp.run(["git", *args], cwd=str(repo), env=T.scrubbed_env(),
                           stdout=_sp.PIPE, stderr=_sp.PIPE, text=True)

        g("init", "-q")
        g("config", "user.email", "t@example.com")
        g("config", "user.name", "Test")
        (repo / "keep.txt").write_text("keep\n", encoding="utf-8")
        (repo / "mod.txt").write_text("original\n", encoding="utf-8")
        (repo / "del.txt").write_text("bye\n", encoding="utf-8")
        g("add", "-A")
        g("commit", "-q", "-m", "init")

        check("B12: is_git_repo true for repo top-level", WT.is_git_repo(repo))
        check("B12: is_git_repo false for plain dir", not WT.is_git_repo(Path(d)))

        dest = Path(d) / "gwt"
        kind = WT.create_worktree(repo, dest, use_git=True)
        check("B12: repo + use_git creates a git worktree",
              kind == "git" and dest.exists() and (dest / "keep.txt").exists())

        (dest / "mod.txt").write_text("changed\n", encoding="utf-8")
        (dest / "new.txt").write_text("brand new\n", encoding="utf-8")
        (dest / "del.txt").unlink()

        ch = WT.compute_changes(repo, dest, kind="git")
        kinds = {f["path"]: f["kind"] for f in ch["files"]}
        check("B12: git compute_changes shape identical to copy",
              set(ch.keys()) == {"files", "diff", "paths"})
        check("B12: git detects modified/created/deleted",
              kinds.get("mod.txt") == "modified" and kinds.get("new.txt") == "created"
              and kinds.get("del.txt") == "deleted")
        check("B12: git ignores unchanged files", "keep.txt" not in kinds)
        check("B12: git diff text present", "changed" in ch["diff"] or "brand new" in ch["diff"])

        ws = Workspace(str(repo))
        WT.apply_changes(ws, dest, ch["files"])
        check("B12: apply writes modified/created back to workspace",
              (repo / "mod.txt").read_text(encoding="utf-8") == "changed\n"
              and (repo / "new.txt").read_text(encoding="utf-8") == "brand new\n")
        check("B12: apply deletes removed file", not (repo / "del.txt").exists())

        before_n = len(g("worktree", "list").stdout.splitlines())
        WT.discard_worktree(dest, kind="git", src_root=str(repo))
        after_n = len(g("worktree", "list").stdout.splitlines())
        check("B12: git discard removes worktree (dir gone + admin record pruned)",
              not dest.exists() and after_n == 1 and after_n < before_n)


def test_web_fetch() -> None:
    """M19-B13: web_fetch — https-only, SSRF-guard, twarda allowlista, cap, HTML→text,
    re-walidacja redirectu, generyczny błąd; gating (MUTATING + reguły WebFetch + klucz
    per-host); advertowanie warunkowe (ukryte gdy off / dla subagenta)."""
    import types as _types

    import config as CFG
    from caelo_core.agent.permission_rules import RuleSet, targets_for_tool
    from caelo_core.agent.permissions import MUTATING, PermissionGate

    class _Resp:
        def __init__(self, body=b"x", ctype="text/html", url=""):
            self._body = body
            self.headers = {"content-type": ctype}
            self.url = url

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size=8192):
            for i in range(0, len(self._body), chunk_size):
                yield self._body[i:i + chunk_size]

    def _getter(resp_factory):
        def _get(u, **kw):
            return resp_factory(u)
        return _get

    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        orig_req = T.requests
        orig_gai = T.socket.getaddrinfo
        try:
            T.requests = _types.SimpleNamespace(
                get=_getter(lambda u: _Resp(b"<html><body>Hello <b>World</b></body></html>",
                                            "text/html; charset=utf-8", u)))
            # 3.3-g: rozwiązywanie hosta jest teraz częścią guardu — stubuj na PUBLICZNY IP,
            # by test był deterministyczny (host literalny prywatny/loopback i tak odpada
            # wcześniej w _web_host_blocked, przed getaddrinfo).
            T.socket.getaddrinfo = lambda host, *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))]
            out = T.web_fetch(ws, url="https://example.com/page")
            check("B13: web_fetch reduces HTML to text",
                  "Hello World" in out and "<b>" not in out)
            check("B13: web_fetch rejects non-https",
                  T.web_fetch(ws, url="http://example.com").startswith("Error"))
            check("B13: web_fetch refuses loopback",
                  "refused" in T.web_fetch(ws, url="https://127.0.0.1/x"))
            check("B13: web_fetch refuses localhost",
                  "refused" in T.web_fetch(ws, url="https://localhost/x"))
            check("B13: web_fetch refuses private IP",
                  "refused" in T.web_fetch(ws, url="https://10.0.0.5/x"))

            prev = CFG.WEB_FETCH_ALLOW_DOMAINS
            CFG.WEB_FETCH_ALLOW_DOMAINS = ["example.com"]
            try:
                check("B13: allowlist permits listed host (subdomain)",
                      "Hello World" in T.web_fetch(ws, url="https://docs.example.com/a"))
                check("B13: allowlist blocks unlisted host",
                      "allowlist" in T.web_fetch(ws, url="https://evil.org/a"))
            finally:
                CFG.WEB_FETCH_ALLOW_DOMAINS = prev

            T.requests = _types.SimpleNamespace(
                get=_getter(lambda u: _Resp(b"x", "text/plain", "https://169.254.169.254/meta")))
            check("B13: web_fetch refuses redirect to blocked host",
                  "redirect" in T.web_fetch(ws, url="https://example.com/r"))

            prev_cap = CFG.WEB_FETCH_MAX_BYTES
            CFG.WEB_FETCH_MAX_BYTES = 50
            try:
                T.requests = _types.SimpleNamespace(
                    get=_getter(lambda u: _Resp(b"A" * 500, "text/plain", u)))
                out = T.web_fetch(ws, url="https://example.com/big")
                check("B13: web_fetch caps size + truncation note",
                      "truncated" in out and len(out) < 200)
            finally:
                CFG.WEB_FETCH_MAX_BYTES = prev_cap

            def _boom(u, **kw):
                raise RuntimeError("connect 10.1.2.3:443 failed SECRET-DETAIL")

            T.requests = _types.SimpleNamespace(get=_boom)
            err = T.web_fetch(ws, url="https://example.com/e")
            check("B13: web_fetch network error is generic (no leak)",
                  err.startswith("Error: web_fetch failed") and "SECRET-DETAIL" not in err)
        finally:
            T.requests = orig_req
            T.socket.getaddrinfo = orig_gai

    # --- gating + reguły ---
    check("B13: web_fetch is gated (MUTATING, not READONLY)", "web_fetch" in MUTATING)
    gate = PermissionGate()
    check("B13: web_fetch needs approval by default",
          gate.needs_approval("web_fetch", {"url": "https://example.com/x"}))
    rs = RuleSet(allow=["WebFetch(domain:example.com)"], deny=["WebFetch(domain:evil.org)"])
    check("B13: WebFetch allow rule matches host (subdomain)",
          rs.evaluate_tool("web_fetch", {"url": "https://docs.example.com/x"}) == "allow")
    check("B13: WebFetch deny rule matches host",
          rs.evaluate_tool("web_fetch", {"url": "https://evil.org/x"}) == "deny")
    check("B13: targets_for_tool maps web_fetch -> WebFetch(url)",
          targets_for_tool("web_fetch", {"url": "https://h/x"}) == [("WebFetch", "https://h/x")])
    g2 = PermissionGate()
    g2.allow("web_fetch", {"url": "https://example.com/a"})
    check("B13: Always-allow web_fetch is per-host",
          not g2.needs_approval("web_fetch", {"url": "https://example.com/other"})
          and g2.needs_approval("web_fetch", {"url": "https://evil.org/x"}))

    # --- advertowanie warunkowe ---
    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        g3 = PermissionGate()

        def mock_llm(api_key, base_url, messages, model, temperature, tools,
                     on_text=None, stop_flag=None, **_):
            return {"role": "assistant", "content": "ok"}

        prev_en = CFG.WEB_FETCH_ENABLED
        try:
            CFG.WEB_FETCH_ENABLED = False
            off = AgentSession(ws, g3, mock_llm, lambda: "k", "http://unused",
                               emit=lambda e: None, request_approval=lambda *a: "accept")
            check("B13: web_fetch hidden when disabled",
                  "web_fetch" not in {t["function"]["name"] for t in off._all_tools()})
            CFG.WEB_FETCH_ENABLED = True
            on = AgentSession(ws, g3, mock_llm, lambda: "k", "http://unused",
                              emit=lambda e: None, request_approval=lambda *a: "accept")
            check("B13: web_fetch advertised when enabled (main agent)",
                  "web_fetch" in {t["function"]["name"] for t in on._all_tools()})
            sub = AgentSession(ws, g3, mock_llm, lambda: "k", "http://unused",
                               emit=lambda e: None, request_approval=lambda *a: "accept",
                               tool_names={"read_file"})
            check("B13: web_fetch not advertised to a scoped subagent",
                  "web_fetch" not in {t["function"]["name"] for t in sub._all_tools()})
        finally:
            CFG.WEB_FETCH_ENABLED = prev_en


def test_web_search() -> None:
    """Faza-G/TOP1: web_search — READONLY live search reużywające responses_client.
    Sprawdza format wyniku (synteza + Sources), pusty query→Error, generyczny błąd,
    advertowanie warunkowe (off / orkiestrator / subagent), brak bramki w pętli oraz że
    narzędzie NIE jest w MUTATING/READONLY (własna ścieżka, jak delegate)."""
    import config as CFG
    from caelo_core import responses_client as RC
    from caelo_core.agent.permissions import MUTATING, READONLY, PermissionGate

    # --- egzekutor: stub stream_response (bez sieci) ---
    orig_stream = RC.stream_response
    captured: dict = {}
    try:
        def _fake_stream(messages, *, model, api_key_provider, tools=None, **kw):
            captured["model"] = model
            captured["tools"] = tools
            captured["key"] = api_key_provider()
            return {"text": "Grok 4.3 shipped in 2026.",
                    "citations": [{"url": "https://x.ai/blog", "title": "xAI Blog"},
                                  {"url": "https://docs.x.ai", "title": ""}]}
        RC.stream_response = _fake_stream
        out = T.web_search("when did grok 4.3 ship", api_key_provider=lambda: "k",
                           model="grok-4.3")
        check("TOP1: web_search returns synthesized text",
              "Grok 4.3 shipped in 2026." in out)
        check("TOP1: web_search appends cited Sources",
              "Sources:" in out and "https://x.ai/blog" in out and "xAI Blog" in out)
        check("TOP1: web_search reuses live-search tools (web + x)",
              {"type": "web_search"} in (captured.get("tools") or [])
              and {"type": "x_search"} in (captured.get("tools") or []))
        check("TOP1: web_search uses the given model + auth provider",
              captured.get("model") == "grok-4.3" and captured.get("key") == "k")
        check("TOP1: web_search rejects an empty query",
              T.web_search("   ", api_key_provider=lambda: "k").startswith("Error"))

        def _boom(*a, **k):
            raise RuntimeError("api.x.ai 500 SECRET-DETAIL")
        RC.stream_response = _boom
        err = T.web_search("q", api_key_provider=lambda: "k")
        check("TOP1: web_search error is generic (no leak)",
              err.startswith("Error: web_search failed") and "SECRET-DETAIL" not in err)
    finally:
        RC.stream_response = orig_stream

    # --- klasyfikacja: bez bramki, własna ścieżka (jak delegate; poza zbiorami plikowymi) ---
    check("TOP1: web_search is not gated (not in MUTATING)", "web_search" not in MUTATING)
    check("TOP1: web_search stays out of READONLY (no ALL_FILE_TOOLS bloat)",
          "web_search" not in READONLY)

    def mock_llm(api_key, base_url, messages, model, temperature, tools,
                 on_text=None, stop_flag=None, **_):
        return {"role": "assistant", "content": "ok"}

    prev_en = CFG.WEB_SEARCH_ENABLED
    try:
        # --- advertowanie warunkowe ---
        with tempfile.TemporaryDirectory() as d:
            ws = Workspace(d)
            g = PermissionGate()
            CFG.WEB_SEARCH_ENABLED = False
            off = AgentSession(ws, g, mock_llm, lambda: "k", "http://unused",
                               emit=lambda e: None, request_approval=lambda *a: "accept")
            check("TOP1: web_search hidden when disabled",
                  "web_search" not in {t["function"]["name"] for t in off._all_tools()})
            CFG.WEB_SEARCH_ENABLED = True
            on = AgentSession(ws, g, mock_llm, lambda: "k", "http://unused",
                              emit=lambda e: None, request_approval=lambda *a: "accept")
            check("TOP1: web_search advertised when enabled (main agent)",
                  "web_search" in {t["function"]["name"] for t in on._all_tools()})
            sub = AgentSession(ws, g, mock_llm, lambda: "k", "http://unused",
                               emit=lambda e: None, request_approval=lambda *a: "accept",
                               tool_names={"read_file"})
            check("TOP1: web_search not advertised to a scoped subagent",
                  "web_search" not in {t["function"]["name"] for t in sub._all_tools()})

        # --- w pętli: READONLY (żadnego approval), cytowania wracają do modelu ---
        with tempfile.TemporaryDirectory() as d:
            ws = Workspace(d)
            g = PermissionGate()
            CFG.WEB_SEARCH_ENABLED = True
            orig_stream2 = RC.stream_response
            approvals: list = []
            results: list = []
            try:
                RC.stream_response = lambda messages, **kw: {
                    "text": "answer", "citations": [{"url": "https://a.b", "title": "T"}]}
                calls = {"n": 0}

                def llm(api_key, base_url, messages, model, temperature, tools,
                        on_text=None, stop_flag=None, **_):
                    calls["n"] += 1
                    if calls["n"] == 1:
                        return {"role": "assistant", "content": "",
                                "tool_calls": [{"id": "c1", "type": "function",
                                                "function": {"name": "web_search",
                                                             "arguments": json.dumps({"query": "x"})}}]}
                    return {"role": "assistant", "content": "done"}

                def emit(ev):
                    if ev.get("type") == "tool_result" and ev.get("id") == "c1":
                        results.append(ev)

                def request_approval(call_id, name, detail):
                    approvals.append(name)
                    return "accept"

                sess = AgentSession(ws, g, llm, lambda: "k", "http://unused",
                                    emit=emit, request_approval=request_approval)
                sess.run_turn("search please", "grok-4.3")
                check("TOP1: web_search runs READONLY in the loop (no approval asked)",
                      not approvals and bool(results) and results[0]["ok"])
                check("TOP1: web_search result carries citations back to the model",
                      any("Sources:" in (r.get("summary") or "") for r in results))
            finally:
                RC.stream_response = orig_stream2
    finally:
        CFG.WEB_SEARCH_ENABLED = prev_en


def test_plan_widget() -> None:
    """Faza-G/TOP3: update_plan — live checklist (jak TodoWrite). Sprawdza normalize_plan
    (warianty/cap/zły status), plan_summary, ramkę `plan` w pętli (READONLY, bez approval),
    advertowanie orkiestratorowi / ukrycie przed subagentem, balans historii."""
    from caelo_core.agent.permissions import MUTATING, READONLY, PermissionGate

    # --- normalize_plan (pure) ---
    norm = T.normalize_plan([
        {"step": "Read code", "status": "completed"},
        {"content": "Edit file", "status": "in_progress"},
        "Run tests",                              # goły string -> pending
        {"step": "   ", "status": "pending"},     # pusty -> pomiń
        {"step": "Bad status", "status": "wat"},  # zły status -> pending
        123,                                      # nie-obiekt -> pomiń
    ])
    check("TOP3: normalize_plan maps step/content + clamps statuses",
          norm == [{"content": "Read code", "status": "completed"},
                   {"content": "Edit file", "status": "in_progress"},
                   {"content": "Run tests", "status": "pending"},
                   {"content": "Bad status", "status": "pending"}])
    check("TOP3: normalize_plan caps step count",
          len(T.normalize_plan([{"step": f"s{i}"} for i in range(100)])) == T.PLAN_MAX_STEPS)
    check("TOP3: normalize_plan tolerates non-list input", T.normalize_plan(None) == [])
    check("TOP3: plan_summary counts done/active",
          "2 step(s)" in T.plan_summary([{"content": "a", "status": "completed"},
                                         {"content": "b", "status": "in_progress"}])
          and "1 done" in T.plan_summary([{"content": "a", "status": "completed"}]))

    # --- klasyfikacja: meta, bez bramki (poza MUTATING/READONLY, jak delegate) ---
    check("TOP3: update_plan is not gated (not in MUTATING)", "update_plan" not in MUTATING)
    check("TOP3: update_plan stays out of READONLY set", "update_plan" not in READONLY)

    def mock_llm(api_key, base_url, messages, model, temperature, tools,
                 on_text=None, stop_flag=None, **_):
        return {"role": "assistant", "content": "ok"}

    # --- advertowanie warunkowe ---
    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        g = PermissionGate()
        main = AgentSession(ws, g, mock_llm, lambda: "k", "http://unused",
                            emit=lambda e: None, request_approval=lambda *a: "accept")
        check("TOP3: update_plan advertised to the main agent",
              "update_plan" in {t["function"]["name"] for t in main._all_tools()})
        sub = AgentSession(ws, g, mock_llm, lambda: "k", "http://unused",
                           emit=lambda e: None, request_approval=lambda *a: "accept",
                           tool_names={"read_file"})
        check("TOP3: update_plan not advertised to a scoped subagent",
              "update_plan" not in {t["function"]["name"] for t in sub._all_tools()})

    # --- w pętli: emituje ramkę `plan`, READONLY (bez approval), historia zbalansowana ---
    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        g = PermissionGate()
        approvals: list = []
        plan_frames: list = []
        calls = {"n": 0}

        def llm(api_key, base_url, messages, model, temperature, tools,
                on_text=None, stop_flag=None, **_):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"role": "assistant", "content": "",
                        "tool_calls": [{"id": "p1", "type": "function",
                                        "function": {"name": "update_plan",
                                                     "arguments": json.dumps({"steps": [
                                                         {"step": "Investigate", "status": "in_progress"},
                                                         {"step": "Fix", "status": "pending"}]})}}]}
            return {"role": "assistant", "content": "done"}

        def emit(ev):
            if ev.get("type") == "plan":
                plan_frames.append(ev)

        def request_approval(call_id, name, detail):
            approvals.append(name)
            return "accept"

        sess = AgentSession(ws, g, llm, lambda: "k", "http://unused",
                            emit=emit, request_approval=request_approval)
        sess.run_turn("do a task", "grok-4.3")
        check("TOP3: update_plan emits a `plan` frame with normalized items",
              bool(plan_frames) and plan_frames[0]["items"] == [
                  {"content": "Investigate", "status": "in_progress"},
                  {"content": "Fix", "status": "pending"}])
        check("TOP3: update_plan runs READONLY in the loop (no approval asked)", not approvals)
        tool_msgs = [m for m in sess.history if m.get("role") == "tool"]
        check("TOP3: update_plan tool result recorded (balanced history)",
              any("Plan updated" in (m.get("content") or "") for m in tool_msgs))


def test_project_config() -> None:
    """M19-B14: hierarchiczny config cwd→root — find_project_root (.git walk),
    project_dir_chain (deeper-wins), dziedziczenie CAELO.md i `.caelo/{permissions,lsp}.json`
    z przodków (monorepo); pojedynczy root = zachowanie sprzed B14."""
    from caelo_core.agent.caelomd import load_caelo_md
    from caelo_core.agent.project import find_project_root, project_dir_chain

    with tempfile.TemporaryDirectory() as d:
        repo = Path(d) / "repo"
        mid = repo / "pkg"
        ws = mid / "app"
        ws.mkdir(parents=True)
        (repo / ".git").mkdir()  # symuluj korzeń repo

        check("B14: find_project_root finds .git ancestor",
              find_project_root(ws) == repo.resolve())
        plain = Path(d) / "plain"
        plain.mkdir()
        check("B14: find_project_root returns start when no repo",
              find_project_root(plain) == plain.resolve())

        check("B14: project_dir_chain is root->ws (shallowest first)",
              project_dir_chain(ws) == [repo.resolve(), mid.resolve(), ws.resolve()])
        check("B14: chain for repo-root is just itself",
              project_dir_chain(repo) == [repo.resolve()])
        check("B14: chain for non-repo dir is just itself",
              project_dir_chain(plain) == [plain.resolve()])

        # CAELO.md: przodek + workspace (deeper = workspace, ostatni)
        (repo / "CAELO.md").write_text("Repo-wide rule: use tabs.", encoding="utf-8")
        (ws / "CAELO.md").write_text("App rule: 100 char lines.", encoding="utf-8")
        md = load_caelo_md(ws, None)
        check("B14: CAELO.md inherits ancestor + workspace",
              "Repo-wide rule" in md and "App rule" in md)
        check("B14: workspace CAELO.md is the deepest (labeled workspace, ancestor labeled)",
              "## Workspace project rules" in md and "ancestor: repo" in md)

        # Backend.__new__ (bez I/O) do testu discovery permissions + lsp
        from caelo_core.state import Backend
        (repo / ".caelo").mkdir()
        (repo / ".caelo" / "permissions.json").write_text('{"allow": ["Read(src/**)"]}',
                                                          encoding="utf-8")
        (ws / ".caelo").mkdir()
        (ws / ".caelo" / "permissions.json").write_text('{"deny": ["Bash(rm*)"]}',
                                                        encoding="utf-8")
        b = Backend.__new__(Backend)
        b.permissions = PermissionGate()
        b.read_settings = lambda: {}
        b._workspace = Workspace(str(ws))
        b.reload_permission_rules()
        rs = b.permissions.rule_strings()
        check("B14: permission rules inherit ancestor allow + workspace deny",
              "Read(src/**)" in rs["allow"] and "Bash(rm*)" in rs["deny"])

        # .caelo/lsp.json: przodek + workspace (deeper wygrywa per nazwa serwera)
        (repo / ".caelo" / "lsp.json").write_text(
            '{"py": {"command": "ancestor-ls"}, "rs": {"command": "rust-ls"}}', encoding="utf-8")
        (ws / ".caelo" / "lsp.json").write_text('{"py": {"command": "ws-pyright"}}',
                                               encoding="utf-8")
        cfg = b._discover_lsp_configs(Workspace(str(ws)).root)
        check("B14: lsp config inherits ancestor + workspace (deeper wins per server)",
              cfg.get("rs", {}).get("command") == "rust-ls"
              and cfg.get("py", {}).get("command") == "ws-pyright")


def test_worktree_path_isolation() -> None:
    """3.3-b: dwa równoległe TeamManagery na WSPÓLNEJ bazie worktree dostają rozłączne
    ścieżki (run-<pid>-<uuid>-<seq>), więc nie nadpisują sobie kopii."""
    from caelo_core.agent.permissions import PermissionGate
    with tempfile.TemporaryDirectory() as d:
        reg = _make_registry(d)
        ws = Workspace(d)
        gate = PermissionGate()
        llm = lambda *a, **k: {"role": "assistant", "content": "ok"}  # noqa: E731
        ta, _ = _make_team(reg, ws, gate, llm)
        tb, _ = _make_team(reg, ws, gate, llm)
        shared = Path(tempfile.mkdtemp())
        ta.worktrees_base = shared
        tb.worktrees_base = shared
        pa = ta.new_worktree_path("sa1")
        pb = tb.new_worktree_path("sa1")
        check("3.3-b: parallel teams get disjoint worktree roots", pa != pb)
        check("3.3-b: worktree path is process-unique (pid-tagged)",
              "run-" in str(pa) and str(os.getpid()) in str(pa))


def test_role_registry_thread_safety() -> None:
    """3.3-d: równoległy odczyt/zapis RoleRegistry nie rzuca (lock wokół _save iteracji)."""
    import threading
    import time
    from caelo_core.agent.roles import RoleRegistry
    with tempfile.TemporaryDirectory() as d:
        reg = RoleRegistry(Path(d) / "subagents.json")
        errs: list = []
        stop = threading.Event()

        def writer(tag: int) -> None:
            n = 0
            while not stop.is_set():
                try:
                    reg.set_limits({"max_parallel": (n % 4) + 1})
                    reg.upsert_role({"id": f"r{tag}-{n % 5}", "tools": ["read_file"]})
                except Exception as e:  # noqa: BLE001
                    errs.append(repr(e))
                n += 1

        def reader() -> None:
            while not stop.is_set():
                try:
                    reg.list(); reg.limits(); reg.get("researcher")
                except Exception as e:  # noqa: BLE001
                    errs.append(repr(e))

        threads = [threading.Thread(target=writer, args=(0,)),
                   threading.Thread(target=writer, args=(1,)),
                   threading.Thread(target=reader)]
        for t in threads:
            t.start()
        time.sleep(0.25)
        stop.set()
        for t in threads:
            t.join(5)
        check("3.3-d: RoleRegistry concurrent read/write does not raise", errs == [])


def test_team_timeout_no_late_merge() -> None:
    """3.3-c: subagent zablokowany w wywołaniu (LLM ignoruje stop) i ZTIMEOUTOWANY NIE
    rejestruje scalenia — nawet kończąc PÓŹNO z realną zmianą w worktree."""
    import threading
    from caelo_core.agent.permissions import PermissionGate
    from caelo_core.agent.team import MergeStore
    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        (ws.root / "base.txt").write_text("base\n", encoding="utf-8")
        gate = PermissionGate()
        reg = _make_registry(d)
        # timeout_s ma dolny bound 10 w set_limits — ustaw bezpośrednio (szybki test).
        reg._limits["timeout_s"] = 1
        reg._limits["max_parallel"] = 1
        store = MergeStore(ws.root)
        release = threading.Event()
        threading.Timer(1.5, release.set).start()  # zwolnij PO timeoutcie (1 s)

        def llm_block(api_key, base_url, messages, model, temperature, tools, on_text=None, stop_flag=None, **_):
            if "IMPLEMENTER subagent" in messages[0]["content"]:
                if _n_assist(messages) == 0:
                    release.wait(10)  # blokuj IGNORUJĄC stop (jak requests.post)
                    return {"role": "assistant", "content": None, "tool_calls": [
                        {"id": "w", "type": "function", "function": {
                            "name": "write_file",
                            "arguments": json.dumps({"path": "out.txt", "content": "late"})}}]}
                return {"role": "assistant", "content": "wrote"}
            return {"role": "assistant", "content": "done"}

        team, _ = _make_team(reg, ws, gate, llm_block, store=store)
        team.run([{"role": "implementer", "task": "WRITEFILE:out.txt"}],
                 model="mock", workspace=ws, mode="ask")
        check("3.3-c: timed-out subagent (late finish) registers no merge", store.list() == [])


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
    test_run_command_no_false_timeout()  # 3.3-f
    test_run_command_env_scrub()
    test_atomic_write()
    test_symlink_sandbox()
    test_device_and_read_cap()           # 3.3-a
    test_web_fetch_dns_rebinding()       # 3.3-g
    test_command_security()
    test_ws_stream()
    # M13 — agent: zaufanie (diff / plan / checkpoint / CAELO.md / tryby)
    test_diff_binary()
    test_plan_mode()
    test_agent_modes()
    test_checkpoints()
    test_caelo_md()
    # M14 — rozszerzalność: narzędzia MCP w pętli agenta (B2) + hooki (B5)
    test_mcp_in_agent()
    test_hooks()
    # M17 — subagenci / zespół (B1 izolacja, B2 role, B3 worktree, B4 merge, B5/B6)
    test_team_isolation_and_roles()
    test_team_parallel_stop_budget()
    test_team_merge()
    test_team_cost()
    test_worktree_path_isolation()      # 3.3-b
    test_role_registry_thread_safety()  # 3.3-d
    test_team_timeout_no_late_merge()   # 3.3-c
    # M19 — B4: reguły uprawnień jako globy (ToolPrefix), deny>allow, integracja w pętli
    test_permission_rules()
    # M19 — B6: role skilli-orkiestratorów (rejestracja + brak eskalacji)
    test_orchestration_roles()
    # M19 — B8: wstrzyknięcie pamięci hybrydowej na 1. turze (mock memory)
    test_memory_injection()
    # M19 — B9: poziomy reasoning_effort (sesja/per-tura/role/payload llm)
    test_reasoning_effort()
    # M19 — B10: auto-compact kontekstu agenta (zwijanie najstarszych tur)
    test_autocompact()
    # M19 — B11: persony + kontrakt I/O subagentów (persona/contract/round-trip)
    test_persona_io()
    # M19 — B12: realne git worktree jako opcja (fallback do kopii, kształt, discard)
    test_git_worktree()
    # M19 — B13: web_fetch w agencie (https-only/SSRF/allowlista/cap + gating + advertise)
    test_web_fetch()
    # Faza-G / TOP1: web_search w agencie (live search READONLY, reuse responses_client)
    test_web_search()
    # Faza-G / TOP3: update_plan — live checklist/TODO agenta (ramka `plan` + advertise)
    test_plan_widget()
    # M19 — B14: config projektowy hierarchiczny (find_project_root + walk cwd→root)
    test_project_config()
    ok = True
    for name, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    print("RESULT:", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
