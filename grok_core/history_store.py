"""M9-B1: trwały, przeszukiwalny magazyn artefaktów i historii (SQLite + FTS5).

Kręgosłup huba (`docs/PLAN_M9_SZKIELET.md`): jeden typ **Artifact** + zdarzenia
historii ze wszystkich trybów, pełnotekstowo przeszukiwalne (FTS5). `sqlite3` jest
w stdlib — zero nowych zależności; działa identycznie na Windows/macOS/Linux
(spójne z celem cross-platform).

Własność danych (CLAUDE.md): ten magazyn ma **własny plik** `grok_history.db` pod
`config.DATA_DIR` (IS_FROZEN → `%LOCALAPPDATA%`) i **NIE dotyka** `grok_config.json`
(należy wyłącznie do `HistoryManager`). Uszkodzona baza → backup `.corrupt`
(analogicznie do `config.load_json_or_backup`, P1-11), nie ciche wytarcie.

Współbieżność: sidecar jest async + wątki robocze; pojedyncze połączenie
(`check_same_thread=False`) serializowane przez `RLock`, tryb WAL. Zapisy są poza
gorącą pętlą użytkownika (B2 woła po zakończeniu strumienia).

API publiczne (stabilne dla B2/B3):
- `add_artifact(...) -> Artifact` / `get_artifact(id) -> Artifact|None`
- `record_event(...) -> HistoryEvent`
- `list_events(q=, mode=, project_id=, since=, until=, limit=, offset=) -> [HistoryEvent]`
- `list_artifacts(...)` / `get_store()` (leniwy singleton na `config.HISTORY_DB_FILE`)
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import config

_log = logging.getLogger("grok.history")

# Słownik typów/trybów — dokumentacyjny (walidacja miękka, by nie blokować rozwoju).
ARTIFACT_TYPES = ("image", "video", "audio", "file", "text", "code")
MODES = ("chat", "image", "video", "voice", "code")


@dataclass
class Artifact:
    """Znormalizowany rekord treści przepływającej między trybami (PLAN_M9 §0)."""
    id: str
    type: str
    mode: str
    mime: str = ""
    path: str = ""
    thumb_path: str = ""
    meta: dict = field(default_factory=dict)
    project_id: Optional[str] = None
    created_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id, "type": self.type, "mode": self.mode, "mime": self.mime,
            "path": self.path, "thumb_path": self.thumb_path, "meta": self.meta,
            "project_id": self.project_id, "created_at": self.created_at,
        }


@dataclass
class HistoryEvent:
    """Zdarzenie historii z dowolnego trybu (czat/media/voice/agent)."""
    id: str
    mode: str
    text: str = ""
    artifact_id: Optional[str] = None
    project_id: Optional[str] = None
    created_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id, "mode": self.mode, "text": self.text,
            "artifact_id": self.artifact_id, "project_id": self.project_id,
            "created_at": self.created_at,
        }


@dataclass
class Project:
    """Projekt — wspólny scope historii/artefaktów dla wszystkich trybów (M9-B5).
    `root` wiąże projekt z workspace'em kodu (most z `recent_workspaces`); puste
    `root` = projekt bez folderu (np. czysto czatowy). `vector_store_id` (M10-B5) =
    kolekcja xAI z dokumentami projektu (file_search w wielu rozmowach)."""
    id: str
    name: str
    root: str = ""
    created_at: float = 0.0
    vector_store_id: Optional[str] = None

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "root": self.root,
                "created_at": self.created_at, "vector_store_id": self.vector_store_id}


@dataclass
class CollectionFile:
    """Dokument w kolekcji projektu (M10-B5): mapuje plik xAI (`file_id`) w vector
    store (`vector_store_id`) na metadane do listy w UI."""
    id: str
    project_id: str
    vector_store_id: str
    file_id: str
    name: str = ""
    bytes: int = 0
    created_at: float = 0.0

    def to_dict(self) -> dict:
        return {"id": self.id, "project_id": self.project_id,
                "vector_store_id": self.vector_store_id, "file_id": self.file_id,
                "name": self.name, "bytes": self.bytes, "created_at": self.created_at}


def _fts_query(q: str) -> str:
    """Zamień dowolny tekst użytkownika na BEZPIECZNE wyrażenie FTS5 MATCH.

    Surowy `q` w MATCH potrafi rzucić błędem składni (np. samotny `"` albo operator
    `AND`/`*`). Tokenizujemy po białych znakach i każdy token cytujemy jako frazę
    (podwajając wewnętrzne `"`), łącząc spacją (= implicit AND). Pusty `q` → wzorzec,
    który nie trafia w nic."""
    toks = [t for t in re.split(r"\s+", q.strip()) if t]
    if not toks:
        return '""'
    return " ".join('"' + t.replace('"', '""') + '"' for t in toks)


class HistoryStore:
    """SQLite (+FTS5) magazyn artefaktów i historii. Bezpieczny dla wielu wątków."""

    def __init__(self, db_path: Optional[Any] = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else config.HISTORY_DB_FILE
        self._lock = threading.RLock()
        self._conn = self._connect_or_backup(self.db_path)
        self._init_schema()

    # --- otwarcie + odporność na korupcję -------------------------------------

    @staticmethod
    def _backup_corrupt(path: Path) -> None:
        """Przenieś uszkodzony plik bazy do `<name>.corrupt` (zachowanie do odzysku)
        i usuń poboczne pliki WAL (`-wal`/`-shm`), by nie zatruły świeżej bazy."""
        if path.exists():
            backup = path.with_suffix(path.suffix + ".corrupt")
            try:
                os.replace(path, backup)
                _log.error("Corrupt history db -> backed up to %s", backup.name)
            except OSError as exc:
                _log.error("Could not back up corrupt history db %s: %s", path.name, exc)
        for suffix in ("-wal", "-shm"):
            side = Path(str(path) + suffix)
            try:
                if side.exists():
                    side.unlink()
            except OSError:
                pass

    def _configure(self, conn: sqlite3.Connection) -> sqlite3.Connection:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn

    def _connect_or_backup(self, path: Path) -> sqlite3.Connection:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn: Optional[sqlite3.Connection] = None
        try:
            conn = sqlite3.connect(str(path), check_same_thread=False)
            # `connect` jest leniwy: korupcję wykrywa dopiero pierwszy odczyt stron.
            row = conn.execute("PRAGMA integrity_check(1)").fetchone()
            if not row or row[0] != "ok":
                raise sqlite3.DatabaseError(f"integrity_check: {row[0] if row else 'empty'}")
            return self._configure(conn)
        except sqlite3.DatabaseError as exc:
            _log.error("History db %s unusable (%s); backing up and recreating",
                       path.name, exc)
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
            self._backup_corrupt(path)
            return self._configure(sqlite3.connect(str(path), check_same_thread=False))

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS artifacts (
                    id          TEXT PRIMARY KEY,
                    type        TEXT NOT NULL,
                    mode        TEXT NOT NULL,
                    mime        TEXT NOT NULL DEFAULT '',
                    path        TEXT NOT NULL DEFAULT '',
                    thumb_path  TEXT NOT NULL DEFAULT '',
                    meta        TEXT NOT NULL DEFAULT '{}',
                    project_id  TEXT,
                    created_at  REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS history_events (
                    id          TEXT PRIMARY KEY,
                    mode        TEXT NOT NULL,
                    text        TEXT NOT NULL DEFAULT '',
                    artifact_id TEXT,
                    project_id  TEXT,
                    created_at  REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_events_created   ON history_events(created_at);
                CREATE INDEX IF NOT EXISTS idx_events_mode      ON history_events(mode);
                CREATE INDEX IF NOT EXISTS idx_events_project   ON history_events(project_id);
                CREATE INDEX IF NOT EXISTS idx_artifacts_created ON artifacts(created_at);
                CREATE INDEX IF NOT EXISTS idx_artifacts_mode    ON artifacts(mode);
                CREATE INDEX IF NOT EXISTS idx_artifacts_project ON artifacts(project_id);
                CREATE TABLE IF NOT EXISTS projects (
                    id          TEXT PRIMARY KEY,
                    name        TEXT NOT NULL,
                    root        TEXT NOT NULL DEFAULT '',
                    created_at  REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_projects_root ON projects(root);
                CREATE TABLE IF NOT EXISTS collection_files (
                    id              TEXT PRIMARY KEY,
                    project_id      TEXT NOT NULL,
                    vector_store_id TEXT NOT NULL,
                    file_id         TEXT NOT NULL,
                    name            TEXT NOT NULL DEFAULT '',
                    bytes           INTEGER NOT NULL DEFAULT 0,
                    created_at      REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_collfiles_project ON collection_files(project_id);
                CREATE VIRTUAL TABLE IF NOT EXISTS history_fts USING fts5(
                    text,
                    meta,
                    event_id UNINDEXED,
                    tokenize='unicode61'
                );
                """
            )
            # M10-B5: dołóż kolumnę vector_store_id do istniejącej tabeli projects
            # (migracja — CREATE TABLE IF NOT EXISTS nie dodaje kolumn do starej bazy).
            cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(projects)")}
            if "vector_store_id" not in cols:
                self._conn.execute("ALTER TABLE projects ADD COLUMN vector_store_id TEXT")

    # --- artefakty ------------------------------------------------------------

    def add_artifact(
        self, *, type: str, mode: str, mime: str = "", path: str = "",
        thumb_path: str = "", meta: Optional[dict] = None,
        project_id: Optional[str] = None, created_at: Optional[float] = None,
        id: Optional[str] = None,
    ) -> Artifact:
        art = Artifact(
            id=id or uuid.uuid4().hex,
            type=type, mode=mode, mime=mime, path=path, thumb_path=thumb_path,
            meta=dict(meta or {}), project_id=project_id,
            created_at=time.time() if created_at is None else float(created_at),
        )
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO artifacts "
                "(id, type, mode, mime, path, thumb_path, meta, project_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (art.id, art.type, art.mode, art.mime, art.path, art.thumb_path,
                 json.dumps(art.meta, ensure_ascii=False), art.project_id, art.created_at),
            )
        return art

    def get_artifact(self, artifact_id: str) -> Optional[Artifact]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM artifacts WHERE id = ?", (artifact_id,)
            ).fetchone()
        return self._row_to_artifact(row) if row else None

    def list_artifacts(
        self, *, mode: Optional[str] = None, project_id: Optional[str] = None,
        since: Optional[float] = None, until: Optional[float] = None,
        limit: int = 50, offset: int = 0,
    ) -> list[Artifact]:
        sql = "SELECT * FROM artifacts"
        where, params = self._filters(mode, project_id, since, until, col_prefix="")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params += [int(limit), int(offset)]
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_artifact(r) for r in rows]

    # --- zdarzenia historii ---------------------------------------------------

    def record_event(
        self, *, mode: str, text: str = "", artifact_id: Optional[str] = None,
        project_id: Optional[str] = None, meta: Optional[dict] = None,
        created_at: Optional[float] = None, id: Optional[str] = None,
    ) -> HistoryEvent:
        ev = HistoryEvent(
            id=id or uuid.uuid4().hex,
            mode=mode, text=text or "", artifact_id=artifact_id,
            project_id=project_id,
            created_at=time.time() if created_at is None else float(created_at),
        )
        meta_text = json.dumps(meta, ensure_ascii=False) if meta else ""
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO history_events "
                "(id, mode, text, artifact_id, project_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (ev.id, ev.mode, ev.text, ev.artifact_id, ev.project_id, ev.created_at),
            )
            self._conn.execute(
                "INSERT INTO history_fts (text, meta, event_id) VALUES (?, ?, ?)",
                (ev.text, meta_text, ev.id),
            )
        return ev

    def list_events(
        self, *, q: Optional[str] = None, mode: Optional[str] = None,
        project_id: Optional[str] = None, since: Optional[float] = None,
        until: Optional[float] = None, limit: int = 50, offset: int = 0,
    ) -> list[HistoryEvent]:
        params: list[Any] = []
        if q and q.strip():
            sql = ("SELECT e.* FROM history_fts f "
                   "JOIN history_events e ON e.id = f.event_id "
                   "WHERE history_fts MATCH ?")
            params.append(_fts_query(q))
            where, fp = self._filters(mode, project_id, since, until, col_prefix="e.")
            if where:
                sql += " AND " + " AND ".join(where)
            params += fp
            sql += " ORDER BY rank LIMIT ? OFFSET ?"
        else:
            sql = "SELECT * FROM history_events"
            where, fp = self._filters(mode, project_id, since, until, col_prefix="")
            if where:
                sql += " WHERE " + " AND ".join(where)
            params += fp
            sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params += [int(limit), int(offset)]
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_event(r) for r in rows]

    # --- projekty (M9-B5) -----------------------------------------------------

    def add_project(self, *, name: str, root: str = "", id: Optional[str] = None,
                    created_at: Optional[float] = None) -> Project:
        proj = Project(
            id=id or uuid.uuid4().hex, name=name, root=root or "",
            created_at=time.time() if created_at is None else float(created_at),
        )
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO projects (id, name, root, created_at) VALUES (?, ?, ?, ?)",
                (proj.id, proj.name, proj.root, proj.created_at),
            )
        return proj

    def get_project(self, project_id: str) -> Optional[Project]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
        return self._row_to_project(row) if row else None

    def get_project_by_root(self, root: str) -> Optional[Project]:
        if not root:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM projects WHERE root = ? ORDER BY created_at LIMIT 1", (root,)
            ).fetchone()
        return self._row_to_project(row) if row else None

    def ensure_project_for_root(self, root: str, name: Optional[str] = None) -> Project:
        """Idempotentnie: zwróć projekt dla `root` albo go utwórz (most z workspace)."""
        existing = self.get_project_by_root(root)
        if existing is not None:
            return existing
        nm = name or (Path(root).name if root else "") or root or "Project"
        return self.add_project(name=nm, root=root)

    def list_projects(self) -> list[Project]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM projects ORDER BY created_at DESC"
            ).fetchall()
        return [self._row_to_project(r) for r in rows]

    # --- kolekcje projektu (M10-B5: file_search) ------------------------------

    def set_project_vector_store(self, project_id: str, vector_store_id: str) -> None:
        """Przypisz (lub zmień) vector store kolekcji projektu."""
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE projects SET vector_store_id = ? WHERE id = ?",
                (vector_store_id, project_id),
            )

    def add_collection_file(self, *, project_id: str, vector_store_id: str,
                            file_id: str, name: str = "", bytes: int = 0,
                            id: Optional[str] = None,
                            created_at: Optional[float] = None) -> CollectionFile:
        cf = CollectionFile(
            id=id or uuid.uuid4().hex, project_id=project_id,
            vector_store_id=vector_store_id, file_id=file_id, name=name,
            bytes=int(bytes or 0),
            created_at=time.time() if created_at is None else float(created_at),
        )
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO collection_files "
                "(id, project_id, vector_store_id, file_id, name, bytes, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (cf.id, cf.project_id, cf.vector_store_id, cf.file_id, cf.name,
                 cf.bytes, cf.created_at),
            )
        return cf

    def list_collection_files(self, project_id: str) -> list[CollectionFile]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM collection_files WHERE project_id = ? ORDER BY created_at DESC",
                (project_id,),
            ).fetchall()
        return [self._row_to_collection_file(r) for r in rows]

    def get_collection_file(self, file_row_id: str) -> Optional[CollectionFile]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM collection_files WHERE id = ?", (file_row_id,)
            ).fetchone()
        return self._row_to_collection_file(row) if row else None

    def remove_collection_file(self, file_row_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM collection_files WHERE id = ?", (file_row_id,))

    # --- helpery --------------------------------------------------------------

    @staticmethod
    def _filters(mode, project_id, since, until, col_prefix: str):
        where: list[str] = []
        params: list[Any] = []
        if mode:
            where.append(f"{col_prefix}mode = ?")
            params.append(mode)
        if project_id:
            where.append(f"{col_prefix}project_id = ?")
            params.append(project_id)
        if since is not None:
            where.append(f"{col_prefix}created_at >= ?")
            params.append(float(since))
        if until is not None:
            where.append(f"{col_prefix}created_at <= ?")
            params.append(float(until))
        return where, params

    @staticmethod
    def _row_to_artifact(row: sqlite3.Row) -> Artifact:
        try:
            meta = json.loads(row["meta"]) if row["meta"] else {}
        except (ValueError, TypeError):
            meta = {}
        return Artifact(
            id=row["id"], type=row["type"], mode=row["mode"], mime=row["mime"],
            path=row["path"], thumb_path=row["thumb_path"], meta=meta,
            project_id=row["project_id"], created_at=row["created_at"],
        )

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> HistoryEvent:
        return HistoryEvent(
            id=row["id"], mode=row["mode"], text=row["text"],
            artifact_id=row["artifact_id"], project_id=row["project_id"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _row_to_project(row: sqlite3.Row) -> Project:
        keys = row.keys()
        return Project(id=row["id"], name=row["name"], root=row["root"],
                       created_at=row["created_at"],
                       vector_store_id=row["vector_store_id"] if "vector_store_id" in keys else None)

    @staticmethod
    def _row_to_collection_file(row: sqlite3.Row) -> CollectionFile:
        return CollectionFile(
            id=row["id"], project_id=row["project_id"],
            vector_store_id=row["vector_store_id"], file_id=row["file_id"],
            name=row["name"], bytes=row["bytes"], created_at=row["created_at"],
        )

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass


# --- leniwy singleton (B2 podepnie go pod Backend; tu wygodny dostęp) ---------
_default_store: Optional[HistoryStore] = None
_default_lock = threading.Lock()


def get_store() -> HistoryStore:
    """Zwróć współdzielony magazyn na `config.HISTORY_DB_FILE` (tworzony leniwie)."""
    global _default_store
    if _default_store is None:
        with _default_lock:
            if _default_store is None:
                _default_store = HistoryStore()
    return _default_store
