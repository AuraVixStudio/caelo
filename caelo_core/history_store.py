"""M9-B1: trwały, przeszukiwalny magazyn artefaktów i historii (SQLite + FTS5).

Kręgosłup huba (`docs/PLAN_M9_SZKIELET.md`): jeden typ **Artifact** + zdarzenia
historii ze wszystkich trybów, pełnotekstowo przeszukiwalne (FTS5). `sqlite3` jest
w stdlib — zero nowych zależności; działa identycznie na Windows/macOS/Linux
(spójne z celem cross-platform).

Własność danych (CLAUDE.md): ten magazyn ma **własny plik** `caelo_history.db` pod
`config.DATA_DIR` (IS_FROZEN → `%LOCALAPPDATA%`) i **NIE dotyka** `caelo_config.json`
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

import array
import json
import logging
import math
import os
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

import config

_log = logging.getLogger("caelo.history")

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
    """Dokument w „wiedzy projektu" (M10-B5). xAI nie wspiera serwerowych vector
    stores (`/v1/vector_stores` → 404), więc dokument jest trzymany **lokalnie**
    (`path` pod `DATA_DIR/project_docs`) i dołączany do wiadomości jako `input_file`
    na żądanie (przycisk „Attach all"). Pola `vector_store_id`/`file_id` zostają dla
    zgodności schematu (puste)."""
    id: str
    project_id: str
    name: str = ""
    path: str = ""
    mime: str = ""
    bytes: int = 0
    created_at: float = 0.0
    vector_store_id: str = ""
    file_id: str = ""

    def to_dict(self) -> dict:
        return {"id": self.id, "project_id": self.project_id, "name": self.name,
                "path": self.path, "mime": self.mime, "bytes": self.bytes,
                "created_at": self.created_at}


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
                except Exception:  # noqa: BLE001 — zamknięcie uszkodzonego połączenia; powód zalogowano wyżej, bazę i tak odtwarzamy
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
                    vector_store_id TEXT NOT NULL DEFAULT '',
                    file_id         TEXT NOT NULL DEFAULT '',
                    name            TEXT NOT NULL DEFAULT '',
                    path            TEXT NOT NULL DEFAULT '',
                    mime            TEXT NOT NULL DEFAULT '',
                    bytes           INTEGER NOT NULL DEFAULT 0,
                    created_at      REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_collfiles_project ON collection_files(project_id);
                CREATE TABLE IF NOT EXISTS gen_jobs (
                    id           TEXT PRIMARY KEY,
                    kind         TEXT NOT NULL,
                    op           TEXT NOT NULL,
                    params       TEXT NOT NULL DEFAULT '{}',
                    status       TEXT NOT NULL,
                    artifact_ids TEXT NOT NULL DEFAULT '[]',
                    error        TEXT NOT NULL DEFAULT '',
                    cost         REAL NOT NULL DEFAULT 0,
                    project_id   TEXT,
                    created_at   REAL NOT NULL,
                    updated_at   REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_genjobs_created ON gen_jobs(created_at);
                CREATE INDEX IF NOT EXISTS idx_genjobs_status  ON gen_jobs(status);
                CREATE INDEX IF NOT EXISTS idx_genjobs_project ON gen_jobs(project_id);
                CREATE VIRTUAL TABLE IF NOT EXISTS history_fts USING fts5(
                    text,
                    meta,
                    event_id UNINDEXED,
                    tokenize='unicode61'
                );
                CREATE TABLE IF NOT EXISTS event_embeddings (
                    event_id   TEXT PRIMARY KEY,
                    dim        INTEGER NOT NULL,
                    vec        BLOB NOT NULL,
                    created_at REAL NOT NULL DEFAULT 0
                );
                """
            )
            # M10-B5: migracje kolumn (CREATE TABLE IF NOT EXISTS nie dodaje kolumn
            # do istniejącej tabeli) — vector_store_id w projects (relikt), path+mime
            # w collection_files (lokalne przechowywanie dokumentów wiedzy projektu).
            pcols = {r["name"] for r in self._conn.execute("PRAGMA table_info(projects)")}
            if "vector_store_id" not in pcols:
                self._conn.execute("ALTER TABLE projects ADD COLUMN vector_store_id TEXT")
            ccols = {r["name"] for r in self._conn.execute("PRAGMA table_info(collection_files)")}
            if "path" not in ccols:
                self._conn.execute("ALTER TABLE collection_files ADD COLUMN path TEXT NOT NULL DEFAULT ''")
            if "mime" not in ccols:
                self._conn.execute("ALTER TABLE collection_files ADD COLUMN mime TEXT NOT NULL DEFAULT ''")

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

    def delete_artifact(self, artifact_id: str) -> int:
        """Usuń rekord artefaktu (plik na dysku kasuje warstwa wyżej — sandbox).
        Zdarzenia historii z `artifact_id` zostają (nieszkodliwy dangling ref)."""
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM artifacts WHERE id = ?", (artifact_id,))
        return cur.rowcount

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

    def event_metas(self, event_ids: Sequence[str]) -> dict[str, dict]:
        """M19-B10: zwróć `{event_id: meta}` dla podanych zdarzeń. `meta` żyje w
        `history_fts` (nie w dataclass HistoryEvent), więc czytamy je tu — używane
        przez eksport historii do markdown (prompt/model w meta). Jeden przebieg
        kursora z wczesnym zakończeniem (FTS5 bez MATCH = pełny skan; export rzadki)."""
        want = {str(i) for i in event_ids if i}
        if not want:
            return {}
        out: dict[str, dict] = {}
        with self._lock:
            cur = self._conn.execute("SELECT event_id, meta FROM history_fts")
            for row in cur:
                eid = row["event_id"]
                if eid in want and eid not in out:
                    try:
                        out[eid] = json.loads(row["meta"]) if row["meta"] else {}
                    except Exception:  # noqa: BLE001
                        out[eid] = {}
                    if len(out) == len(want):
                        break
        return out

    # --- pamięć semantyczna: embeddingi + KNN + hybryda (M19-B8) ---------------
    # Wektory zdarzeń (float32 BLOB) liczone przez `caelo_core.embeddings` w warstwie
    # wyżej (`caelo_core.memory.MemoryIndex`) — tu trzymamy WYŁĄCZNIE magazyn i KNN
    # (brak importu klienta/sieci, jak genjobs nie importuje api_manager). KNN to
    # brute-force cosine w Pythonie nad zdekodowanymi blobami (skala = tysiące → OK,
    # bez `sqlite-vec`/numpy). Hybryda scala FTS5 (MATCH) z KNN semantycznym.

    def set_event_embedding(self, event_id: str, vec: Sequence[float],
                            *, created_at: Optional[float] = None) -> None:
        """Zapisz/zaktualizuj wektor zdarzenia (float32 BLOB). Idempotentne po event_id."""
        blob = array.array("f", [float(x) for x in vec]).tobytes()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO event_embeddings (event_id, dim, vec, created_at) "
                "VALUES (?, ?, ?, ?)",
                (event_id, len(vec), blob,
                 time.time() if created_at is None else float(created_at)),
            )

    def count_event_embeddings(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM event_embeddings").fetchone()
        return int(row[0]) if row else 0

    @staticmethod
    def _decode_vec(blob) -> array.array:
        a = array.array("f")
        a.frombytes(bytes(blob))
        return a

    def knn_events(self, query_vec: Sequence[float], *, k: int = 5,
                   project_id: Optional[str] = None, min_score: float = 0.0
                   ) -> list[tuple[HistoryEvent, float]]:
        """Brute-force cosine KNN nad `event_embeddings` ∩ `history_events`. Zwraca
        listę `(HistoryEvent, score)` malejąco po score (cosinus), powyżej `min_score`.
        Wektory o innym wymiarze niż zapytanie (np. po zmianie modelu) są pomijane."""
        q = [float(x) for x in query_vec]
        qnorm = math.sqrt(sum(v * v for v in q))
        if qnorm == 0.0:
            return []
        sql = ("SELECT e.*, m.vec AS _vec FROM event_embeddings m "
               "JOIN history_events e ON e.id = m.event_id")
        params: list[Any] = []
        if project_id:
            sql += " WHERE e.project_id = ?"
            params.append(project_id)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        scored: list[tuple[HistoryEvent, float]] = []
        for row in rows:
            vec = self._decode_vec(row["_vec"])
            if len(vec) != len(q):
                continue
            dot = 0.0
            vnorm = 0.0
            for a, b in zip(q, vec):
                dot += a * b
                vnorm += b * b
            vnorm = math.sqrt(vnorm)
            if vnorm == 0.0:
                continue
            score = dot / (qnorm * vnorm)
            if score >= min_score:
                scored.append((self._row_to_event(row), score))
        scored.sort(key=lambda t: t[1], reverse=True)
        return scored[:k]

    def hybrid_search(self, *, q_text: Optional[str] = None,
                      query_vec: Optional[Sequence[float]] = None, k: int = 5,
                      project_id: Optional[str] = None, min_score: float = 0.0
                      ) -> list[HistoryEvent]:
        """Hybryda: KNN semantyczny (jeśli `query_vec`) + FTS5 (jeśli `q_text`), scalone
        po id zdarzenia. KNN-trafienia (score≥min_score) idą pierwsze (rerank), potem
        dopełnienie z FTS aż do `k`. Zwraca listę `HistoryEvent`."""
        out: list[HistoryEvent] = []
        seen: set[str] = set()
        if query_vec is not None:
            for ev, _score in self.knn_events(query_vec, k=k, project_id=project_id,
                                              min_score=min_score):
                if ev.id not in seen:
                    seen.add(ev.id)
                    out.append(ev)
        if q_text and q_text.strip() and len(out) < k:
            for ev in self.list_events(q=q_text, project_id=project_id, limit=k):
                if ev.id not in seen:
                    seen.add(ev.id)
                    out.append(ev)
                    if len(out) >= k:
                        break
        return out[:k]

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

    def add_collection_file(self, *, project_id: str, name: str = "", path: str = "",
                            mime: str = "", bytes: int = 0, vector_store_id: str = "",
                            file_id: str = "", id: Optional[str] = None,
                            created_at: Optional[float] = None) -> CollectionFile:
        cf = CollectionFile(
            id=id or uuid.uuid4().hex, project_id=project_id, name=name, path=path,
            mime=mime, bytes=int(bytes or 0), vector_store_id=vector_store_id,
            file_id=file_id,
            created_at=time.time() if created_at is None else float(created_at),
        )
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO collection_files "
                "(id, project_id, vector_store_id, file_id, name, path, mime, bytes, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (cf.id, cf.project_id, cf.vector_store_id, cf.file_id, cf.name,
                 cf.path, cf.mime, cf.bytes, cf.created_at),
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

    # --- zadania generacji (M11-B1: jednolita kolejka obrazu/wideo) -----------
    # Persistencja rekordów `GenJob` (silnik w `caelo_core.genjobs`). Tu trzymamy
    # tylko I/O — by uniknąć cyklicznego importu (genjobs → history_store),
    # operujemy na polach prymitywnych i zwracamy `dict` (genjobs mapuje go na
    # własną dataklasę). `params`/`artifact_ids` serializowane jako JSON.
    _GEN_ACTIVE = ("queued", "running")

    def upsert_gen_job(self, *, id: str, kind: str, op: str, params: dict,
                       status: str, artifact_ids: Optional[list] = None,
                       error: str = "", cost: float = 0.0,
                       project_id: Optional[str] = None,
                       created_at: float, updated_at: float) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO gen_jobs "
                "(id, kind, op, params, status, artifact_ids, error, cost, "
                " project_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (id, kind, op, json.dumps(params or {}, ensure_ascii=False), status,
                 json.dumps(list(artifact_ids or []), ensure_ascii=False), error or "",
                 float(cost or 0.0), project_id, float(created_at), float(updated_at)),
            )

    def get_gen_job(self, job_id: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM gen_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return self._row_to_gen_job(row) if row else None

    def list_gen_jobs(self, *, active: Optional[bool] = None,
                      project_id: Optional[str] = None,
                      limit: int = 50, offset: int = 0) -> list[dict]:
        sql = "SELECT * FROM gen_jobs"
        where: list[str] = []
        params: list[Any] = []
        if active is True:
            where.append("status IN (?, ?)")
            params += list(self._GEN_ACTIVE)
        elif active is False:
            where.append("status NOT IN (?, ?)")
            params += list(self._GEN_ACTIVE)
        if project_id:
            where.append("project_id = ?")
            params.append(project_id)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params += [int(limit), int(offset)]
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_gen_job(r) for r in rows]

    def count_active_gen_jobs(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM gen_jobs WHERE status IN (?, ?)", self._GEN_ACTIVE
            ).fetchone()
        return int(row[0]) if row else 0

    def delete_gen_job(self, job_id: str) -> int:
        """Usuń rekord zadania (NIE rusza artefaktów — wygenerowane media zostają)."""
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM gen_jobs WHERE id = ?", (job_id,))
        return cur.rowcount

    def delete_terminal_gen_jobs(self, *, kind: Optional[str] = None,
                                 project_id: Optional[str] = None) -> int:
        """Wyczyść ZAKOŃCZONE zadania (done/failed/cancelled) — opcjonalnie po `kind`/
        projekcie. Aktywne (queued/running) zostają. Artefakty NIE są usuwane."""
        sql = "DELETE FROM gen_jobs WHERE status NOT IN (?, ?)"
        params: list[Any] = list(self._GEN_ACTIVE)
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        if project_id:
            sql += " AND project_id = ?"
            params.append(project_id)
        with self._lock, self._conn:
            cur = self._conn.execute(sql, params)
        return cur.rowcount

    @staticmethod
    def _row_to_gen_job(row: sqlite3.Row) -> dict:
        try:
            params = json.loads(row["params"]) if row["params"] else {}
        except (ValueError, TypeError):
            params = {}
        try:
            artifact_ids = json.loads(row["artifact_ids"]) if row["artifact_ids"] else []
        except (ValueError, TypeError):
            artifact_ids = []
        return {
            "id": row["id"], "kind": row["kind"], "op": row["op"], "params": params,
            "status": row["status"], "artifact_ids": artifact_ids, "error": row["error"],
            "cost": row["cost"], "project_id": row["project_id"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

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
        keys = row.keys()
        return CollectionFile(
            id=row["id"], project_id=row["project_id"], name=row["name"],
            path=row["path"] if "path" in keys else "",
            mime=row["mime"] if "mime" in keys else "",
            bytes=row["bytes"], created_at=row["created_at"],
            vector_store_id=row["vector_store_id"], file_id=row["file_id"],
        )

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001 — zamknięcie bazy przy wyłączaniu sidecara; błąd nieistotny
                _log.debug("History db close failed", exc_info=True)


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
