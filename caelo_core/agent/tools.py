"""Narzędzia plikowe agenta: schematy (function-calling), egzekutory, podgląd zmian.

Operacje plikowe są sandboxowane do workspace (Workspace.resolve). `run_command`
nie jest sandboxowany w treści polecenia — dlatego wymaga zatwierdzenia.
"""

from __future__ import annotations

import difflib
import html
import ipaddress
import logging
import os
import re
import shlex
import subprocess
import tempfile
import threading
import time
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Callable, Optional
from urllib.parse import urlparse

import requests  # type: ignore

import config  # type: ignore  # repo-root (sys.path z caelo_core/__init__.py)

from caelo_core.agent.permissions import command_metachars
from caelo_core.agent.workspace import Workspace, WorkspaceError

log = logging.getLogger(__name__)

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
    ".git", ".caelo", ".grok", "node_modules", ".venv", "venv", "__pycache__",
    "out", "dist", ".vite", ".idea", ".vscode", "build",
}
# `.caelo` = magazyn checkpointów agenta (M13-B3). Nie enumeruj/przeszukuj go —
# inaczej agent czytałby własne kopie zapasowe (i widziałby je w glob/grep).
# `.grok` zostaje na liście dla wstecznej zgodności (stara nazwa sprzed rebrandu M15).

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
_ENV_SCRUB_EXACT = {"CAELO_CORE_TOKEN", "XAI_API_KEY"}
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


def list_dir(ws: Workspace, path: str = ".", rule_filter=None, **_) -> str:
    p = ws.resolve(path)
    if not p.is_dir():
        return f"Error: not a directory: {path}"
    entries = sorted(p.iterdir(), key=lambda e: (e.is_file(), e.name.lower()))
    # P0-7: pomiń wpisy wychodzące poza workspace (symlink/junction na zewnątrz).
    # P1-B: ukryj NAZWĘ wpisu objętego regułą deny (np. `Read(secret)` ukrywa katalog
    # `secret`). Uwaga: `Read(secret/**)` NIE złapie gołego segmentu — do ukrycia samego
    # katalogu trzeba reguły `Read(<dir>)` (matcher segmentowy, patrz permission_rules).
    out = [e.name + ("/" if e.is_dir() else "")
           for e in entries
           if _within_root(e, ws.root) and not (rule_filter and rule_filter(ws.rel(e)))]
    return "\n".join(out) or "(empty)"


def glob(ws: Workspace, pattern: str, rule_filter=None, **_) -> str:
    # P0-2: glob nie może uciec z workspace. `ws.root.glob()` omijał `ws.resolve()`,
    # więc wzorzec `../**/*` enumerował pliki POZA korzeniem (wyciek struktury FS,
    # m.in. ścieżek do caelo_auth.json). Odrzucamy wzorce `..`/absolutne na wejściu
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
        rel = ws.rel(p)
        try:
            ws.resolve(rel)  # re-walidacja sandboxa (ucieczki przez `..`/symlink)
        except WorkspaceError:
            continue
        if rule_filter and rule_filter(rel):  # P1-B: pomiń ścieżkę objętą deny
            continue
        matches.append(rel)
    matches.sort()
    if not matches:
        return "(no matches)"
    if len(matches) > 200:
        return "\n".join(matches[:200]) + f"\n… ({len(matches) - 200} more)"
    return "\n".join(matches)


def grep(ws: Workspace, pattern: str, path: str = ".", ignore_case: bool = False,
         max_results: int = 200, rule_filter=None, **_) -> str:
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
        # P1-B: pomiń (przed czytaniem) pliki objęte regułą deny — inaczej grep zwracał
        # modelowi dopasowane linie z deny-listowanych ścieżek (np. secret/). Filtr per-plik
        # (1× evaluate_rules na plik), nie per-linia.
        if rule_filter and rule_filter(ws.rel(f)):
            continue
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
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".caelo-", suffix=".tmp")
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


def atomic_write_bytes(p: Path, data: bytes) -> None:
    """Atomowy zapis bajtów (temp + os.replace). Wariant `atomic_write_text` dla
    treści binarnej — używany przy przywracaniu checkpointów (M13-B3), gdzie kopia
    zapasowa może być dowolnym plikiem (obraz, archiwum), nie tylko tekstem."""
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".caelo-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
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


def scrubbed_env() -> dict:
    """Środowisko bez sekretów (P0-6). Denylista (nie minimalny allowlist), by nie
    psuć narzędzi wymagających PATH/APPDATA/SystemRoot itd., a jednocześnie nie
    ujawnić CAELO_CORE_TOKEN/XAI_API_KEY i podobnych. Reużywane przez `run_command`
    oraz pty terminala (P0-11) — tam też `set`/`env` nie mogą wyciec sekretów."""
    env = {}
    for k, v in os.environ.items():
        ku = k.upper()
        if k in _ENV_SCRUB_EXACT or any(s in ku for s in _ENV_SCRUB_SUBSTR):
            continue
        env[k] = v
    return env


def _tree_kill(proc: "subprocess.Popen") -> None:
    """Ubija proces I jego potomków, cross-platform (P0-4, M15-6). `proc.kill()` z
    `shell=True` zabija tylko `cmd.exe`/`sh`, a nie uruchomione przez nie programy.
      • Windows: `taskkill /T /F` po PID (ubija drzewo; brak grzecznego wariantu).
      • POSIX:   grupa procesów (Popen z `start_new_session`) — najpierw **SIGTERM**
        (grzeczne zakończenie, szansa na sprzątnięcie), a gdy proces nie zniknie w
        krótkim oknie — **SIGKILL** (twardo). Eskalacja SIGTERM→SIGKILL zamiast od
        razu SIGKILL daje narzędziom (np. testom, devserverom) szansę domknięcia."""
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
            pgid = os.getpgid(proc.pid)
            os.killpg(pgid, signal.SIGTERM)   # 1) grzecznie całej grupie
            try:
                proc.wait(timeout=3)          # daj szansę na czyste wyjście
            except subprocess.TimeoutExpired:
                os.killpg(pgid, signal.SIGKILL)  # 2) uparte → twardo
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
    popen_kwargs: dict = {"env": scrubbed_env()}  # P0-6: bez sekretów w env
    # P0-10: dobór powłoki zależnie od platformy.
    #  • Windows: shell=True — zgodność z `.cmd` (npm/npx/tsc) i builtinami cmd
    #    (`echo`/`dir`/`cd`); skaner metaznaków (świadomy cudzysłowów cmd.exe) już
    #    odrzucił łańcuchowanie, więc komenda to pojedyncze wywołanie.
    #  • POSIX: shell=False + argv (shlex) — nawet GDYBY metaznak prześlizgnął się
    #    obok skanera, NIE ma `sh`, które zinterpretowałoby `&&`/`;`/`|`/`$()`.
    #    Skaner sh jest tu tylko zachowawczym pre-filtrem, nie jedyną obroną.
    if os.name == "nt":
        popen_target: object = command
        use_shell = True
    else:
        try:
            argv = shlex.split(command)
        except ValueError as exc:
            return f"Error: cannot parse command: {exc}"
        if not argv:
            return "Error: empty command"
        popen_target = argv
        use_shell = False
        # nowa sesja = własna grupa procesów → killpg ubije całe drzewo (P0-4)
        popen_kwargs["start_new_session"] = True
        # M19-B7: opcjonalny sandbox OS (off-by-default → no-op). Owija argv launcherem
        # (bwrap/sandbox-exec); brak wsparcia/platformy → bez zmian. FAIL-OPEN: błąd
        # budowy sandboxa nie blokuje komendy (defense-in-depth, jak Grok CLI).
        try:
            from caelo_core import sandbox
            popen_target = sandbox.wrap_command(argv, root=str(ws.root))
        except Exception:  # noqa: BLE001
            log.warning("sandbox wrap failed; running without OS sandbox", exc_info=True)
            popen_target = argv
    try:
        proc = subprocess.Popen(
            popen_target, shell=use_shell, cwd=str(workdir),
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


# --- web_fetch (M19-B13) — egress agenta pod bramką ---
_WEB_FETCH_UA = "Caelo-Agent/1.0"


def _web_host_blocked(host: str) -> bool:
    """SSRF-guard: blokuj localhost/loopback oraz sieci prywatne/link-local/zarezerwowane
    podane jako LITERAŁ IP. Nazwy hostów (nie-IP) przepuszczamy — decyduje allowlista +
    bramka (pełna ochrona DNS-rebinding poza zakresem [P3])."""
    h = (host or "").strip().strip("[]").lower()
    if not h or h == "localhost" or h.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False
    return (ip.is_loopback or ip.is_private or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified)


def _web_host_allowed(host: str, allow: list) -> bool:
    """Czy host pasuje do twardej allowlisty (`WEB_FETCH_ALLOW_DOMAINS`) — dokładnie
    lub jako subdomena (bez `www.`)."""
    h = (host or "").lower()
    h = h[4:] if h.startswith("www.") else h
    for d in allow:
        d = (d or "").lower()
        d = d[4:] if d.startswith("www.") else d
        if d and (h == d or h.endswith("." + d)):
            return True
    return False


def _html_to_text(s: str) -> str:
    """Minimalna redukcja HTML→tekst (bez nowej zależności): usuń script/style + tagi,
    odkoduj encje, zwiń białe znaki."""
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t\f\v]{2,}", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def web_fetch(ws: Workspace, url: str = "", max_bytes: Optional[int] = None, **_) -> str:
    """M19-B13: pobierz treść URL (https-only, allowlista hostów, cap, SSRF-guard). Zwraca
    tekst (HTML zredukowany do tekstu) albo `Error: …`. Egress jest bramkowany WYŻEJ
    (MUTATING → approval / reguła WebFetch); tu wymuszamy twarde inwarianty sieciowe."""
    u = (url or "").strip()
    if not u.lower().startswith("https://"):
        return "Error: web_fetch requires an https:// URL"
    try:
        host = urlparse(u).hostname or ""
    except Exception:  # noqa: BLE001
        host = ""
    if _web_host_blocked(host):
        return f"Error: web_fetch refused host '{host or u}' (loopback/private not allowed)"
    allow = getattr(config, "WEB_FETCH_ALLOW_DOMAINS", []) or []
    if allow and not _web_host_allowed(host, allow):
        return f"Error: host '{host}' is not in the web_fetch allowlist (WEB_FETCH_ALLOW_DOMAINS)"
    cap = getattr(config, "WEB_FETCH_MAX_BYTES", 512 * 1024)
    try:
        if max_bytes:
            cap = min(int(max_bytes), cap)
    except (TypeError, ValueError):
        pass
    timeout = getattr(config, "WEB_FETCH_TIMEOUT_S", 20)
    try:
        with requests.get(
            u, stream=True, timeout=timeout, allow_redirects=True,
            headers={"User-Agent": _WEB_FETCH_UA,
                     "Accept": "text/html,text/plain,application/json,*/*"},
        ) as r:
            r.raise_for_status()
            # Re-walidacja PO przekierowaniach (anti-SSRF: allowed host → blocked redirect).
            final = urlparse(r.url)
            if (r.url or "").lower()[:8] != "https://" or _web_host_blocked(final.hostname or ""):
                return f"Error: web_fetch refused redirect to '{r.url}'"
            if allow and not _web_host_allowed(final.hostname or "", allow):
                return f"Error: redirect host '{final.hostname}' is not in the allowlist"
            ctype = (r.headers.get("content-type") or "").lower()
            data = bytearray()
            for chunk in r.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                data.extend(chunk)
                if len(data) >= cap:
                    break
    except Exception as exc:  # noqa: BLE001 (sieć od modelu — komunikat generyczny, log surowy)
        log.warning("web_fetch failed for %s", u, exc_info=True)
        return f"Error: web_fetch failed ({type(exc).__name__})"
    truncated = len(data) >= cap
    text = bytes(data[:cap]).decode("utf-8", "replace")
    if "html" in ctype:
        text = _html_to_text(text)
    if not text.strip():
        return "(empty response)"
    return text + ("\n… (truncated)" if truncated else "")


_EXECUTORS = {
    "read_file": read_file,
    "list_dir": list_dir,
    "glob": glob,
    "grep": grep,
    "write_file": write_file,
    "edit_file": edit_file,
    "run_command": run_command,
    "web_fetch": web_fetch,  # M19-B13 (advertowane warunkowo w session._all_tools)
}


def execute_tool(ws: Workspace, name: str, args: dict,
                 on_output: Optional[Callable[[str], None]] = None,
                 stop_flag: Optional[Callable[[], bool]] = None,
                 rule_filter: Optional[Callable[[str], bool]] = None) -> str:
    fn = _EXECUTORS.get(name)
    if fn is None:
        return f"Error: unknown tool {name}"
    kwargs = dict(args or {})
    if name == "run_command":
        kwargs["on_output"] = on_output
        kwargs["stop_flag"] = stop_flag
    # P1-B: reguły `deny` egzekwowane też na WYNIKACH narzędzi przeszukujących —
    # bez tego `grep`/`glob`/`list_dir` zwracały treść/nazwy z deny-listowanych ścieżek.
    if rule_filter is not None and name in ("grep", "glob", "list_dir"):
        kwargs["rule_filter"] = rule_filter
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
    """Buduje opis zmiany do zatwierdzenia (M13-B1): unified diff dla write/edit,
    komenda dla run. Nowy plik → diff jako same dodania (`created`). Plik binarny
    (bajt NUL) → znacznik „binary" + rozmiar zamiast nieczytelnego diffa."""
    try:
        if name in ("write_file", "edit_file"):
            p = ws.resolve(args["path"])
            exists = p.exists() and p.is_file()
            # P0-7/B1: nadpisanie pliku binarnego — nie generuj śmieciowego diffa.
            if exists and _is_binary(p):
                try:
                    size = p.stat().st_size
                except OSError:
                    size = 0
                return {"kind": "binary", "path": args["path"], "bytes": size,
                        "detail": f"binary file ({size} bytes) would be overwritten"}
            old = p.read_text(encoding="utf-8", errors="replace") if exists else ""
            if name == "write_file":
                new = args.get("content", "")
            else:
                os_, ns = args.get("old_string", ""), args.get("new_string", "")
                new = old.replace(os_, ns) if args.get("replace_all") else old.replace(os_, ns, 1)
            return {"kind": "diff", "path": args["path"], "created": not exists,
                    "diff": _udiff(old, new, args["path"])}
        if name == "run_command":
            return {"kind": "command", "command": args.get("command", ""), "cwd": args.get("cwd")}
        if name == "web_fetch":  # M19-B13: karta zatwierdzenia egresu sieciowego
            return {"kind": "web_fetch", "url": args.get("url", "")}
    except Exception as exc:  # noqa: BLE001
        return {"kind": "error", "detail": str(exc)}
    return None
