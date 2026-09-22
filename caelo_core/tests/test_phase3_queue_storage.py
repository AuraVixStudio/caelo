from __future__ import annotations

import json
import sqlite3
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.responses import FileResponse

from caelo_core.history_store import HistoryStore
from caelo_core.jobs.recovery import recover_jobs
from caelo_core.jobs.queue import GenJobManager
from caelo_core.storage.files import WorkspaceFileManager
from caelo_core.storage.metadata import write_sidecar


def _generation(repos, id: str, state: str):
    repos.generations.create(
        id=id,
        provider="google",
        kind="video",
        operation="text2video",
        request={},
        status=state,
        created_at=time.time(),
    )
    repos.jobs.create(id=id, generation_id=id, queue_type="video", state=state)


def test_schema_migrations_are_versioned(tmp_path):
    store = HistoryStore(tmp_path / "history.db")
    assert [
        r[0] for r in store._conn.execute("SELECT version FROM schema_migrations")
    ] == [1, 2, 3, 4]
    columns = {r[1] for r in store._conn.execute("PRAGMA table_info(artifacts)")}
    assert "generation_output_id" in columns
    store.close()


def test_queue_replaces_preflight_image_estimate_with_actual_api_cost(tmp_path):
    store = HistoryStore(tmp_path / "cost.db")
    _generation(store.media, "cost", "COMPLETED")
    manager = GenJobManager(lambda *_args: [], store=store, workers=1)
    try:
        manager.set_actual_cost(
            "cost", 0.05268,
            remote_metadata={"usage": {"input_tokens": 5, "output_tokens": 1756}},
        )
        saved = store.media.generations.get("cost")
        assert saved["estimated_cost"] == 0.05268
        assert saved["remote_metadata"]["usage"]["output_tokens"] == 1756
    finally:
        manager.close()
        store.close()


def test_job_list_uses_lightweight_request_without_reading_blob(tmp_path):
    store = HistoryStore(tmp_path / "history.db")
    payload = "data:image/png;base64," + ("A" * 200_000)
    store.media.generations.create(
        id="heavy",
        provider="google",
        kind="image",
        operation="edit",
        request={"prompt": "keep me", "model": "image-model", "images": [payload]},
        status="COMPLETED",
        created_at=time.time(),
    )
    store.media.jobs.create(
        id="heavy", generation_id="heavy", queue_type="image", state="COMPLETED"
    )

    listed = store.media.jobs.list(include_request=False)
    assert listed[0]["request"] == {
        "provider": "google", "model": "image-model", "prompt": "keep me"
    }
    saved = store.media.generations.get("heavy")["request"]
    assert saved["prompt"] == "keep me"
    assert saved["images"] == [payload]
    store.close()


def test_legacy_backfill_does_not_duplicate_completed_data_uris(tmp_path):
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE gen_jobs (id TEXT PRIMARY KEY,kind TEXT,op TEXT,params TEXT,status TEXT,"
        "artifact_ids TEXT,error TEXT,cost REAL,project_id TEXT,created_at REAL,updated_at REAL)"
    )
    payload = "data:image/png;base64," + ("A" * 200_000)
    conn.execute(
        "INSERT INTO gen_jobs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("old", "image", "edit", json.dumps({"prompt": "legacy", "images": [payload]}),
         "done", "[]", "", 0, None, time.time(), time.time()),
    )
    conn.commit()
    conn.close()

    store = HistoryStore(path)
    backup = path.with_suffix(path.suffix + ".pre-migration-v4.bak")
    assert backup.exists()
    check = sqlite3.connect(backup)
    try:
        assert check.execute("SELECT COUNT(*) FROM gen_jobs").fetchone()[0] == 1
        assert not check.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='generations'"
        ).fetchone()
    finally:
        check.close()
    legacy_size = store._conn.execute(
        "SELECT length(params) FROM gen_jobs WHERE id='old'"
    ).fetchone()[0]
    new_size = store._conn.execute(
        "SELECT length(request) FROM generations WHERE id='old'"
    ).fetchone()[0]
    assert legacy_size > 200_000
    assert new_size < 1_000
    assert store.media.generations.get("old")["request"]["prompt"] == "legacy"
    store.close()


def test_recovery_resumes_remote_handle_and_does_not_resubmit_unknown(tmp_path):
    store = HistoryStore(tmp_path / "history.db")
    repos = store.media
    _generation(repos, "resume", "SUBMITTED")
    repos.generations.update("resume", remote_operation_id="operations/123")
    _generation(repos, "unknown", "SUBMITTING")

    result = recover_jobs(repos)

    assert result == {"resumed": 1, "requeued": 0, "unknown": 1}
    assert repos.jobs.get("resume")["state"] == "PROCESSING"
    assert repos.jobs.get("unknown")["state"] == "UNKNOWN_REMOTE_STATE"
    store.close()


def test_manager_restart_finishes_remote_poll_without_resubmit(tmp_path):
    path = tmp_path / "history.db"
    store = HistoryStore(path)
    _generation(store.media, "resume", "SUBMITTED")
    store.media.generations.update(
        "resume",
        remote_operation_id="operations/123",
        remote_metadata={"kind": "operation"},
    )
    store.close()

    calls = []

    class PollOnlyExecutor:
        def execute(self, job, cancel, manager):
            calls.append((job.state, job.remote_operation_id))
            return ["artifact-after-restart"]

    reopened = HistoryStore(path)
    manager = GenJobManager(
        PollOnlyExecutor(), store=reopened, workers=1, scheduler_interval=0.01
    )
    try:
        final = manager.wait("resume", timeout=3)
        assert final.status == "done"
        assert final.artifact_ids == ["artifact-after-restart"]
        assert calls == [("PROCESSING", "operations/123")]
    finally:
        manager.close()
        reopened.close()


def test_manager_restart_never_executes_unknown_submit(tmp_path):
    store = HistoryStore(tmp_path / "history.db")
    _generation(store.media, "unknown", "SUBMITTING")
    calls = []

    def must_not_run(job, cancel):
        calls.append(job.id)
        return []

    manager = GenJobManager(
        must_not_run, store=store, workers=1, scheduler_interval=0.01
    )
    try:
        job = manager.get("unknown")
        assert job.state == "UNKNOWN_REMOTE_STATE"
        assert job.status == "unknown_remote_state"
        assert calls == []
    finally:
        manager.close()
        store.close()


def test_atomic_file_sidecar_and_recoverable_trash(tmp_path):
    files = WorkspaceFileManager(tmp_path / "workspace")
    target = files.allocate("video", ".mp4")
    assert target.parent == tmp_path / "workspace"
    digest, size = files.atomic_write(target, (b"0123", b"456789"))
    assert target.read_bytes() == b"0123456789"
    assert not target.with_name(target.name + ".part").exists()
    assert size == 10 and len(digest) == 64
    assert write_sidecar(target, {"provider": "google"}).exists()
    trashed = files.trash(target)
    assert trashed.exists() and ".trash" in trashed.parts


def test_job_inputs_are_stored_outside_sqlite_and_materialized_for_worker(tmp_path):
    store = HistoryStore(tmp_path / "history.db")
    payload = "data:image/png;base64," + ("A" * 200_000)
    seen = []

    class Executor:
        def execute(self, job, cancel, manager):
            seen.append(job.params["images"][0])
            return []

    manager = GenJobManager(Executor(), store=store, workers=1, scheduler_interval=0.01)
    try:
        job = manager.submit(
            kind="image", op="edit", params={"prompt": "test", "images": [payload]}
        )
        final = manager.wait(job.id, timeout=3)
        assert final.status == "done"
        saved = store._conn.execute(
            "SELECT request FROM generations WHERE id=?", (job.id,)
        ).fetchone()[0]
        assert len(saved) < 1_000
        assert "_caelo_input_file" in saved
        assert seen == [payload]
        assert not (tmp_path / "job_inputs" / job.id).exists()
    finally:
        manager.close()
        store.close()


def test_file_response_honors_http_range(tmp_path):
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"0123456789")
    app = FastAPI()

    @app.get("/media")
    def get_media():
        return FileResponse(media, media_type="video/mp4")

    response = TestClient(app).get("/media", headers={"Range": "bytes=3-6"})
    assert response.status_code == 206
    assert response.content == b"3456"
    assert response.headers["content-range"] == "bytes 3-6/10"


def test_remote_file_cache_survives_store_reopen(tmp_path):
    path = tmp_path / "history.db"
    store = HistoryStore(path)
    store.media.remote_files.put(
        sha256="a" * 64,
        provider="google",
        remote_name="files/1",
        uri="https://example.invalid/file",
        mime="video/mp4",
        expires_at=time.time() + 3600,
    )
    store.close()
    reopened = HistoryStore(path)
    assert reopened.media.remote_files.get("a" * 64)["remote_name"] == "files/1"
    reopened.close()
