"""Verify the latest history migration on a consistent copy of a real database.

The source is opened read-only and is never modified. SQLite's backup API copies
committed WAL pages into a temporary database, then ``HistoryStore`` migrates only
that copy. The script checks integrity, migration versions and row-count stability.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from caelo_core.history_store import HistoryStore  # noqa: E402
from caelo_core.storage.migrations import LATEST_SCHEMA_VERSION  # noqa: E402


PRESERVED_TABLES = (
    "artifacts", "history_events", "history_fts", "event_embeddings",
    "projects", "collection_files", "gen_jobs",
)


def counts(conn: sqlite3.Connection) -> dict[str, int]:
    tables = {
        str(row[0]) for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
        )
    }
    return {
        table: int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
        for table in PRESERVED_TABLES if table in tables
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("--work-dir", type=Path)
    args = parser.parse_args()
    source_path = args.database.resolve()
    if not source_path.is_file():
        parser.error(f"database does not exist: {source_path}")

    work = args.work_dir or Path(tempfile.mkdtemp(prefix="caelo-phase7-migration-"))
    work.mkdir(parents=True, exist_ok=True)
    target_path = work / source_path.name
    started = time.perf_counter()

    source = sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True)
    target = sqlite3.connect(target_path)
    try:
        before = counts(source)
        source.backup(target)
    finally:
        target.close()
        source.close()

    store = HistoryStore(target_path)
    try:
        integrity = str(store._conn.execute("PRAGMA integrity_check").fetchone()[0])
        after = counts(store._conn)
        versions = [
            int(row[0]) for row in store._conn.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]
        columns = {
            str(row[1]) for row in store._conn.execute("PRAGMA table_info(artifacts)")
        }
    finally:
        store.close()

    backup = target_path.with_suffix(
        target_path.suffix + f".pre-migration-v{LATEST_SCHEMA_VERSION}.bak"
    )
    ok = (
        integrity == "ok" and before == after and
        versions and versions[-1] == LATEST_SCHEMA_VERSION and
        "generation_output_id" in columns
    )
    report = {
        "ok": ok,
        "source": str(source_path),
        "source_bytes": source_path.stat().st_size,
        "copy": str(target_path),
        "copy_bytes": target_path.stat().st_size,
        "pre_migration_backup": str(backup) if backup.exists() else None,
        "integrity": integrity,
        "versions": versions,
        "preserved_counts": after,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
