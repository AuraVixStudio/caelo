"""Wersjonowane migracje SQLite dla zunifikowanego modułu mediów."""

from __future__ import annotations

import json
import sqlite3
import time

from caelo_core.storage.payloads import strip_blob_params

LATEST_SCHEMA_VERSION = 4

MEDIA_SCHEMA = """
CREATE TABLE IF NOT EXISTS generations (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    kind TEXT NOT NULL,
    operation TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    prompt TEXT NOT NULL DEFAULT '',
    request TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL,
    project_id TEXT,
    remote_operation_id TEXT,
    remote_file_uri TEXT,
    remote_metadata TEXT NOT NULL DEFAULT '{}',
    error TEXT NOT NULL DEFAULT '',
    estimated_cost REAL NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_generations_created ON generations(created_at);
CREATE INDEX IF NOT EXISTS idx_generations_status ON generations(status);
CREATE INDEX IF NOT EXISTS idx_generations_project ON generations(project_id);

CREATE TABLE IF NOT EXISTS generation_inputs (
    id TEXT PRIMARY KEY, generation_id TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'input',
    source TEXT NOT NULL DEFAULT '', mime TEXT NOT NULL DEFAULT '', sha256 TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL, FOREIGN KEY(generation_id) REFERENCES generations(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_generation_inputs_generation ON generation_inputs(generation_id);

CREATE TABLE IF NOT EXISTS generation_outputs (
    id TEXT PRIMARY KEY, generation_id TEXT NOT NULL, artifact_id TEXT,
    path TEXT NOT NULL DEFAULT '', mime TEXT NOT NULL DEFAULT '', sha256 TEXT NOT NULL DEFAULT '',
    bytes INTEGER NOT NULL DEFAULT 0, metadata TEXT NOT NULL DEFAULT '{}', created_at REAL NOT NULL,
    FOREIGN KEY(generation_id) REFERENCES generations(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_generation_outputs_generation ON generation_outputs(generation_id);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY, generation_id TEXT NOT NULL UNIQUE, queue_type TEXT NOT NULL,
    state TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 3,
    next_run_at REAL, next_poll_at REAL, locked_at REAL, worker_id TEXT,
    progress INTEGER, last_error TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL, updated_at REAL NOT NULL,
    FOREIGN KEY(generation_id) REFERENCES generations(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_jobs_sched ON jobs(state, next_run_at, next_poll_at);
CREATE INDEX IF NOT EXISTS idx_jobs_locked ON jobs(locked_at);

CREATE TABLE IF NOT EXISTS usage_records (
    id TEXT PRIMARY KEY, generation_id TEXT, provider TEXT NOT NULL, model TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL, units REAL NOT NULL DEFAULT 0, unit_name TEXT NOT NULL DEFAULT '',
    estimated_cost REAL NOT NULL DEFAULT 0, actual_cost REAL, created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_usage_created ON usage_records(created_at);

CREATE TABLE IF NOT EXISTS remote_file_cache (
    sha256 TEXT PRIMARY KEY, provider TEXT NOT NULL, remote_name TEXT NOT NULL DEFAULT '',
    uri TEXT NOT NULL, mime TEXT NOT NULL DEFAULT '', expires_at REAL NOT NULL, created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_remote_file_expiry ON remote_file_cache(expires_at);

CREATE TABLE IF NOT EXISTS asset_references (
    id TEXT PRIMARY KEY, artifact_id TEXT NOT NULL, source_artifact_id TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'reference', created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS presets (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS prompt_templates (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, template TEXT NOT NULL, kind TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS media_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tags (id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS generation_tags (
    generation_id TEXT NOT NULL, tag_id TEXT NOT NULL, PRIMARY KEY(generation_id, tag_id),
    FOREIGN KEY(generation_id) REFERENCES generations(id) ON DELETE CASCADE,
    FOREIGN KEY(tag_id) REFERENCES tags(id) ON DELETE CASCADE
);
"""


def _backfill_legacy_jobs(conn: sqlite3.Connection) -> None:
    """Przenieś rekordy M11. Operacja idempotentna; nie usuwa starej tabeli."""
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='gen_jobs'"
    ).fetchone()
    if not exists:
        return
    # Nie pobieraj wszystkich wierszy naraz: stare params mogą zawierać wiele GB
    # data-URI. Lista samych identyfikatorów jest mała, rekordy czytamy pojedynczo.
    row_ids = [row[0] for row in conn.execute("SELECT id FROM gen_jobs")]
    now = time.time()
    state_map = {
        "queued": "QUEUED",
        "running": "UNKNOWN_REMOTE_STATE",
        "done": "COMPLETED",
        "failed": "FAILED",
        "cancelled": "CANCELLED",
    }
    for row_id in row_ids:
        row = conn.execute("SELECT * FROM gen_jobs WHERE id=?", (row_id,)).fetchone()
        r = dict(row)
        params = r.get("params") or "{}"
        try:
            parsed = json.loads(params)
        except (TypeError, ValueError):
            parsed = {}
            params = "{}"
        provider = str(parsed.get("provider") or "xai")
        state = state_map.get(str(r.get("status") or "").lower(), "FAILED")
        if state == "COMPLETED":
            # Pełny oryginał pozostaje w legacy gen_jobs; do nowej tabeli nie kopiujemy
            # drugi raz wielomegabajtowych data-URI.
            parsed = strip_blob_params(parsed, mark_compacted=True)
            params = json.dumps(parsed, ensure_ascii=False)
        error = r.get("error") or ""
        if str(r.get("status") or "").lower() == "running" and not error:
            error = "Restart nastąpił podczas wysyłania; nie wysłano ponownie, aby uniknąć podwójnego naliczenia."
        conn.execute(
            "INSERT OR IGNORE INTO generations "
            "(id,provider,kind,operation,model,prompt,request,status,project_id,error,estimated_cost,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                r["id"],
                provider,
                r["kind"],
                r["op"],
                str(parsed.get("model") or ""),
                str(parsed.get("prompt") or ""),
                params,
                state,
                r.get("project_id"),
                error,
                float(r.get("cost") or 0),
                float(r.get("created_at") or now),
                float(r.get("updated_at") or now),
            ),
        )
        conn.execute(
            "INSERT OR IGNORE INTO jobs (id,generation_id,queue_type,state,attempt,max_attempts,created_at,updated_at,last_error) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                r["id"],
                r["id"],
                r["kind"],
                state,
                0,
                3,
                float(r.get("created_at") or now),
                float(r.get("updated_at") or now),
                error,
            ),
        )
        try:
            artifacts = json.loads(r.get("artifact_ids") or "[]")
        except (TypeError, ValueError):
            artifacts = []
        for artifact_id in artifacts:
            conn.execute(
                "INSERT OR IGNORE INTO generation_outputs "
                "(id,generation_id,artifact_id,created_at) VALUES (?,?,?,?)",
                (
                    f"{r['id']}:{artifact_id}",
                    r["id"],
                    artifact_id,
                    float(r.get("updated_at") or now),
                ),
            )
def run_migrations(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at REAL NOT NULL)"
    )
    applied = {int(r[0]) for r in conn.execute("SELECT version FROM schema_migrations")}
    if 1 not in applied:
        conn.executescript(MEDIA_SCHEMA)
        conn.execute(
            "INSERT INTO schema_migrations VALUES (1, ?, ?)",
            ("media_schema", time.time()),
        )
    if 2 not in applied:
        _backfill_legacy_jobs(conn)
        conn.execute(
            "INSERT INTO schema_migrations VALUES (2, ?, ?)",
            ("legacy_gen_jobs_backfill", time.time()),
        )
    if 3 not in applied:
        artifact_columns = {
            str(row[1]) for row in conn.execute("PRAGMA table_info(artifacts)")
        }
        if "favorite" not in artifact_columns:
            conn.execute(
                "ALTER TABLE artifacts ADD COLUMN favorite INTEGER NOT NULL DEFAULT 0"
            )
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS artifact_tags (
                artifact_id TEXT NOT NULL,
                tag_id TEXT NOT NULL,
                PRIMARY KEY(artifact_id, tag_id),
                FOREIGN KEY(artifact_id) REFERENCES artifacts(id) ON DELETE CASCADE,
                FOREIGN KEY(tag_id) REFERENCES tags(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_asset_refs_artifact
                ON asset_references(artifact_id);
            CREATE INDEX IF NOT EXISTS idx_asset_refs_source
                ON asset_references(source_artifact_id);
            """
        )
        conn.execute(
            "INSERT INTO schema_migrations VALUES (3, ?, ?)",
            ("artifact_library_metadata", time.time()),
        )
    if 4 not in applied:
        artifact_columns = {
            str(row[1]) for row in conn.execute("PRAGMA table_info(artifacts)")
        }
        if "generation_output_id" not in artifact_columns:
            # Nullable i bez backfillu: legacy artefakty pozostają poprawne jako NULL.
            conn.execute("ALTER TABLE artifacts ADD COLUMN generation_output_id TEXT")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_artifacts_generation_output "
            "ON artifacts(generation_output_id)"
        )
        conn.execute(
            "INSERT INTO schema_migrations VALUES (4, ?, ?)",
            ("artifact_generation_output_link", time.time()),
        )
