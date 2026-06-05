"""Worktree mutujących subagentów (M17-B3/B4) — izolacja + scalanie.

Decyzja przekrojowa (PLAN_M17 §5, spójnie z checkpointem M13): worktree = **kopia
katalogu** workspace (bez zależności od gita; działa też gdy workspace nie jest
repo). Mutujący subagent (implementer/tester) pracuje na kopii; jego zmiany NIE
dotykają realnego workspace, dopóki użytkownik nie zatwierdzi **jednego diffa**
przy scalaniu (B4) — to rozwiązuje „approval fatigue" przy wielu subagentach.

Bezpieczeństwo:
- kopia POMIJA `IGNORE_DIRS` (.git/.grok/node_modules/.venv/…) — szybciej i bez
  rekurencji w magazyn checkpointów; **pomija dowiązania** (symlink/junction), więc
  worktree nie wciąga niczego spoza workspace.
- scalanie rozwiązuje każdą ścieżkę przez `Workspace.resolve` (sandbox — brak
  ucieczki) i **snapshotuje oryginał do checkpointu** (M13) → scalenie jest cofalne.
- konflikt = ta sama ścieżka zmieniona przez >1 worktree (wykrywane w MergeStore).
"""

from __future__ import annotations

import difflib
import logging
import os
import shutil
from pathlib import Path
from typing import Optional

from caelo_core.agent.tools import IGNORE_DIRS, atomic_write_bytes
from caelo_core.agent.workspace import Workspace

log = logging.getLogger(__name__)

# Kopiowanie/diff dużych lub binarnych plików — limity zdroworozsądkowe.
_DIFF_MAX_BYTES = 2 * 1024 * 1024   # powyżej: znacznik zamiast tekstowego diffa
_BINARY_SNIFF = 4096


def _is_binary_bytes(data: bytes) -> bool:
    return b"\x00" in data[:_BINARY_SNIFF]


def copy_worktree(src_root: Path, dest_root: Path) -> None:
    """Skopiuj `src_root` do `dest_root`, pomijając IGNORE_DIRS i dowiązania.
    `dest_root` musi nie istnieć (świeża kopia)."""
    src_root = Path(src_root)
    dest_root = Path(dest_root)
    dest_root.mkdir(parents=True, exist_ok=True)
    for dirpath, dirnames, filenames in os.walk(src_root, followlinks=False):
        # nie wchodź w IGNORE_DIRS ani w dowiązane katalogi (junction/symlink)
        dirnames[:] = [
            d for d in dirnames
            if d not in IGNORE_DIRS and not os.path.islink(os.path.join(dirpath, d))
        ]
        rel_dir = os.path.relpath(dirpath, src_root)
        target_dir = dest_root if rel_dir == "." else dest_root / rel_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        for fn in filenames:
            sp = os.path.join(dirpath, fn)
            if os.path.islink(sp):  # pomijaj pliki-dowiązania (mogą wskazywać poza root)
                continue
            try:
                shutil.copy2(sp, target_dir / fn)
            except OSError:
                log.warning("worktree copy skipped %s", sp, exc_info=True)


def _rel_files(root: Path) -> set[str]:
    """Względne ścieżki plików (POSIX) pod `root`, pomijając IGNORE_DIRS/dowiązania."""
    out: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [
            d for d in dirnames
            if d not in IGNORE_DIRS and not os.path.islink(os.path.join(dirpath, d))
        ]
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            if os.path.islink(p):
                continue
            out.add(os.path.relpath(p, root).replace(os.sep, "/"))
    return out


def _read(p: Path) -> Optional[bytes]:
    try:
        return p.read_bytes()
    except OSError:
        return None


def _file_diff(rel: str, old: Optional[bytes], new: Optional[bytes]) -> tuple[str, str]:
    """Zwróć (kind, unified-diff-text) dla jednego pliku. kind ∈
    created|modified|deleted (+ wariant binarny → marker zamiast śmieciowego diffa)."""
    if old is None and new is not None:
        kind = "created"
    elif old is not None and new is None:
        kind = "deleted"
    else:
        kind = "modified"

    big = (len(old or b"") > _DIFF_MAX_BYTES) or (len(new or b"") > _DIFF_MAX_BYTES)
    binary = _is_binary_bytes(old or b"") or _is_binary_bytes(new or b"")
    if binary or big:
        size = len((new if new is not None else old) or b"")
        marker = f"# {kind}: {rel} ({'binary' if binary else 'large'} file, {size} bytes)\n"
        return kind, marker

    old_t = (old or b"").decode("utf-8", "replace").splitlines(keepends=True)
    new_t = (new or b"").decode("utf-8", "replace").splitlines(keepends=True)
    diff = "".join(difflib.unified_diff(old_t, new_t, fromfile=f"a/{rel}", tofile=f"b/{rel}"))
    return kind, diff or f"# {kind}: {rel} (no textual change)\n"


def compute_changes(orig_root: Path, wt_root: Path) -> dict:
    """Porównaj worktree z oryginałem. Zwraca:
    {files:[{path,kind}], diff:str, paths:[rel]} — `diff` to złączony unified diff
    wszystkich zmienionych plików (do przeglądu jako JEDEN diff, B4)."""
    orig_root, wt_root = Path(orig_root), Path(wt_root)
    orig_files = _rel_files(orig_root)
    wt_files = _rel_files(wt_root)

    files: list[dict] = []
    chunks: list[str] = []
    for rel in sorted(wt_files | orig_files):
        old = _read(orig_root / rel) if rel in orig_files else None
        new = _read(wt_root / rel) if rel in wt_files else None
        if old == new:
            continue  # bez zmian
        kind, diff = _file_diff(rel, old, new)
        files.append({"path": rel, "kind": kind})
        chunks.append(diff)
    return {"files": files, "diff": "".join(chunks), "paths": [f["path"] for f in files]}


def apply_changes(workspace: Workspace, wt_root: Path, files: list[dict],
                  checkpoints=None, label: str = "") -> dict:
    """Zastosuj zmiany worktree do realnego workspace. Każda ścieżka przez sandbox
    (`Workspace.resolve`); oryginał snapshotowany do checkpointu (M13) → scalenie
    cofalne. Zwraca {applied, deleted, skipped}."""
    wt_root = Path(wt_root)
    applied: list[str] = []
    deleted: list[str] = []
    skipped: list[str] = []

    if checkpoints is not None:
        try:
            checkpoints.begin_turn(label=label or "Merge subagent changes")
        except Exception:  # noqa: BLE001
            checkpoints = None

    for entry in files:
        rel = entry.get("path") or ""
        kind = entry.get("kind") or "modified"
        try:
            target = workspace.resolve(rel)  # sandbox: odrzuca ucieczki
        except Exception:  # noqa: BLE001 (WorkspaceError)
            skipped.append(rel)
            continue
        if checkpoints is not None:
            try:
                checkpoints.snapshot(rel)  # zapisz oryginał przed nadpisaniem/usunięciem
            except Exception:  # noqa: BLE001
                pass
        try:
            if kind == "deleted":
                if target.exists():
                    target.unlink()
                deleted.append(rel)
            else:  # created / modified
                data = (wt_root / rel).read_bytes()
                atomic_write_bytes(target, data)
                applied.append(rel)
        except OSError:
            log.warning("merge could not apply %s", rel, exc_info=True)
            skipped.append(rel)

    return {"applied": applied, "deleted": deleted, "skipped": skipped}


def discard_worktree(wt_root: Path) -> None:
    """Usuń katalog worktree (odrzucenie scalenia / sprzątanie)."""
    try:
        shutil.rmtree(wt_root, ignore_errors=True)
    except Exception:  # noqa: BLE001
        pass
