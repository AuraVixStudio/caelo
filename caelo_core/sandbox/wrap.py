"""Owijanie komendy launcherem sandboxa OS (M19-B7).

`wrap(argv, profile, root)` → argv' opakowane platformowym launcherem:
- **Linux:** `bwrap` (bubblewrap), jeśli na PATH; inaczej **no-op + ostrzeżenie**
  (jak Grok CLI — loguje i kontynuuje bez egzekucji; Landlock-ctypes = odłożone).
- **macOS:** `sandbox-exec -p '<seatbelt>'` z profilem generowanym z `Profile`.
- **Windows / inne:** best-effort **no-op** (mamy już Job/tree-kill; brak FS-sandboxa).

Funkcje są PURE (bez I/O) — testowalne przez wymuszenie `platform`/`which`. Zdarzenia
(profil zastosowany / no-op + powód) loguje osobny `log_event()` wołany w miejscu wpięcia.

⚠️ Realna egzekucja (Landlock/Seatbelt/bwrap blokuje zapis) weryfikowana na Linux/macOS
użytkownika — sandbox CI (Windows) sprawdza tylko poprawność budowanego argv.
"""

from __future__ import annotations

import json
import logging
import shutil
import sys
import time
from pathlib import Path
from typing import Callable, List, Optional

import config  # type: ignore

from caelo_core.sandbox.profiles import Profile, resolve_profile

log = logging.getLogger(__name__)

# Minimalne katalogi systemowe montowane read-only w `strict` (by program dało się odpalić).
_STRICT_RO_SYSTEM = ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc")


def _sb_quote(p: str) -> str:
    return '"' + p.replace("\\", "\\\\").replace('"', '\\"') + '"'


def seatbelt_profile(profile: Profile) -> str:
    """Wygeneruj politykę Seatbelt (.sb) z `Profile`. Reguły ewaluowane top-down,
    wygrywa OSTATNIE dopasowanie → deny ścieżek wrażliwych idą na końcu."""
    parts: List[str] = ["(version 1)", "(allow default)",
                        "(allow process-exec)", "(allow process-fork)"]
    if profile.restrict_network:
        parts.append("(deny network*)")
    if profile.read_all:
        parts.append("(allow file-read*)")
    else:  # strict — czytaj tylko wskazane korzenie
        parts.append("(deny file-read*)")
        for r in profile.read_paths:
            parts.append(f"(allow file-read* (subpath {_sb_quote(r)}))")
    parts.append("(deny file-write*)")
    for w in profile.write_paths:
        parts.append(f"(allow file-write* (subpath {_sb_quote(w)}))")
    for d in profile.deny_paths:  # zawsze zabronione (sekrety) — na końcu, by wygrały
        parts.append(f"(deny file* (subpath {_sb_quote(d)}))")
    return "\n".join(parts)


def _macos_argv(argv: List[str], profile: Profile) -> List[str]:
    return ["sandbox-exec", "-p", seatbelt_profile(profile), *argv]


def linux_bwrap_argv(argv: List[str], profile: Profile, *, root: Optional[str],
                     bwrap: str = "bwrap", exists: Callable[[str], bool] = None) -> List[str]:
    """Zbuduj argv `bwrap`. `exists` (test-injectable) decyduje, które ścieżki montować."""
    ex = exists or (lambda p: Path(p).exists())
    cmd: List[str] = [bwrap, "--die-with-parent", "--unshare-pid",
                      "--proc", "/proc", "--dev", "/dev"]
    if profile.read_all:
        cmd += ["--ro-bind", "/", "/"]
    else:  # strict — tylko minimalny system RO (do uruchomienia programu)
        for p in _STRICT_RO_SYSTEM:
            if ex(p):
                cmd += ["--ro-bind", p, p]
    # Zapisywalne korzenie (rebind RW — nadpisuje ro-bind).
    for w in profile.write_paths:
        if w and ex(w):
            cmd += ["--bind", w, w]
    if root and not profile.read_all and ex(root):
        cmd += ["--bind", root, root]  # strict: korzeń RW
    # Maskuj ścieżki wrażliwe (po bindach, by wygrały): katalog → tmpfs, plik → /dev/null.
    for d in profile.deny_paths:
        if not d or not ex(d):
            continue
        if Path(d).is_dir():
            cmd += ["--tmpfs", d]
        else:
            cmd += ["--ro-bind", "/dev/null", d]
    if profile.restrict_network:
        cmd += ["--unshare-net"]
    cmd += ["--", *argv]
    return cmd


def wrap(argv, profile: Profile, *, root: Optional[str] = None,
         platform: Optional[str] = None,
         which: Optional[Callable[[str], Optional[str]]] = None) -> List[str]:
    """Owiń `argv` launcherem sandboxa wg `profile`. `off`/pusty argv → bez zmian.
    `platform`/`which` wymuszalne (testy). Brak launchera → no-op (argv bez zmian)."""
    argv = list(argv)
    if not argv or profile.name == "off":
        return argv
    plat = platform or sys.platform
    if plat == "darwin":
        return _macos_argv(argv, profile)
    if plat.startswith("linux"):
        finder = which or shutil.which
        bwrap = finder("bwrap")
        if bwrap:
            return linux_bwrap_argv(argv, profile, root=root, bwrap=bwrap)
        log.warning("sandbox '%s' requested but bwrap not on PATH; running WITHOUT OS sandbox",
                    profile.name)
        return argv
    # Windows / inne: brak FS-sandboxa (Job/tree-kill już mamy)
    log.warning("sandbox '%s' requested but no OS sandbox on %s; running WITHOUT it",
                profile.name, plat)
    return argv


def wrap_command(argv, *, root: Optional[str] = None) -> List[str]:
    """Wygodne wejście dla miejsc wpięcia (run_command/MCP/LSP): rozstrzyga aktywny
    profil (`resolve_profile`) i owija. `off` (domyślny) → no-op (zero kosztu)."""
    prof = resolve_profile(root=root)
    if prof.name == "off":
        return list(argv)
    wrapped = wrap(argv, prof, root=root)
    log_event(prof.name, applied=(wrapped is not argv and wrapped != list(argv)), root=root)
    return wrapped


def log_event(profile_name: str, *, applied: bool, root: Optional[str] = None,
              reason: str = "") -> None:
    """Dopisz zdarzenie do `DATA_DIR/sandbox-events.jsonl` (best-effort, gitignored)."""
    try:
        rec = {"ts": time.time(), "profile": profile_name, "applied": bool(applied),
               "platform": sys.platform, "root": root or "", "reason": reason}
        path = Path(config.DATA_DIR) / "sandbox-events.jsonl"
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        log.debug("sandbox event log write failed", exc_info=True)
