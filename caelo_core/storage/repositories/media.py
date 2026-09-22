from __future__ import annotations

import json
import time
import uuid
from typing import Any, Optional

def _loads(value: Any, fallback):
    try:
        return json.loads(value) if value else fallback
    except (TypeError, ValueError):
        return fallback


class _Repository:
    def __init__(self, conn, lock) -> None:
        self.conn, self.lock = conn, lock


class GenerationRepository(_Repository):
    def create(
        self,
        *,
        id: str,
        provider: str,
        kind: str,
        operation: str,
        request: dict,
        status: str,
        project_id=None,
        estimated_cost=0.0,
        created_at=None,
    ) -> dict:
        now = time.time() if created_at is None else float(created_at)
        with self.lock, self.conn:
            self.conn.execute(
                "INSERT INTO generations (id,provider,kind,operation,model,prompt,request,status,project_id,estimated_cost,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    id,
                    provider,
                    kind,
                    operation,
                    str(request.get("model") or ""),
                    str(request.get("prompt") or ""),
                    json.dumps(request, ensure_ascii=False),
                    status,
                    project_id,
                    float(estimated_cost),
                    now,
                    now,
                ),
            )
        return self.get(id)

    def get(self, generation_id: str) -> Optional[dict]:
        with self.lock:
            row = self.conn.execute(
                "SELECT * FROM generations WHERE id=?", (generation_id,)
            ).fetchone()
        if not row:
            return None
        out = dict(row)
        out["request"] = _loads(out.get("request"), {})
        out["remote_metadata"] = _loads(out.get("remote_metadata"), {})
        return out

    def update(self, generation_id: str, **fields) -> None:
        allowed = {
            "status",
            "remote_operation_id",
            "remote_file_uri",
            "remote_metadata",
            "error",
            "estimated_cost",
        }
        data = {k: v for k, v in fields.items() if k in allowed}
        if "remote_metadata" in data:
            data["remote_metadata"] = json.dumps(
                data["remote_metadata"] or {}, ensure_ascii=False
            )
        data["updated_at"] = time.time()
        sql = ", ".join(f"{k}=?" for k in data)
        with self.lock, self.conn:
            self.conn.execute(
                f"UPDATE generations SET {sql} WHERE id=?",
                (*data.values(), generation_id),
            )

    def add_output(
        self,
        generation_id: str,
        artifact_id: str,
        *,
        path="",
        mime="",
        sha256="",
        bytes=0,
        metadata=None,
    ) -> str:
        output_id = uuid.uuid4().hex
        with self.lock, self.conn:
            self.conn.execute(
                "INSERT INTO generation_outputs (id,generation_id,artifact_id,path,mime,sha256,bytes,metadata,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    output_id,
                    generation_id,
                    artifact_id,
                    path,
                    mime,
                    sha256,
                    int(bytes),
                    json.dumps(metadata or {}, ensure_ascii=False),
                    time.time(),
                ),
            )
        return output_id

    def artifact_ids(self, generation_id: str) -> list[str]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT artifact_id FROM generation_outputs WHERE generation_id=? AND artifact_id IS NOT NULL ORDER BY created_at",
                (generation_id,),
            ).fetchall()
        return [str(r[0]) for r in rows]

    def add_reference(self, artifact_id: str, source_artifact_id: str, role: str) -> None:
        with self.lock, self.conn:
            self.conn.execute(
                "INSERT INTO asset_references(id,artifact_id,source_artifact_id,role,created_at) "
                "VALUES (?,?,?,?,?)",
                (uuid.uuid4().hex, artifact_id, source_artifact_id, role or "reference", time.time()),
            )


class JobRepository(_Repository):
    ACTIVE = (
        "QUEUED",
        "PREPARING",
        "UPLOADING",
        "SUBMITTING",
        "SUBMITTED",
        "PROCESSING",
        "DOWNLOADING",
        "FINALIZING",
        "RETRY_WAIT",
        "RECOVERY_PENDING",
    )

    def create(
        self,
        *,
        id: str,
        generation_id: str,
        queue_type: str,
        state="QUEUED",
        max_attempts=3,
        created_at=None,
    ) -> dict:
        now = time.time() if created_at is None else float(created_at)
        with self.lock, self.conn:
            self.conn.execute(
                "INSERT INTO jobs (id,generation_id,queue_type,state,max_attempts,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                (id, generation_id, queue_type, state, int(max_attempts), now, now),
            )
        return self.get(id)

    def get(self, job_id: str) -> Optional[dict]:
        with self.lock:
            row = self.conn.execute(
                "SELECT j.*,g.provider,g.kind,g.operation,g.request,g.project_id,g.estimated_cost,g.remote_operation_id,g.remote_file_uri,g.remote_metadata,g.error "
                "FROM jobs j JOIN generations g ON g.id=j.generation_id WHERE j.id=?",
                (job_id,),
            ).fetchone()
        return self._decode(row)

    def list(
        self, *, active=None, project_id=None, limit=50, offset=0,
        include_request: bool = True,
    ) -> list[dict]:
        request_column = "g.request" if include_request else "NULL AS request"
        sql = (
            "SELECT j.*,g.provider,g.kind,g.operation,g.model,g.prompt,"
            f"{request_column},g.project_id,g.estimated_cost,g.remote_operation_id,g.remote_file_uri,g.remote_metadata,g.error "
            "FROM jobs j JOIN generations g ON g.id=j.generation_id"
        )
        where, params = [], []
        marks = ",".join("?" for _ in self.ACTIVE)
        if active is True:
            where.append(f"j.state IN ({marks})")
            params.extend(self.ACTIVE)
        elif active is False:
            where.append(f"j.state NOT IN ({marks})")
            params.extend(self.ACTIVE)
        if project_id:
            where.append("g.project_id=?")
            params.append(project_id)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY j.created_at DESC LIMIT ? OFFSET ?"
        params += [int(limit), int(offset)]
        with self.lock:
            rows = self.conn.execute(sql, params).fetchall()
        return [self._decode(r) for r in rows]

    def count_active(self) -> int:
        marks = ",".join("?" for _ in self.ACTIVE)
        with self.lock:
            row = self.conn.execute(
                f"SELECT COUNT(*) FROM jobs WHERE state IN ({marks})", self.ACTIVE
            ).fetchone()
        return int(row[0])

    def update(self, job_id: str, **fields) -> bool:
        allowed = {
            "state",
            "attempt",
            "next_run_at",
            "next_poll_at",
            "locked_at",
            "worker_id",
            "progress",
            "last_error",
        }
        data = {k: v for k, v in fields.items() if k in allowed}
        data["updated_at"] = time.time()
        sql = ", ".join(f"{k}=?" for k in data)
        with self.lock, self.conn:
            cur = self.conn.execute(
                f"UPDATE jobs SET {sql} WHERE id=?", (*data.values(), job_id)
            )
        return bool(cur.rowcount)

    def try_lock(
        self,
        job_id: str,
        worker_id: str,
        *,
        stale_before: float,
        expected_state: Optional[str] = None,
    ) -> bool:
        now = time.time()
        state_sql = " AND state=?" if expected_state is not None else ""
        params = [now, worker_id, now, job_id, stale_before]
        if expected_state is not None:
            params.append(expected_state)
        with self.lock, self.conn:
            cur = self.conn.execute(
                "UPDATE jobs SET locked_at=?,worker_id=?,updated_at=? WHERE id=? "
                f"AND (locked_at IS NULL OR locked_at<?){state_sql}",
                params,
            )
        return bool(cur.rowcount)

    def unlock(self, job_id: str) -> None:
        self.update(job_id, locked_at=None, worker_id=None)

    def delete(self, job_id: str) -> int:
        with self.lock, self.conn:
            cur = self.conn.execute(
                "DELETE FROM generations WHERE id=(SELECT generation_id FROM jobs WHERE id=?)",
                (job_id,),
            )
        return cur.rowcount

    def delete_terminal(self, *, kind=None, project_id=None) -> int:
        marks = ",".join("?" for _ in self.ACTIVE)
        sql = f"DELETE FROM generations WHERE id IN (SELECT g.id FROM generations g JOIN jobs j ON j.generation_id=g.id WHERE j.state NOT IN ({marks})"
        params = list(self.ACTIVE)
        if kind:
            sql += " AND g.kind=?"
            params.append(kind)
        if project_id:
            sql += " AND g.project_id=?"
            params.append(project_id)
        sql += ")"
        with self.lock, self.conn:
            cur = self.conn.execute(sql, params)
        return cur.rowcount

    @staticmethod
    def _decode(row):
        if not row:
            return None
        out = dict(row)
        if out.get("request") is None:
            out["request"] = {
                "provider": out.get("provider") or "xai",
                "model": out.get("model") or "",
                "prompt": out.get("prompt") or "",
            }
        else:
            out["request"] = _loads(out.get("request"), {})
        out["remote_metadata"] = _loads(out.get("remote_metadata"), {})
        return out


class UsageRepository(_Repository):
    def record(
        self,
        *,
        generation_id,
        provider,
        model,
        kind,
        units,
        unit_name,
        estimated_cost,
        actual_cost=None,
    ):
        with self.lock, self.conn:
            self.conn.execute(
                "INSERT INTO usage_records VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    uuid.uuid4().hex,
                    generation_id,
                    provider,
                    model,
                    kind,
                    float(units),
                    unit_name,
                    float(estimated_cost),
                    actual_cost,
                    time.time(),
                ),
            )

    def estimated_since(self, since: float) -> float:
        with self.lock:
            row = self.conn.execute(
                "SELECT COALESCE(SUM(COALESCE(actual_cost, estimated_cost)),0) FROM usage_records WHERE created_at>=?",
                (float(since),),
            ).fetchone()
        return float(row[0] or 0)


class RemoteFileCacheRepository(_Repository):
    def get(self, sha256: str, provider="google") -> Optional[dict]:
        now = time.time()
        with self.lock, self.conn:
            row = self.conn.execute(
                "SELECT * FROM remote_file_cache WHERE sha256=? AND provider=? AND expires_at>?",
                (sha256, provider, now),
            ).fetchone()
            self.conn.execute(
                "DELETE FROM remote_file_cache WHERE expires_at<=?", (now,)
            )
        return dict(row) if row else None

    def put(self, *, sha256, provider, remote_name, uri, mime, expires_at) -> None:
        with self.lock, self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO remote_file_cache VALUES (?,?,?,?,?,?,?)",
                (
                    sha256,
                    provider,
                    remote_name,
                    uri,
                    mime,
                    float(expires_at),
                    time.time(),
                ),
            )


class MediaRepositories:
    def __init__(self, conn, lock) -> None:
        self.generations = GenerationRepository(conn, lock)
        self.jobs = JobRepository(conn, lock)
        self.usage = UsageRepository(conn, lock)
        self.remote_files = RemoteFileCacheRepository(conn, lock)
