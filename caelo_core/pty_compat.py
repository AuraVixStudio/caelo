"""Abstrakcja PTY cross-platform (M15-5).

Terminal (`/terminal`) potrzebuje pseudo-terminala. Na Windows jedyną sensowną
opcją jest **pywinpty** (ConPTY); na Unix wystarcza **stdlib** `pty`+`os`+`termios`+
`fcntl` (zero nowych zależności). Ten moduł wystawia JEDEN interfejs `open_pty()`
zwracający obiekt o API zgodnym z `winpty.PtyProcess`
(`read`/`write`/`setwinsize`/`isalive`/`terminate`), więc `routes/terminal.py`
nie musi znać platformy.

Zasady przekrojowe M15:
  • **Import bez efektów ubocznych na każdej platformie.** Na Windows `winpty`
    ładujemy LENIWIE w `open_pty()` (nie na imporcie), a stdlib `termios`/`fcntl`/
    `pty` (Unix-only) importujemy tylko w gałęzi non-Windows — dzięki temu sidecar
    importuje się czysto także pod Pythonem na Unix (audyt M15-7).
  • **Scrubbed env** (P0-11) nakłada wywołujący — tu tylko przekazujemy `env=`.
  • Brak PTY (np. pywinpty niezainstalowany) → `PtyUnavailable` z instrukcją.
"""

from __future__ import annotations

import os
import sys
from typing import Optional


class PtyUnavailable(RuntimeError):
    """PTY niedostępne na tej platformie/instalacji (np. brak pywinpty na Windows)."""


# --- Unix: implementacja na stdlib (pty/termios/fcntl) ---------------------------
if sys.platform != "win32":
    import fcntl
    import pty
    import signal
    import struct
    import subprocess
    import termios

    class UnixPtyProcess:
        """Cienki PTY na stdlib o API zgodnym z `winpty.PtyProcess`.

        `pty.openpty()` daje parę (master, slave); proces dziecko dostaje slave jako
        stdin/stdout/stderr, my czytamy/zapisujemy master. `start_new_session=True`
        nadaje własną grupę procesów → `terminate()` może ubić CAŁE drzewo przez
        `killpg` (spójne z tree-kill `run_command`, M15-6)."""

        def __init__(self, proc: "subprocess.Popen", master_fd: int) -> None:
            self._proc = proc
            self._fd = master_fd

        @classmethod
        def spawn(cls, argv, cwd: Optional[str] = None,
                  env: Optional[dict] = None) -> "UnixPtyProcess":
            if isinstance(argv, str):
                argv = [argv]
            master_fd, slave_fd = pty.openpty()
            try:
                proc = subprocess.Popen(
                    argv, cwd=cwd, env=env,
                    stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
                    start_new_session=True,  # własna grupa procesów (sygnały/tree-kill)
                    close_fds=True,
                )
            finally:
                os.close(slave_fd)  # rodzic używa tylko master
            return cls(proc, master_fd)

        def isalive(self) -> bool:
            return self._proc.poll() is None

        def read(self, size: int = 1024) -> str:
            try:
                data = os.read(self._fd, size)
            except OSError:
                return ""  # master zamknięty (proces zakończony)
            return data.decode("utf-8", errors="replace")

        def write(self, data: str) -> None:
            os.write(self._fd, data.encode("utf-8"))

        def setwinsize(self, rows: int, cols: int) -> None:
            winsize = struct.pack("HHHH", int(rows), int(cols), 0, 0)
            fcntl.ioctl(self._fd, termios.TIOCSWINSZ, winsize)

        def terminate(self, force: bool = False) -> None:
            if self._proc.poll() is None:
                sig = signal.SIGKILL if force else signal.SIGTERM
                try:
                    os.killpg(os.getpgid(self._proc.pid), sig)  # ubij grupę (drzewo)
                except OSError:
                    try:
                        self._proc.kill()
                    except OSError:
                        pass
            try:
                os.close(self._fd)
            except OSError:
                pass


def open_pty(shell, cwd: Optional[str] = None, env: Optional[dict] = None):
    """Uruchom shell w PTY i zwróć obiekt zgodny z `winpty.PtyProcess`.

    Windows → pywinpty (ładowane leniwie; brak → `PtyUnavailable`).
    Unix    → `UnixPtyProcess` (stdlib)."""
    if sys.platform == "win32":
        try:
            from winpty import PtyProcess  # type: ignore  # lazy: tylko gdy faktycznie startujemy PTY
        except Exception as exc:  # noqa: BLE001
            raise PtyUnavailable(
                "Terminal unavailable: install 'pywinpty' in the backend venv."
            ) from exc
        return PtyProcess.spawn(shell, cwd=cwd, env=env)
    return UnixPtyProcess.spawn(shell, cwd=cwd, env=env)
