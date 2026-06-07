"""Tryb headless / CLI sidecara (M19-B1).

`python -m caelo_core run -p "..." [opcje]` — uruchamia agenta kodowania BEZ GUI/WS,
reużywając `AgentRunner` (M19-§0). Wyjście: `plain` | `json` | `streaming-json` (lustrzane
do oficjalnego Grok CLI). Fundament pod CI/skrypty i pod ACP (M19-B2).

Dyscyplina stdout: w trybie `run` NIE ma linii handshake — stdout to strumień zdarzeń /
finalny wynik, logi idą na stderr. UTF-8 wymuszony na stdout (zasada streamingu — Windows
cp1252 mangluje znaki spoza ASCII).

Bezpieczeństwo (fail-closed): brak człowieka → `request_approval` zawsze zwraca 'reject'.
Mutacje przechodzą TYLKO gdy: tryb `bypass`/`accept-edits` (`--permission-mode`/
`--always-approve`) albo reguła allow (`--allow`, B4 — deny>allow). `--tools`/
`--disallowed-tools` zawężają narzędzia; `Agent` w denyliście blokuje delegację (subagentów).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import secrets
import sys
from pathlib import Path
from typing import Optional

import config  # type: ignore  # repo-root (sys.path z caelo_core/__init__.py)
from caelo_core.agent import sessions  # M21: wspólny magazyn sesji (headless + WS)

log = logging.getLogger("caelo_core.headless")

# Narzędzia plikowe agenta (zbiór dla --tools/--disallowed-tools; MCP/delegate osobno).
_FILE_TOOLS = {"read_file", "list_dir", "glob", "grep", "write_file", "edit_file", "run_command"}


def _out(obj: dict) -> None:
    """Jedna linia JSON na stdout (newline-delimited, UTF-8)."""
    print(json.dumps(obj, ensure_ascii=False), flush=True)


# --- trwałe sesje (M19-B1): magazyn wydzielony do `agent/sessions.py` (M21 — wspólny
# z WS `/agent/stream`). Poniższe to cienkie aliasy zachowujące dotychczasowe API
# headless (self-checki ich używają); cała logika/format żyje w `sessions`. ---
def _sessions_dir() -> Path:
    return sessions.sessions_dir()


def _session_path(sid: str) -> Path:
    return sessions.session_path(sid)


def _load_session(sid: str) -> list:
    return sessions.load_history(sid)


def _save_session(sid: str, history: list, cwd: str) -> None:
    sessions.save(id=sid, cwd=cwd, history=history)


def _latest_session() -> Optional[str]:
    return sessions.latest()


# --- eksport sesji do Markdown (M19-B10) ----------------------------------------
def _msg_text(content) -> str:
    """Tekst wiadomości: string wprost albo sklejone części tekstowe (multimodal)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(p.get("text", "") for p in content
                        if isinstance(p, dict) and p.get("type") == "text" and p.get("text"))
    return ""


def history_to_markdown(history: list, *, title: str = "Caelo session") -> str:
    """M19-B10: serializuj surową historię agenta (wiadomości role user/assistant/tool)
    do Markdown. CZYSTA funkcja (testowalna). Tool-calls i wyniki narzędzi wypisane,
    by eksport oddał pełny przebieg tury."""
    out: list[str] = [f"# {title}", ""]
    for m in history:
        if not isinstance(m, dict):
            continue
        role = m.get("role", "?")
        text = _msg_text(m.get("content")).strip()
        if role == "user":
            out += ["## User", "", text or "(no text)", ""]
        elif role == "assistant":
            out += ["## Assistant", ""]
            if text:
                out += [text, ""]
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function", {}) or {}
                out.append(f"- 🔧 `{fn.get('name', '?')}({fn.get('arguments', '')})`")
            if m.get("tool_calls"):
                out.append("")
        elif role == "tool":
            out += ["### Tool result", "", "```", text[:2000], "```", ""]
    return "\n".join(out).rstrip() + "\n"


def _export_session(opts) -> int:
    """M19-B10: zapisz historię wybranej sesji do pliku Markdown. Nie potrzebuje
    Backendu/sieci — czyta `DATA_DIR/sessions/<id>.json`."""
    sid = opts.resume or opts.session_id or (_latest_session() if opts.cont else None)
    if not sid:
        print("Error: --export-md needs a session (-s <id> / -r <id> / -c)", file=sys.stderr)
        return 2
    if not _session_path(sid).exists():
        print(f"Error: session not found: {sid}", file=sys.stderr)
        return 2
    history = _load_session(sid)
    md = history_to_markdown(history, title=f"Caelo session {sid}")
    try:
        Path(opts.export_md).write_text(md, encoding="utf-8")
    except OSError as exc:
        print(f"Error: cannot write {opts.export_md!r}: {exc}", file=sys.stderr)
        return 2
    print(f"Exported session {sid} ({len(history)} messages) to {opts.export_md}",
          file=sys.stderr)
    return 0


def _resolve_tools(tools_csv: Optional[str], disallowed_csv: Optional[str]):
    """Zwraca (tool_names|None, allow_delegate). tool_names zawęża zbiór narzędzi
    plikowych (rola M17-B1); None = wszystkie. `Agent`/`Agent(...)` w denyliście → blokada
    delegacji (głębia 0)."""
    allow_delegate = True
    if tools_csv:
        names = {x.strip() for x in tools_csv.split(",") if x.strip()}
        allowed = names & _FILE_TOOLS
    else:
        allowed = set(_FILE_TOOLS)
    if disallowed_csv:
        for x in (y.strip() for y in disallowed_csv.split(",")):
            if not x:
                continue
            if x == "Agent" or x.startswith("Agent("):
                allow_delegate = False
            else:
                allowed.discard(x)
    tool_names = None if (not tools_csv and allowed == _FILE_TOOLS) else allowed
    return tool_names, allow_delegate


class _Sink:
    """Mapuje ramki agenta → wyjście wg formatu. `plain`/`json` buforują (finał na końcu);
    `streaming-json` emituje na bieżąco deltę z kumulowanego pola `full`."""

    def __init__(self, fmt: str) -> None:
        self.fmt = fmt
        self._prev = 0
        self.stop_reason = "EndTurn"
        self.error: Optional[str] = None

    def emit(self, ev: dict) -> None:
        t = ev.get("type")
        if t == "text":
            if self.fmt == "streaming-json":
                full = ev.get("full") or ""
                delta = full[self._prev:]
                self._prev = len(full)
                if delta:
                    _out({"type": "text", "data": delta})
        elif t == "tool_call" and self.fmt == "streaming-json":
            _out({"type": "tool_call", "name": ev.get("name"), "args": ev.get("args")})
        elif t == "stopped":
            self.stop_reason = "Stopped"
        elif t == "error":
            self.stop_reason = "Error"
            self.error = ev.get("error")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="caelo run",
                                description="Run the Caelo coding agent headless.")
    p.add_argument("-p", "--prompt", "--single", dest="prompt", default=None,
                   help="Prompt to send to the agent (required unless --export-md).")
    p.add_argument("--export-md", dest="export_md", default=None,
                   help="Export a saved session's history to this Markdown file and exit "
                        "(use with -s/-r/-c to pick the session).")
    p.add_argument("-m", "--model", dest="model", default=None, help="Model id.")
    p.add_argument("--cwd", dest="cwd", default=None, help="Workspace directory (default: cwd).")
    p.add_argument("--project-root", dest="project_root", action="store_true",
                   help="Use the git project root (walk up from --cwd for .git) as the "
                        "workspace instead of --cwd (M19-B14).")
    p.add_argument("--output-format", dest="fmt",
                   choices=["plain", "json", "streaming-json"], default="plain")
    p.add_argument("--max-turns", dest="max_turns", type=int, default=None,
                   help="Max agentic iterations before stopping.")
    p.add_argument("--effort", "--reasoning-effort", dest="effort",
                   choices=["low", "medium", "high"], default=None,
                   help="Reasoning effort for reasoning models (low|medium|high).")
    p.add_argument("--tools", dest="tools", default=None,
                   help="Comma-separated allowlist of tools (only these are available).")
    p.add_argument("--disallowed-tools", dest="disallowed", default=None,
                   help="Comma-separated denylist; Agent / Agent(role) blocks delegation.")
    p.add_argument("--permission-mode", dest="perm_mode",
                   choices=["ask", "accept-edits", "plan", "bypass"], default="ask")
    p.add_argument("--always-approve", dest="always", action="store_true",
                   help="Auto-approve all mutations (= --permission-mode bypass).")
    p.add_argument("--allow", dest="allow", action="append", default=[],
                   help="Glob permission allow rule, e.g. Bash(npm*) (repeatable).")
    p.add_argument("--sandbox", dest="sandbox", default=None,
                   choices=["off", "workspace", "read-only", "strict"],
                   help="OS sandbox profile for child processes (M19-B7; default off / "
                        "env CAELO_SANDBOX). Linux=bwrap, macOS=sandbox-exec; else no-op.")
    p.add_argument("--worktree", dest="worktree", nargs="?", const=True, default=None,
                   help="Use real `git worktree` for mutating subagents when the workspace "
                        "is a git repo (M19-B12; default off / env CAELO_GIT_WORKTREE).")
    p.add_argument("--disable-web-search", dest="disable_web", action="store_true",
                   help="Disable the agent's web_fetch tool for this run (M19-B13; web_fetch "
                        "is opt-in via env CAELO_WEB_FETCH).")
    p.add_argument("--deny", dest="deny", action="append", default=[],
                   help="Glob permission deny rule, e.g. Bash(rm*) (repeatable).")
    p.add_argument("-s", "--session-id", dest="session_id", default=None,
                   help="Create or resume a session with this id.")
    p.add_argument("-r", "--resume", dest="resume", default=None,
                   help="Resume an existing session (error if not found).")
    p.add_argument("-c", "--continue", dest="cont", action="store_true",
                   help="Continue the most recent session.")
    return p


def _resolve_session(opts):
    """(session_id, initial_history) | (None, None) gdy --resume nie istnieje."""
    if opts.resume:
        if not _session_path(opts.resume).exists():
            print(f"Error: session not found: {opts.resume}", file=sys.stderr)
            return None, None
        return opts.resume, _load_session(opts.resume)
    if opts.cont:
        sid = _latest_session()
        return (sid, _load_session(sid)) if sid else (secrets.token_urlsafe(8), [])
    if opts.session_id:
        return opts.session_id, _load_session(opts.session_id)  # create-or-resume
    return secrets.token_urlsafe(8), []


def _apply_rules(backend, allow: list, deny: list) -> None:
    """Scal reguły glob z CLI (--allow/--deny) z trwałymi (globalne+projektowe — już w
    bramce po set_workspace). Niepoprawne wpisy → ostrzeżenie na stderr i pominięcie."""
    from caelo_core.agent.permission_rules import parse_rule

    for r in (*allow, *deny):
        if parse_rule(r) is None:
            print(f"Warning: ignoring invalid rule: {r!r}", file=sys.stderr)
    cur = backend.permissions.rule_strings()
    backend.permissions.set_rules(
        cur["allow"] + [r for r in allow if parse_rule(r)],
        cur["deny"] + [r for r in deny if parse_rule(r)],
    )


def _run(opts, backend) -> int:
    """Rdzeń trybu headless (backend wstrzykiwany — testowalny bez I/O Backendu)."""
    from caelo_core.agent.runner import AgentRunner

    # M19-B7: profil sandboxa z flagi (nadpisuje env CAELO_SANDBOX dla tego biegu).
    if getattr(opts, "sandbox", None):
        config.SANDBOX_PROFILE = opts.sandbox
    # M19-B12: włącz realne git worktree dla tego biegu (--worktree).
    if getattr(opts, "worktree", None):
        config.AGENT_GIT_WORKTREE = True
    # M19-B13: wyłącz web_fetch dla tego biegu (--disable-web-search), nawet gdy env je włączył.
    if getattr(opts, "disable_web", False):
        config.WEB_FETCH_ENABLED = False

    cwd = os.path.abspath(opts.cwd or os.getcwd())
    # M19-B14: --project-root → użyj korzenia repo (najbliższy .git w górę) jako workspace.
    if getattr(opts, "project_root", False):
        from caelo_core.agent.project import find_project_root
        cwd = str(find_project_root(cwd))
    try:
        backend.set_workspace(cwd)
    except Exception as exc:  # noqa: BLE001
        print(f"Error: cannot set workspace {cwd!r}: {exc}", file=sys.stderr)
        return 2

    _apply_rules(backend, opts.allow, opts.deny)

    sid, initial = _resolve_session(opts)
    if sid is None:
        return 2

    mode = "bypass" if opts.always else opts.perm_mode
    tool_names, allow_delegate = _resolve_tools(opts.tools, opts.disallowed)
    model = opts.model or backend.read_settings().get("code_model") or "grok-build-0.1"
    # M19-B9: --effort z fallbackiem na ustawienie `code_effort`; niepoprawne → None.
    from caelo_core import validation as V
    effort = V.normalize_effort(opts.effort or backend.read_settings().get("code_effort"))

    sink = _Sink(opts.fmt)
    runner = AgentRunner(
        backend, emit=sink.emit, request_approval=lambda *a: "reject",  # fail-closed
        stop=lambda: False, tool_names=tool_names, max_iters=opts.max_turns,
        allow_delegate=allow_delegate, initial_history=initial,
        reasoning_effort=effort,  # M19-B9
    )
    final = runner.run_turn(opts.prompt, model, mode=mode)

    # M21: zapisz pełną sesję ze stemplem projektu (M9-B5) + modelem — by lista sesji
    # w UI mogła filtrować po projekcie. StubBackend bez current_project_id → None.
    sessions.save(id=sid, cwd=cwd, history=runner.history,
                  project_id=getattr(backend, "current_project_id", None), model=model)

    if opts.fmt == "plain":
        if final:
            print(final, flush=True)
        if sink.error:
            print(f"Error: {sink.error}", file=sys.stderr)
    elif opts.fmt == "json":
        _out({"text": final, "stopReason": sink.stop_reason, "sessionId": sid})
    else:  # streaming-json
        _out({"type": "end", "stopReason": sink.stop_reason, "sessionId": sid})
    return 1 if sink.stop_reason == "Error" else 0


def main(argv) -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # zasada UTF-8 (stdout = strumień zdarzeń)
    except Exception:  # noqa: BLE001
        pass
    opts = _build_parser().parse_args(argv)

    # M19-B10: eksport sesji do Markdown — osobna, czysta ścieżka (bez Backendu/sieci).
    if opts.export_md:
        return _export_session(opts)
    if not opts.prompt:
        print("Error: -p/--prompt is required (or use --export-md to export a session).",
              file=sys.stderr)
        return 2

    from caelo_core.state import Backend

    backend = Backend()
    try:
        return _run(opts, backend)
    finally:
        try:
            backend.shutdown()  # tree-kill ewentualnych podprocesów MCP
        except Exception:  # noqa: BLE001
            pass
