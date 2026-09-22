"""Deterministyczne testy kryteriów odbioru Fazy 3 (bez płatnych wywołań)."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

from caelo_core.history_store import HistoryStore
from caelo_core.jobs.recovery import recover_jobs
from caelo_core.storage.files import WorkspaceFileManager
from caelo_core.storage.metadata import write_sidecar


def main() -> int:
    checks: list[tuple[str, bool]] = []
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        store = HistoryStore(root / "phase3.db")
        repos = store.media
        versions = [
            r[0] for r in store._conn.execute("SELECT version FROM schema_migrations")
        ]
        checks.append(("migrations: schema versioned", versions == [1, 2]))

        # Awaria po otrzymaniu handle: polling można wznowić bez ponownego submitu.
        repos.generations.create(
            id="resume",
            provider="google",
            kind="video",
            operation="text2video",
            request={"model": "veo-3.1-fast-generate-preview"},
            status="SUBMITTED",
            created_at=time.time(),
        )
        repos.jobs.create(
            id="resume", generation_id="resume", queue_type="video", state="SUBMITTED"
        )
        repos.generations.update(
            "resume",
            remote_operation_id="operations/123",
            remote_metadata={"kind": "operation", "wire_model": "veo"},
        )
        # Awaria w nieatomowym oknie submitu: nigdy nie wysyłamy automatycznie drugi raz.
        repos.generations.create(
            id="unknown",
            provider="google",
            kind="video",
            operation="text2video",
            request={},
            status="SUBMITTING",
            created_at=time.time(),
        )
        repos.jobs.create(
            id="unknown",
            generation_id="unknown",
            queue_type="video",
            state="SUBMITTING",
        )
        result = recover_jobs(repos)
        checks.append(
            (
                "recovery: remote handle resumes polling",
                repos.jobs.get("resume")["state"] == "PROCESSING"
                and result["resumed"] == 1,
            )
        )
        checks.append(
            (
                "recovery: submit without handle is UNKNOWN_REMOTE_STATE",
                repos.jobs.get("unknown")["state"] == "UNKNOWN_REMOTE_STATE"
                and result["unknown"] == 1,
            )
        )

        files = WorkspaceFileManager(root / "workspace")
        target = files.allocate("video", ".mp4")
        digest, size = files.atomic_write(target, (b"0123", b"456789"))
        checks.append(
            (
                "files: atomic rename leaves no .part",
                target.read_bytes() == b"0123456789"
                and not target.with_name(target.name + ".part").exists()
                and size == 10
                and len(digest) == 64,
            )
        )
        sidecar = write_sidecar(target, {"provider": "google"})
        checks.append(
            (
                "metadata: versioned JSON sidecar",
                sidecar.exists()
                and '"schema_version": 1' in sidecar.read_text("utf-8"),
            )
        )
        trashed = files.trash(target)
        checks.append(
            (
                "files: dated recoverable trash",
                trashed.exists() and ".trash" in trashed.parts,
            )
        )

        # Starlette FileResponse odpowiada 206 i nie materializuje całego pliku.
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
            from starlette.responses import FileResponse

            ranged = root / "range.bin"
            ranged.write_bytes(b"0123456789")
            app = FastAPI()

            @app.get("/media")
            def media():
                return FileResponse(ranged)

            response = TestClient(app).get("/media", headers={"Range": "bytes=3-6"})
            ok = (
                response.status_code == 206
                and response.content == b"3456"
                and response.headers.get("content-range") == "bytes 3-6/10"
            )
        except Exception:
            ok = False
        checks.append(("media: HTTP Range supports seeking", ok))
        store.close()

    for name, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    passed = all(ok for _, ok in checks)
    print("RESULT:", "OK" if passed else "FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
