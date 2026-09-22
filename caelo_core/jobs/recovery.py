from __future__ import annotations

import time

UNKNOWN_MESSAGE = (
    "Restart nastąpił podczas wysyłania zadania. Caelo nie wysłał go ponownie, "
    "aby uniknąć podwójnego naliczenia; sprawdź konsolę dostawcy i ponów ręcznie."
)


def recover_jobs(repositories) -> dict[str, int]:
    counts = {"resumed": 0, "requeued": 0, "unknown": 0}
    for row in repositories.jobs.list(active=True, limit=10_000):
        job_id = row["id"]
        repositories.jobs.update(
            job_id, state="RECOVERY_PENDING", locked_at=None, worker_id=None
        )
        if row.get("remote_operation_id"):
            repositories.jobs.update(
                job_id, state="PROCESSING", next_poll_at=time.time()
            )
            repositories.generations.update(row["generation_id"], status="PROCESSING")
            counts["resumed"] += 1
        elif row.get("state") == "SUBMITTING":
            repositories.jobs.update(
                job_id, state="UNKNOWN_REMOTE_STATE", last_error=UNKNOWN_MESSAGE
            )
            repositories.generations.update(
                row["generation_id"],
                status="UNKNOWN_REMOTE_STATE",
                error=UNKNOWN_MESSAGE,
            )
            counts["unknown"] += 1
        else:
            repositories.jobs.update(job_id, state="QUEUED", next_run_at=time.time())
            repositories.generations.update(row["generation_id"], status="QUEUED")
            counts["requeued"] += 1
    return counts
