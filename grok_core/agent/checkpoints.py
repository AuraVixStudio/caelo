"""Checkpointy plików agenta (M13-B3) — „cofnij to, co zrobił agent".

Decyzja przekrojowa (PLAN_M13): checkpoint = **kopia śledzonych plików**, BEZ
zależności od gita (cross-platform, działa też gdy workspace nie jest repo).

Model:
  • Checkpoint otwierany jest LENIWIE — dopiero przy pierwszej mutacji w turze
    (tura czysto czytająca / tryb planowania NIE tworzy checkpointu).
  • Przed pierwszą modyfikacją danej ścieżki w checkpoincie kopiujemy oryginał do
    `.grok/checkpoints/<session_id>/<cp_id>/<idx>.bak` (lub oznaczamy „created",
    gdy pliku jeszcze nie było). Manifest (`manifest.json`) zapisywany ATOMOWO po
    każdej zmianie — crash w trakcie tury nie psuje możliwości undo.
  • Undo do checkpointu X = odtworzenie stanu sprzed X przez odtworzenie kopii z
    checkpointów X..N w KOLEJNOŚCI ODWROTNEJ (najnowszy → X): każdy checkpoint
    cofa pliki do stanu sprzed SIEBIE, więc łańcuch od końca daje stan sprzed X.
    „created" → usunięcie pliku. Domyślne undo (bez id) cofa CAŁĄ sesję.

Wszystkie ścieżki przechodzą przez sandbox (muszą zostać pod korzeniem workspace,
po rozwinięciu symlinków/junctionów) — restore nie może pisać poza workspace.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import shutil
import time
from pathlib import Path
from typing import Callable, Optional

import config  # type: ignore  # repo-root (sys.path z grok_core/__init__.py)

from grok_core.agent.tools import atomic_write_bytes

log = logging.getLogger(__name__)

CHECKPOINT_DIRNAME = ".grok"
MAX_SESSIONS_RETAINED = 20  # retencja: ile katalogów sesji zostawić (reszta usuwana)


def _norm_rel(path: str) -> str:
    """Znormalizuj ścieżkę względną do stabilnego klucza (jak permissions._norm_path)."""
    path = (path or "").strip()
    if not path:
        return ""
    return os.path.normpath(path).replace("\\", "/")


class CheckpointManager:
    """Checkpointy dla JEDNEGO workspace + JEDNEJ sesji (per WS connection / run)."""

    def __init__(self, root: Path | str, session_id: Optional[str] = None,
                 on_event: Optional[Callable[[dict], None]] = None) -> None:
        self.root = Path(root).resolve()
        self.session_id = session_id or secrets.token_hex(8)
        self._base = self.root / CHECKPOINT_DIRNAME / "checkpoints" / self.session_id
        self.on_event = on_event  # callback(dict) gdy powstaje nowy checkpoint (WS event)
        self._checkpoints: list[dict] = []
        self._current: Optional[dict] = None        # otwarty checkpoint (lub None)
        self._pending_label: str = ""               # etykieta następnego checkpointu
        self._session_has_command = False           # tura uruchomiła run_command → „partial undo"
        self._retain()

    # --- sandbox ---
    def _within_root(self, p: Path) -> bool:
        try:
            real = p.resolve()
        except OSError:
            return False
        return real == self.root or self.root in real.parents

    # --- otwieranie checkpointów (leniwe) ---
    def begin_turn(self, label: str = "") -> None:
        """Zamknij bieżący checkpoint i ustaw etykietę następnego. Sam checkpoint
        powstanie dopiero przy pierwszej mutacji (`snapshot`) — tura bez zmian go
        nie tworzy (spójne z trybem planowania: „plan nie tworzy checkpointu")."""
        self._current = None
        self._pending_label = (label or "").strip().replace("\n", " ")[:200]

    def _ensure_current(self) -> dict:
        if self._current is None:
            cp = {
                "id": secrets.token_hex(6),
                "label": self._pending_label,
                "created_at": int(time.time()),
                "has_command": False,
                "entries": [],  # [{rel, kind: modified|created, backup}]
            }
            self._checkpoints.append(cp)
            self._current = cp
            self._save()
            if self.on_event:
                try:
                    self.on_event({"type": "checkpoint", "id": cp["id"],
                                   "label": cp["label"], "created_at": cp["created_at"]})
                except Exception:  # noqa: BLE001
                    pass
        return self._current

    # --- snapshot przed mutacją ---
    def snapshot(self, rel_path: str) -> None:
        """Zapisz oryginał `rel_path` przed jego modyfikacją (idempotentne w obrębie
        bieżącego checkpointu). Plik istniejący → kopia + „modified"; brak → „created"."""
        rel = _norm_rel(rel_path)
        if not rel or rel == ".":
            return
        src = self.root / rel
        if not self._within_root(src):  # sandbox: nigdy nie kopiuj spoza workspace
            return
        cp = self._ensure_current()
        if any(e["rel"] == rel for e in cp["entries"]):
            return  # już zsnapshotowane w tym checkpoincie
        try:
            if src.exists() and src.is_file():
                idx = len(cp["entries"])
                backup = f"{cp['id']}/{idx}.bak"
                dst = self._base / backup
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                cp["entries"].append({"rel": rel, "kind": "modified", "backup": backup})
            else:
                cp["entries"].append({"rel": rel, "kind": "created", "backup": None})
            self._save()
        except OSError:
            log.warning("Checkpoint snapshot failed for %s", rel, exc_info=True)

    def mark_command(self) -> None:
        """Oznacz, że tura uruchomiła `run_command` (zmiany komendy są poza
        śledzeniem → undo będzie „częściowy"). Nie tworzy pustego checkpointu —
        flaguje sesję, a jeśli checkpoint już otwarty, także jego."""
        self._session_has_command = True
        if self._current is not None and not self._current["has_command"]:
            self._current["has_command"] = True
            self._save()

    # --- przegląd ---
    def list(self) -> dict:
        return {
            "session_id": self.session_id,
            "partial": self._session_has_command,
            "checkpoints": [
                {"id": c["id"], "label": c["label"], "created_at": c["created_at"],
                 "files": len(c["entries"]), "has_command": c["has_command"]}
                for c in self._checkpoints
            ],
        }

    # --- undo ---
    def undo_to(self, checkpoint_id: Optional[str] = None) -> dict:
        """Cofnij do checkpointu `checkpoint_id` (domyślnie: cała sesja). Odtwarza
        kopie z checkpointów [idx:] w kolejności odwrotnej; „created" → usuwa plik."""
        if not self._checkpoints:
            return {"ok": True, "restored": [], "deleted": [], "missing": [],
                    "partial": self._session_has_command, "checkpoints_undone": 0}
        if checkpoint_id is None:
            idx = 0
        else:
            idx = next((i for i, c in enumerate(self._checkpoints)
                        if c["id"] == checkpoint_id), None)
            if idx is None:
                raise ValueError("Unknown checkpoint")

        to_undo = self._checkpoints[idx:]
        restored: list[str] = []
        deleted: list[str] = []
        missing: list[str] = []
        partial = self._session_has_command

        for cp in reversed(to_undo):
            if cp["has_command"]:
                partial = True
            for e in reversed(cp["entries"]):
                target = self.root / e["rel"]
                if not self._within_root(target):  # sandbox (symlink/junction)
                    missing.append(e["rel"])
                    continue
                if e["kind"] == "modified":
                    bak = self._base / (e["backup"] or "")
                    if e["backup"] and bak.exists():
                        try:
                            atomic_write_bytes(target, bak.read_bytes())
                            restored.append(e["rel"])
                        except OSError:
                            missing.append(e["rel"])
                    else:
                        missing.append(e["rel"])
                else:  # created → usuń, jeśli istnieje
                    try:
                        if target.exists():
                            target.unlink()
                            deleted.append(e["rel"])
                    except OSError:
                        missing.append(e["rel"])

        # odetnij cofnięte checkpointy + posprzątaj ich kopie zapasowe
        self._checkpoints = self._checkpoints[:idx]
        self._current = None
        self._save()
        for cp in to_undo:
            shutil.rmtree(self._base / cp["id"], ignore_errors=True)

        return {"ok": True, "restored": restored, "deleted": deleted, "missing": missing,
                "partial": partial, "checkpoints_undone": len(to_undo)}

    # --- trwałość manifestu ---
    def _save(self) -> None:
        try:
            self._base.mkdir(parents=True, exist_ok=True)
            config.atomic_write_text(
                self._base / "manifest.json",
                json.dumps({
                    "session_id": self.session_id,
                    "has_command": self._session_has_command,
                    "checkpoints": self._checkpoints,
                }, indent=2),
            )
        except Exception:  # noqa: BLE001
            log.warning("Could not persist checkpoint manifest", exc_info=True)

    # --- retencja: nie pozwól, by .grok/checkpoints rosło bez końca ---
    def _retain(self) -> None:
        try:
            parent = self.root / CHECKPOINT_DIRNAME / "checkpoints"
            if not parent.is_dir():
                return
            dirs = [d for d in parent.iterdir() if d.is_dir() and d.name != self.session_id]
            dirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
            for stale in dirs[MAX_SESSIONS_RETAINED:]:
                shutil.rmtree(stale, ignore_errors=True)
        except OSError:
            pass
