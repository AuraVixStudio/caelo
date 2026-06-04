"""Trasy git dla workspace (status, diff) — przez subprocess `git`."""

from __future__ import annotations

import subprocess
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from grok_core.state import Backend, get_backend

router = APIRouter(prefix="/git", tags=["git"])


class StageReq(BaseModel):
    paths: Optional[List[str]] = None  # None/[] -> stage everything (git add -A)


class CommitReq(BaseModel):
    message: str
    stage_all: bool = False  # `git add -A` przed commitem (objęcie nowych plików)


def _require_ws(b: Backend):
    ws = b.get_workspace()
    if ws is None:
        raise HTTPException(status_code=400, detail="No workspace selected")
    return ws


def _run_git(ws, args, timeout=20):
    try:
        r = subprocess.run(
            ["git", *args], cwd=str(ws.root),
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
        )
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="git not found on PATH")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="git timed out")


@router.get("/status")
def status(b: Backend = Depends(get_backend)) -> dict:
    ws = _require_ws(b)
    code, out, err = _run_git(ws, ["status", "--porcelain=v1", "--branch"])
    if code != 0:
        return {"is_repo": False, "detail": err.strip()}
    branch = ""
    files = []
    for ln in out.splitlines():
        if ln.startswith("##"):
            branch = ln[3:].strip()
        elif ln.strip():
            files.append({"status": ln[:2].strip(), "path": ln[3:]})
    return {"is_repo": True, "branch": branch, "files": files}


@router.get("/diff")
def diff(path: str = "", b: Backend = Depends(get_backend)) -> dict:
    ws = _require_ws(b)
    args = ["diff"]
    if path:
        args += ["--", path]
    code, out, err = _run_git(ws, args)
    if code != 0 and err.strip():
        return {"is_repo": False, "detail": err.strip()}
    return {"diff": out}


@router.post("/add")
def stage(req: StageReq, b: Backend = Depends(get_backend)) -> dict:
    """Stage'uje wskazane ścieżki, lub wszystko (`git add -A`) gdy lista pusta."""
    ws = _require_ws(b)
    args = ["add"] + (["--", *req.paths] if req.paths else ["-A"])
    code, out, err = _run_git(ws, args)
    if code != 0:
        raise HTTPException(status_code=400, detail=err.strip() or "git add failed")
    return {"ok": True}


@router.post("/commit")
def commit(req: CommitReq, b: Backend = Depends(get_backend)) -> dict:
    ws = _require_ws(b)
    message = (req.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Commit message is required")
    if req.stage_all:
        code, out, err = _run_git(ws, ["add", "-A"])
        if code != 0:
            raise HTTPException(status_code=400, detail=err.strip() or "git add failed")
    code, out, err = _run_git(ws, ["commit", "-m", message])
    if code != 0:
        detail = (out + err).strip() or "git commit failed"
        raise HTTPException(status_code=400, detail=detail)
    return {"ok": True, "output": out.strip()}
