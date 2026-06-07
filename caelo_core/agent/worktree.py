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
import subprocess
from pathlib import Path
from typing import Optional

from caelo_core.agent.tools import IGNORE_DIRS, atomic_write_bytes, scrubbed_env
from caelo_core.agent.workspace import Workspace

log = logging.getLogger(__name__)

# Kopiowanie/diff dużych lub binarnych plików — limity zdroworozsądkowe.
_DIFF_MAX_BYTES = 2 * 1024 * 1024   # powyżej: znacznik zamiast tekstowego diffa
_BINARY_SNIFF = 4096


def _is_binary_bytes(data: bytes) -> bool:
    return b"\x00" in data[:_BINARY_SNIFF]


# --- wariant git worktree (M19-B12) ---------------------------------------------
# Opcja obok kopii katalogu: gdy workspace jest TOP-LEVEL repo git, używamy realnego
# `git worktree` (szybszy, naturalny diff, respektuje .gitignore). Off-by-default —
# wybierane przez `config.AGENT_GIT_WORKTREE` / headless `--worktree`. Każda operacja
# git biegnie ze `scrubbed_env` (jak run_command/MCP), shell=False, z timeoutem; błąd →
# graceful fallback do kopii (defense-in-depth — nigdy nie wywraca delegacji).

def _git(args: list[str], cwd) -> tuple[int, str]:
    """Uruchom `git <args>` w `cwd` (scrubbed env, shell=False, timeout). Zwraca
    (returncode, stdout). Wyjątek/brak gita → (1, "")."""
    try:
        proc = subprocess.run(
            ["git", *args], cwd=str(cwd), env=scrubbed_env(),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", timeout=60,
        )
        return proc.returncode, proc.stdout
    except Exception:  # noqa: BLE001 (brak gita / timeout / OSError)
        return 1, ""


def is_git_repo(root) -> bool:
    """True, gdy `root` jest TOP-LEVEL repozytorium git (nie podkatalogiem) — tylko
    wtedy `git worktree` obejmuje dokładnie ten workspace, nie cały nadrzędny repo."""
    rc, out = _git(["rev-parse", "--show-toplevel"], cwd=root)
    if rc != 0 or not out.strip():
        return False
    try:
        return Path(out.strip()).resolve() == Path(root).resolve()
    except OSError:
        return False


def _git_worktree_add(src_root, dest_root) -> bool:
    """`git worktree add --detach <dest> HEAD`. Wymaga istniejącego HEAD (≥1 commit)
    i nieistniejącego `dest`. Zwraca True przy sukcesie."""
    dest = Path(dest_root)
    dest.parent.mkdir(parents=True, exist_ok=True)
    rc, _ = _git(["worktree", "add", "--detach", str(dest), "HEAD"], cwd=src_root)
    return rc == 0 and dest.exists()


def create_worktree(src_root, dest_root, *, use_git: bool = False) -> str:
    """Stwórz worktree dla subagenta. `use_git` + repo top-level + udany `git worktree
    add` → wariant 'git'; w każdym innym przypadku kopia katalogu (M17). Zwraca rodzaj
    ('git' | 'copy') — wołający użyje go przy compute_changes/discard."""
    if use_git and is_git_repo(src_root) and _git_worktree_add(src_root, dest_root):
        return "git"
    copy_worktree(src_root, dest_root)
    return "copy"


def _compute_changes_git(src_root, wt_root) -> Optional[dict]:
    """Zmiany w worktree git względem HEAD: `git add -A` + `git diff --cached`. Zwraca
    {files,diff,paths} (ten sam kształt co wariant kopii) albo None, gdy git zawiódł."""
    rc, _ = _git(["add", "-A"], cwd=wt_root)
    if rc != 0:
        return None
    rc, name_status = _git(["diff", "--cached", "--no-renames", "--name-status"], cwd=wt_root)
    if rc != 0:
        return None
    code_to_kind = {"A": "created", "M": "modified", "D": "deleted"}
    files: list[dict] = []
    for line in name_status.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        kind = code_to_kind.get(parts[0].strip()[:1])
        path = parts[1].strip()
        if kind and path:
            files.append({"path": path, "kind": kind})
    rc, diff = _git(["diff", "--cached"], cwd=wt_root)
    return {"files": files, "diff": diff if rc == 0 else "",
            "paths": [f["path"] for f in files]}


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


def compute_changes(orig_root: Path, wt_root: Path, *, kind: str = "copy") -> dict:
    """Porównaj worktree z oryginałem. Zwraca:
    {files:[{path,kind}], diff:str, paths:[rel]} — `diff` to złączony unified diff
    wszystkich zmienionych plików (do przeglądu jako JEDEN diff, B4). Kształt zwrotu
    JEST IDENTYCZNY dla obu wariantów (MergeStore/UI nie wiedzą, który użyto).
    M19-B12: `kind='git'` liczy zmiany przez `git diff` (vs HEAD); fallback do
    porównania drzew, gdy git zawiedzie."""
    if kind == "git":
        git_result = _compute_changes_git(orig_root, wt_root)
        if git_result is not None:
            return git_result
        log.warning("git worktree diff failed; falling back to tree compare")
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


def discard_worktree(wt_root: Path, *, kind: str = "copy", src_root=None) -> None:
    """Usuń worktree (odrzucenie scalenia / sprzątanie). M19-B12: dla wariantu 'git'
    użyj `git worktree remove --force` (+ `prune`), by nie zostawić wpisów admin w
    `.git/worktrees`; przy braku src_root lub porażce — fallback do rmtree."""
    if kind == "git" and src_root is not None:
        rc, _ = _git(["worktree", "remove", "--force", str(wt_root)], cwd=src_root)
        if rc == 0:
            _git(["worktree", "prune"], cwd=src_root)
            return
    try:
        shutil.rmtree(wt_root, ignore_errors=True)
    except Exception:  # noqa: BLE001
        pass
    if kind == "git" and src_root is not None:
        _git(["worktree", "prune"], cwd=src_root)  # sprzątnij wpis po rmtree
