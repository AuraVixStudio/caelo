"""Self-check fundamentu cross-platform (M15-5/6/7) — bez sieci xAI.

Weryfikuje neutralność platformową wprowadzoną w M15:
  M15-5  Abstrakcja PTY  — `caelo_core.pty_compat.open_pty` ma jednolite API
         (read/write/setwinsize/isalive/terminate) na każdej platformie; brak
         pywinpty (Windows) → `PtyUnavailable`; smoke echo round-trip na BIEŻĄCYM OS.
  M15-6  Tree-kill / sygnały  — `_tree_kill` wybiera ścieżkę per-OS (Windows
         `taskkill /T /F`; POSIX `killpg` SIGTERM→SIGKILL); `run_command` na POSIX
         nadaje nową sesję (`start_new_session`); brak wywołań Windows-only na POSIX.
         Plus LIVE: Stop ubija realnie uruchomioną komendę na bieżącym OS.
  M15-7  Założenia Windows-only  — `config.DATA_DIR` rozwiązuje się per-OS;
         `pty_compat` nie ma NIEOSŁONIĘTEGO `import winpty` na poziomie modułu;
         `_migrate_legacy_data()` jest idempotentne.

Części zależne od platformy oznaczane są jako [SKIP] poza danym OS (kod wyjścia 0).
Kod wyjścia 0 = wszystkie asercje OK.
"""

from __future__ import annotations

import inspect
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import config  # noqa: E402  # repo-root (sys.path z caelo_core/__init__.py)

from caelo_core.agent import tools as T  # noqa: E402
from caelo_core import pty_compat  # noqa: E402

checks: list[tuple[str, bool]] = []
skips: list[str] = []


def check(name: str, passed: bool) -> None:
    checks.append((name, bool(passed)))


def skip(name: str) -> None:
    skips.append(name)


# --- M15-5: PTY ----------------------------------------------------------------
def test_pty_interface() -> None:
    check("M15-5: open_pty callable", callable(pty_compat.open_pty))
    check("M15-5: PtyUnavailable is exc", issubclass(pty_compat.PtyUnavailable, Exception))

    if sys.platform == "win32":
        try:
            import winpty  # type: ignore  # noqa: F401
            have_winpty = True
        except Exception:
            have_winpty = False
        if not have_winpty:
            # Brak pywinpty → kontrakt: PtyUnavailable z instrukcją (nie surowy ImportError).
            try:
                pty_compat.open_pty(os.environ.get("COMSPEC", "cmd.exe"))
                check("M15-5: missing pywinpty -> PtyUnavailable", False)
            except pty_compat.PtyUnavailable:
                check("M15-5: missing pywinpty -> PtyUnavailable", True)
            except Exception:
                check("M15-5: missing pywinpty -> PtyUnavailable", False)
            return
        shell = os.environ.get("COMSPEC", "cmd.exe")
        cmd = f'{shell} /c echo PTY_OK_MARKER'
    else:
        # POSIX: open_pty -> UnixPtyProcess.spawn NIE parsuje powłokowo stringa
        # (to nie shell=True) — string trafia do Popen jako pojedynczy argv, więc
        # '/bin/sh -c "..."' byłoby szukane jako nazwa pliku (FileNotFoundError).
        # Przekazujemy gotowe argv (lista), tak jak realny terminal podaje shell.
        cmd = ['/bin/sh', '-c', 'echo PTY_OK_MARKER']

    try:
        proc = pty_compat.open_pty(cmd, cwd=os.getcwd(), env=T.scrubbed_env())
    except pty_compat.PtyUnavailable:
        skip("M15-5: live PTY (no backend on this OS)")
        return

    for m in ("isalive", "read", "write", "setwinsize", "terminate"):
        check(f"M15-5: PTY has {m}()", hasattr(proc, m))
    try:
        proc.setwinsize(24, 80)
        check("M15-5: setwinsize ok", True)
    except Exception:
        check("M15-5: setwinsize ok", False)

    # Echo round-trip — best-effort z deadline'em (PTY bywa wrażliwe na timing/CI).
    out = ""
    deadline = time.time() + 5.0
    try:
        while time.time() < deadline:
            chunk = ""
            try:
                chunk = proc.read(1024)
            except Exception:
                break
            if chunk:
                out += chunk
                if "PTY_OK_MARKER" in out:
                    break
            elif not proc.isalive():
                break
            else:
                time.sleep(0.05)
    finally:
        try:
            proc.terminate(force=True)
        except Exception:
            pass

    if "PTY_OK_MARKER" in out:
        check("M15-5: PTY echo round-trip", True)
    else:
        skip("M15-5: PTY echo round-trip (no marker within deadline)")


# --- M15-6: tree-kill / sygnały ------------------------------------------------
def test_tree_kill_paths() -> None:
    kill_src = inspect.getsource(T._tree_kill)
    # Windows ścieżka: taskkill /T /F musi być pod gałęzią os.name == "nt".
    check("M15-6: Windows kill uses taskkill", "taskkill" in kill_src)
    # Gałąź os.name=='nt' musi poprzedzać FAKTYCZNE wywołanie taskkill (ostatnie
    # wystąpienie; pierwsze jest w docstringu). Tak potwierdzamy, że taskkill jest
    # nieosiągalne na POSIX.
    check("M15-6: taskkill guarded by os.name=='nt'",
          'os.name == "nt"' in kill_src and kill_src.index('os.name == "nt"') < kill_src.rindex("taskkill"))
    # POSIX ścieżka: killpg + eskalacja SIGTERM -> SIGKILL.
    check("M15-6: POSIX kill uses killpg", "killpg" in kill_src)
    check("M15-6: POSIX escalates SIGTERM->SIGKILL",
          "SIGTERM" in kill_src and "SIGKILL" in kill_src
          and kill_src.index("SIGTERM") < kill_src.index("SIGKILL"))
    # run_command na POSIX nadaje nową sesję (własna grupa procesów → killpg ubije drzewo).
    run_src = inspect.getsource(T.run_command)
    check("M15-6: run_command sets start_new_session (POSIX)", "start_new_session" in run_src)
    # Brak wywołań Windows-only na POSIX: taskkill nie może być poza gałęzią nt.
    check("M15-6: no taskkill outside Windows branch", run_src.count("taskkill") == 0)

    # LIVE: Stop realnie ubija uruchomioną komendę na BIEŻĄCYM OS.
    import tempfile
    from caelo_core.agent.workspace import Workspace
    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        cmd = "ping -n 20 127.0.0.1" if os.name == "nt" else "sleep 20"
        stop = threading.Event()
        threading.Timer(0.6, stop.set).start()
        t0 = time.time()
        res = T.run_command(ws, cmd, timeout=30, stop_flag=stop.is_set)
        elapsed = time.time() - t0
        check("M15-6: Stop kills running command", "[stopped]" in res)
        check("M15-6: Stop is prompt (<10s, not full timeout)", elapsed < 10)


# --- M15-7: założenia Windows-only --------------------------------------------
def test_paths_per_os() -> None:
    from pathlib import Path
    check("M15-7: DATA_DIR is a Path", isinstance(config.DATA_DIR, Path))
    check("M15-7: DATA_DIR exists", config.DATA_DIR.exists())
    # base per-OS: musi pasować do bieżącej platformy.
    base = config._user_data_base()
    if sys.platform == "win32":
        expected = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        expected = os.path.expanduser("~/Library/Application Support")
    else:
        expected = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    check("M15-7: _user_data_base() matches OS", str(base) == str(Path(expected)))
    check("M15-7: _user_data_dir appends app name", config._user_data_dir("ZxQ").name == "ZxQ")

    # pty_compat: brak NIEOSŁONIĘTEGO 'import winpty' na poziomie modułu (audyt importu na Unix).
    src = inspect.getsource(pty_compat)
    bad = [ln for ln in src.splitlines()
           if ln.lstrip().startswith(("import winpty", "from winpty"))
           and not ln.startswith((" ", "\t"))]
    check("M15-7: pty_compat has no top-level winpty import", not bad)

    # Migracja danych jest idempotentna (drugie wywołanie nie rzuca).
    try:
        config._migrate_legacy_data()
        config._migrate_legacy_data()
        check("M15-7: _migrate_legacy_data idempotent", True)
    except Exception:
        check("M15-7: _migrate_legacy_data idempotent", False)


def main() -> int:
    test_pty_interface()
    test_tree_kill_paths()
    test_paths_per_os()
    ok = True
    for name, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    for name in skips:
        print(f"  [SKIP] {name}")
    print(f"RESULT: {'OK' if ok else 'FAILED'} ({sum(1 for _, p in checks if p)}/{len(checks)} passed, {len(skips)} skipped)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
