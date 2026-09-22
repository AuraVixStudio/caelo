"""Jednorazowa, odzyskiwalna naprawa rozrośniętej bazy historii Caelo.

Uruchamiać wyłącznie przy zamkniętej aplikacji. Skrypt zachowuje pełną kopię
oryginalnego zestawu SQLite (DB/WAL/SHM), skraca data-URI tylko w zakończonych
zadaniach i wykonuje VACUUM oraz integrity_check.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from caelo_core.storage.payloads import strip_blob_params  # noqa: E402


def _size(path: Path) -> int:
    return path.stat().st_size if path.exists() else 0


def _compact_json(value: str) -> tuple[str, bool]:
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, ValueError):
        return value, False
    compacted = strip_blob_params(parsed, mark_compacted=True)
    changed = compacted != parsed
    return (
        json.dumps(compacted, ensure_ascii=False, separators=(",", ":"))
        if changed
        else value,
        changed,
    )


def _compact_table(
    conn: sqlite3.Connection,
    *,
    table: str,
    payload_column: str,
    completed_status: str,
) -> tuple[int, int, int]:
    rows = conn.execute(
        f"SELECT rowid,{payload_column} FROM {table} WHERE status=?",
        (completed_status,),
    ).fetchall()
    changed_rows = before = after = 0
    for rowid, value in rows:
        text = str(value or "{}")
        compacted, changed = _compact_json(text)
        if not changed:
            continue
        conn.execute(
            f"UPDATE {table} SET {payload_column}=? WHERE rowid=?",
            (compacted, rowid),
        )
        changed_rows += 1
        before += len(text.encode("utf-8"))
        after += len(compacted.encode("utf-8"))
    return changed_rows, before, after


def repair(db_path: Path) -> None:
    expected_parent = (Path(os.environ["LOCALAPPDATA"]) / "Caelo").resolve()
    db_path = db_path.resolve()
    if db_path.parent != expected_parent or db_path.name != "caelo_history.db":
        raise RuntimeError(f"Refusing unexpected database target: {db_path}")
    if not db_path.is_file():
        raise FileNotFoundError(db_path)

    wal_path = Path(str(db_path) + "-wal")
    shm_path = Path(str(db_path) + "-shm")
    original_total = sum(_size(path) for path in (db_path, wal_path, shm_path))

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = db_path.parent / "backups" / f"history-repair-{stamp}"
    backup_dir.mkdir(parents=True, exist_ok=False)
    for source in (db_path, wal_path, shm_path):
        if source.exists():
            shutil.copy2(source, backup_dir / source.name)

    print(f"BACKUP={backup_dir}", flush=True)
    print(f"BEFORE_BYTES={original_total}", flush=True)

    conn = sqlite3.connect(db_path, timeout=30)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("BEGIN IMMEDIATE")
        legacy = _compact_table(
            conn,
            table="gen_jobs",
            payload_column="params",
            completed_status="done",
        )
        current = _compact_table(
            conn,
            table="generations",
            payload_column="request",
            completed_status="COMPLETED",
        )
        conn.commit()
        print(
            "COMPACTED_ROWS="
            f"gen_jobs:{legacy[0]},generations:{current[0]}",
            flush=True,
        )
        print(
            f"REMOVED_LOGICAL_BYTES={(legacy[1] - legacy[2]) + (current[1] - current[2])}",
            flush=True,
        )
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("VACUUM")
        result = conn.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise RuntimeError(f"SQLite integrity_check failed: {result}")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    final_total = sum(_size(path) for path in (db_path, wal_path, shm_path))
    print(f"AFTER_BYTES={final_total}", flush=True)
    print("INTEGRITY=ok", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.apply:
        print("Refusing to modify the database without --apply", file=sys.stderr)
        return 2
    db_path = Path(os.environ["LOCALAPPDATA"]) / "Caelo" / "caelo_history.db"
    started = time.perf_counter()
    repair(db_path)
    print(f"ELAPSED_SECONDS={time.perf_counter() - started:.1f}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
