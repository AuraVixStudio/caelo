"""Narzędzia plikowe agenta: schematy (function-calling), egzekutory, podgląd zmian.

Operacje plikowe są sandboxowane do workspace (Workspace.resolve). `run_command`
nie jest sandboxowany w treści polecenia — dlatego wymaga zatwierdzenia.
"""

from __future__ import annotations

import difflib
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Callable, Optional

from grok_core.agent.permissions import command_metachars
from grok_core.agent.workspace import Workspace, WorkspaceError

# P0-3: silnik regex z wall-clock timeoutem (ReDoS). Moduł `regex` wspiera
# per-search `timeout=`, którego stdlib `re` nie ma (a wzorzec sterowany jest
# przez model). Gdy `regex` niedostępny — fallback do `re` (bez timeoutu, ale
# z limitem rozmiaru/binariów i łącznym budżetem czasu poniżej).
try:
    import regex as _rx_engine
    _RX_TIMEOUT = True
except Exception:  # pragma: no cover - fallback gdy modułu brak
    import re as _rx_engine
    _RX_TIMEOUT = False

IGNORE_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__",
    "out", "dist", ".vite", ".idea", ".vscode", "build",
}

# Limity grep (P0-3): chronią przed ReDoS i wczytaniem ogromnych/binarnych plików.
GREP_MAX_FILE_BYTES = 8 * 1024 * 1024   # pomijaj pliki większe niż ~8 MB
GREP_SEARCH_TIMEOUT_S = 1.0             # budżet wall-clock na pojedyncze rx.search
GREP_TOTAL_TIMEOUT_S = 10.0            # łączny budżet wall-clock całego grep
GREP_BINARY_SNIFF = 4096               # ile bajtów wąchać pod kątem bajtu NUL

# Limity run_command (P0-4).
RUN_OUTPUT_CAP = 8000                   # maks. bajtów wyjścia trzymanych w pamięci/zwracanych
RUN_STOP_POLL_S = 0.1                   # co ile sekund wątek-nadzorca sprawdza Stop

# P0-6: zmienne usuwane ze środowiska run_command, by nie wyciekły do modelu
# (komenda jest sterowana przez model, a jej wyjście wraca do modelu — `set`/`env`
# nie mogą ujawnić sekretów). Jawne nazwy z naszej apki + sieć wzorców.
_ENV_SCRUB_EXACT = {"GROK_CORE_TOKEN", "XAI_API_KEY"}
_ENV_SCRUB_SUBSTR = ("TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL",
                     "API_KEY", "APIKEY", "ACCESS_KEY", "PRIVATE_KEY")

# --- schematy narzędzi (format xAI/OpenAI function-calling) ---
TOOLS = [
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Read a UTF-8 text file from the workspace. Returns numbered lines.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Path relative to workspace root."},
            "offset": {"type": "integer", "description": "First line (0-based)."},
            "limit": {"type": "integer", "description": "Max lines to return."},
        }, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "list_dir",
        "description": "List entries of a directory in the workspace.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Directory path (default '.')."},
        }}}},
    {"type": "function", "function": {
        "name": "glob",
        "description": "Find files by glob pattern (e.g. '**/*.py') relative to workspace.",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string"},
        }, "required": ["pattern"]}}},
    {"type": "function", "function": {
        "name": "grep",
        "description": "Search file contents by regular expression. Returns path:line: match.",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string"},
            "path": {"type": "string", "description": "File or dir to search (default '.')."},
            "ignore_case": {"type": "boolean"},
        }, "required": ["pattern"]}}},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "Create or overwrite a file with the given content. Requires approval.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        }, "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "edit_file",
        "description": "Replace an exact unique string in a file. Requires approval.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "old_string": {"type": "string", "description": "Exact text to replace (must be unique unless replace_all)."},
            "new_string": {"type": "string"},
            "replace_all": {"type": "boolean"},
        }, "required": ["path", "old_string", "new_string"]}}},
    {"type": "function", "function": {
        "name": "run_command",
        "description": ("Run a single program in the workspace. Requires approval. Returns exit "
                        "code + output. Shell operators are NOT allowed (no & | ; < > $ ` ( ) { } "
                        "or newlines) — to chain steps, issue separate run_command calls."),
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string"},
            "cwd": {"type": "string", "description": "Working dir relative to workspace (optional)."},
            "timeout": {"type": "integer", "description": "Seconds (default 120)."},
        }, "required": ["command"]}}},
]


def _within_root(p: Path, root: Path) -> bool:
    """Czy realna ścieżka `p` (po rozwinięciu symlinków/junctionów) zostaje w
    `root`. `resolve()` rozwija też reparse-pointy Windows (junction), których
    `is_symlink()` nie wykrywa — dlatego kluczowe dla P0-7."""
    try:
        real = p.resolve()
    except OSError:
        return False
    return real == root or root in real.parents


def _walk_files(base: Path, root: Path):
    # P0-7: nie podążaj za symlinkami/junctionami poza workspace. os.walk z
    # followlinks=False nie wchodzi w dowiązane katalogi-symlinki; junctiony i
    # pliki-symlinki odsiewamy przez _within_root (resolve()).
    for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
        dirnames[:] = [
            d for d in dirnames
            if d not in IGNORE_DIRS and _within_root(Path(dirpath) / d, root)
        ]
        for fn in filenames:
            p = Path(dirpath) / fn
            if _within_root(p, root):
                yield p


def _is_binary(path: Path) -> bool:
    """Heurystyka: plik jest binarny, jeśli w pierwszych bajtach jest NUL."""
    try:
        with path.open("rb") as fh:
            return b"\x00" in fh.read(GREP_BINARY_SNIFF)
    except OSError:
        return True


# --- egzekutory ---
def read_file(ws: Workspace, path: str, offset: int = 0, limit: int = 2000, **_) -> str:
    p = ws.resolve(path)
    if not p.exists():
        return f"Error: file not found: {path}"
    if p.is_dir():
        return f"Error: is a directory: {path}"
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    start = max(0, int(offset or 0))
    end = start + int(limit or 2000)
    chunk = lines[start:end]
    numbered = "\n".join(f"{start + i + 1}\t{ln}" for i, ln in enumerate(chunk))
    if not numbered:
        return "(empty or out-of-range)"
    if end < len(lines):
        numbered += f"\n… ({len(lines) - end} more lines)"
    return numbered


def list_dir(ws: Workspace, path: str = ".", **_) -> str:
    p = ws.resolve(path)
    if not p.is_dir():
        return f"Error: not a directory: {path}"
    entries = sorted(p.iterdir(), key=lambda e: (e.is_file(), e.name.lower()))
    # P0-7: pomiń wpisy wychodzące poza workspace (symlink/junction na zewnątrz).
    out = [e.name + ("/" if e.is_dir() else "")
           for e in entries if _within_root(e, ws.root)]
    return "\n".join(out) or "(empty)"


def glob(ws: Workspace, pattern: str, **_) -> str:
    # P0-2: glob nie może uciec z workspace. `ws.root.glob()` omijał `ws.resolve()`,
    # więc wzorzec `../**/*` enumerował pliki POZA korzeniem (wyciek struktury FS,
    # m.in. ścieżek do grok_auth.json). Odrzucamy wzorce `..`/absolutne na wejściu
    # i dodatkowo re-walidujemy każdy wynik przez sandbox (łapie też symlinki).
    pat = (pattern or "").strip()
    if not pat:
        return "Error: empty glob pattern"
    norm = pat.replace("\\", "/")
    if (".." in norm.split("/")
            or PurePosixPath(norm).is_absolute()
            or PureWindowsPath(pat).is_absolute()):
        return "Error: glob pattern must be relative to the workspace (no '..' or absolute paths)"
    try:
        results = list(ws.root.glob(pat))
    except (ValueError, OSError) as exc:
        return f"Error: bad glob pattern: {exc}"
    matches = []
    for p in results:
        if any(part in IGNORE_DIRS for part in p.parts):
            continue
        try:
            ws.resolve(ws.rel(p))  # re-walidacja sandboxa (ucieczki przez `..`/symlink)
        except WorkspaceError:
            continue
        matches.append(ws.rel(p))
    matches.sort()
    if not matches:
        return "(no matches)"
    if len(matches) > 200:
        return "\n".join(matches[:200]) + f"\n… ({len(matches) - 200} more)"
    return "\n".join(matches)


def grep(ws: Workspace, pattern: str, path: str = ".", ignore_case: bool = False,
         max_results: int = 200, **_) -> str:
    base = ws.resolve(path)
    try:
        rx = _rx_engine.compile(pattern, _rx_engine.IGNORECASE if ignore_case else 0)
    except Exception as exc:  # re.error / regex.error — wzorzec od modelu
        return f"Error: bad regex: {exc}"

    # P0-3: timeout per-search (ReDoS) + łączny budżet + pomijanie dużych/binarnych.
    search_kw = {"timeout": GREP_SEARCH_TIMEOUT_S} if _RX_TIMEOUT else {}
    files = [base] if base.is_file() else _walk_files(base, ws.root)
    out: list[str] = []
    skipped_large = skipped_binary = 0
    deadline = time.monotonic() + GREP_TOTAL_TIMEOUT_S
    timed_out = False

    for f in files:
        if time.monotonic() > deadline:
            timed_out = True
            break
        try:
            if f.stat().st_size > GREP_MAX_FILE_BYTES:
                skipped_large += 1
                continue
        except OSError:
            continue
        if _is_binary(f):
            skipped_binary += 1
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        try:
            for i, line in enumerate(text.splitlines(), 1):
                # Sprawdzaj budżet CO LINIĘ: każde rx.search może trwać do
                # GREP_SEARCH_TIMEOUT_S, więc rzadsze sprawdzanie pozwoliłoby
                # wielokrotnie przekroczyć łączny budżet (DoS przez wolny wzorzec).
                if time.monotonic() > deadline:
                    timed_out = True
                    break
                if rx.search(line, **search_kw):
                    out.append(f"{ws.rel(f)}:{i}: {line.strip()[:200]}")
                    if len(out) >= max_results:
                        return "\n".join(out) + "\n… (truncated)"
        except TimeoutError:
            return ("Error: regex timed out (possible catastrophic backtracking). "
                    "Simplify the pattern — avoid nested quantifiers like (a+)+ or (a|a)*.")
        if timed_out:
            break

    result = "\n".join(out) if out else "(no matches)"
    notes = []
    if timed_out:
        notes.append(f"search budget {GREP_TOTAL_TIMEOUT_S:.0f}s exceeded — partial results")
    if skipped_large:
        notes.append(f"{skipped_large} file(s) >{GREP_MAX_FILE_BYTES // (1024 * 1024)}MB skipped")
    if skipped_binary:
        notes.append(f"{skipped_binary} binary file(s) skipped")
    if notes:
        result += "\n[" + "; ".join(notes) + "]"
    return result


def atomic_write_text(p: Path, content: str) -> None:
    """P0-7: zapis atomowy (temp w tym samym katalogu + os.replace). Oryginał nie
    jest truncowany w miejscu — przy błędzie/utracie zasilania plik nie ginie.
    fsync przed replace = treść trwale na dysku. Zachowuje translację newline jak
    write_text (newline=None → os.linesep na Windows)."""
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".grok-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_file(ws: Workspace, path: str, content: str = "", **_) -> str:
    p = ws.resolve(path)
    atomic_write_text(p, content)
    return f"Wrote {len(content)} chars to {path}"


def edit_file(ws: Workspace, path: str, old_string: str, new_string: str,
              replace_all: bool = False, **_) -> str:
    p = ws.resolve(path)
    if not p.exists():
        return f"Error: file not found: {path}"
    text = p.read_text(encoding="utf-8", errors="replace")
    count = text.count(old_string)
    if count == 0:
        return f"Error: old_string not found in {path}"
    if count > 1 and not replace_all:
        return f"Error: old_string is not unique in {path} ({count} matches). Add context or set replace_all."
    new_text = text.replace(old_string, new_string) if replace_all else text.replace(old_string, new_string, 1)
    atomic_write_text(p, new_text)  # P0-7: zapis atomowy
    return f"Edited {path} ({count if replace_all else 1} replacement(s))"


def _scrubbed_env() -> dict:
    """Środowisko dla run_command bez sekretów (P0-6). Denylista (nie minimalny
    allowlist), by nie psuć narzędzi wymagających PATH/APPDATA/SystemRoot itd.,
    a jednocześnie nie ujawnić GROK_CORE_TOKEN/XAI_API_KEY i podobnych modelowi."""
    env = {}
    for k, v in os.environ.items():
        ku = k.upper()
        if k in _ENV_SCRUB_EXACT or any(s in ku for s in _ENV_SCRUB_SUBSTR):
            continue
        env[k] = v
    return env


def _tree_kill(proc: "subprocess.Popen") -> None:
    """Ubija proces I jego potomków. `proc.kill()` z `shell=True` zabija tylko
    `cmd.exe`/`sh`, a nie uruchomione przez nie programy (P0-4). Windows: taskkill
    /T /F po PID; POSIX: SIGKILL na grupie procesów (Popen z start_new_session)."""
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
            )
        else:
            import signal
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def run_command(ws: Workspace, command: str, cwd: Optional[str] = None, timeout: int = 120,
                on_output: Optional[Callable[[str], None]] = None,
                stop_flag: Optional[Callable[[], bool]] = None, **_) -> str:
    # P0-1: odrzuć metaznaki powłoki PRZED uruchomieniem. Z `shell=True` to one
    # umożliwiają łańcuchowanie (`git && rm`, `a | b`, `$(...)`), więc bez nich
    # komenda to pojedyncze wywołanie — co widać w zatwierdzeniu, to się wykona.
    bad = command_metachars(command or "")
    if bad:
        shown = " ".join(sorted(c.encode("unicode_escape").decode() for c in bad))
        return (f"Error: command rejected — shell operators are not allowed ({shown}). "
                f"Run a single program per call; issue separate run_command calls to chain steps.")
    workdir = ws.resolve(cwd) if cwd else ws.root
    popen_kwargs: dict = {"env": _scrubbed_env()}  # P0-6: bez sekretów w env
    if os.name != "nt":
        # nowa sesja = własna grupa procesów → killpg ubije całe drzewo (P0-4)
        popen_kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(
            command, shell=True, cwd=str(workdir),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            **popen_kwargs,
        )
    except Exception as exc:
        return f"Error: cannot start command: {exc}"

    killed = {"why": ""}
    done = threading.Event()

    def _kill(reason: str):
        if not killed["why"]:
            killed["why"] = reason
        _tree_kill(proc)  # P0-4: ubij całe drzewo, nie tylko powłokę

    def _watch_stop():
        # P0-4: nadzorca przerywa nawet komendy „ciche" (bez wyjścia), na których
        # pętla odczytu blokuje się i nie sprawdzałaby Stop/timeoutu.
        while not done.wait(RUN_STOP_POLL_S):
            if stop_flag and stop_flag():
                _kill("stopped")
                return

    timer = threading.Timer(max(1, int(timeout or 120)), lambda: _kill("timeout"))
    timer.start()
    watcher = threading.Thread(target=_watch_stop, daemon=True) if stop_flag else None
    if watcher:
        watcher.start()

    captured: list[str] = []
    captured_len = 0
    truncated = False
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            if on_output:
                on_output(line)
            # P0-4: ogranicz akumulację w pamięci w pętli, nie dopiero przy zwrocie.
            if not truncated:
                captured.append(line)
                captured_len += len(line)
                if captured_len >= RUN_OUTPUT_CAP:
                    truncated = True
            if stop_flag and stop_flag():  # szybka ścieżka, gdy jest wyjście
                _kill("stopped")
                break
    except (ValueError, OSError):
        pass  # stdout zamknięty przez kill — oczekiwane
    finally:
        done.set()
        timer.cancel()
        if watcher:
            watcher.join(timeout=1)
        proc.wait()

    out = "".join(captured)
    if truncated or len(out) > RUN_OUTPUT_CAP:
        out = out[:RUN_OUTPUT_CAP] + "\n… (output truncated)"
    suffix = f"\n[{killed['why']}]" if killed["why"] else ""
    return f"(exit {proc.returncode}){suffix}\n{out}".rstrip()


_EXECUTORS = {
    "read_file": read_file,
    "list_dir": list_dir,
    "glob": glob,
    "grep": grep,
    "write_file": write_file,
    "edit_file": edit_file,
    "run_command": run_command,
}


def execute_tool(ws: Workspace, name: str, args: dict,
                 on_output: Optional[Callable[[str], None]] = None,
                 stop_flag: Optional[Callable[[], bool]] = None) -> str:
    fn = _EXECUTORS.get(name)
    if fn is None:
        return f"Error: unknown tool {name}"
    kwargs = dict(args or {})
    if name == "run_command":
        kwargs["on_output"] = on_output
        kwargs["stop_flag"] = stop_flag
    try:
        return fn(ws, **kwargs)
    except TypeError as exc:
        return f"Error: bad arguments for {name}: {exc}"
    except Exception as exc:  # noqa: BLE001
        return f"Error: {exc}"


def _udiff(old: str, new: str, path: str) -> str:
    diff = difflib.unified_diff(
        old.splitlines(keepends=True), new.splitlines(keepends=True),
        fromfile=f"a/{path}", tofile=f"b/{path}",
    )
    text = "".join(diff)
    return text or "(no textual changes)"


def preview_change(ws: Workspace, name: str, args: dict) -> Optional[dict]:
    """Buduje opis zmiany do zatwierdzenia (diff dla write/edit, komenda dla run)."""
    try:
        if name == "write_file":
            p = ws.resolve(args["path"])
            old = p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""
            return {"kind": "diff", "path": args["path"], "diff": _udiff(old, args.get("content", ""), args["path"])}
        if name == "edit_file":
            p = ws.resolve(args["path"])
            old = p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""
            os_, ns = args.get("old_string", ""), args.get("new_string", "")
            new = old.replace(os_, ns) if args.get("replace_all") else old.replace(os_, ns, 1)
            return {"kind": "diff", "path": args["path"], "diff": _udiff(old, new, args["path"])}
        if name == "run_command":
            return {"kind": "command", "command": args.get("command", ""), "cwd": args.get("cwd")}
    except Exception as exc:  # noqa: BLE001
        return {"kind": "error", "detail": str(exc)}
    return None
