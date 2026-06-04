"""Trasy git dla workspace (status, diff) — przez subprocess `git`."""

from __future__ import annotations

import logging
import subprocess
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from grok_core.state import require_workspace

log = logging.getLogger(__name__)

router = APIRouter(prefix="/git", tags=["git"])


class StageReq(BaseModel):
    paths: Optional[List[str]] = None  # None/[] -> stage everything (git add -A)


class CommitReq(BaseModel):
    message: str
    stage_all: bool = False  # `git add -A` przed commitem (objęcie nowych plików)


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
def status(ws=Depends(require_workspace)) -> dict:
    code, out, err = _run_git(ws, ["status", "--porcelain=v1", "--branch"])
    if code != 0:
        # P1-13: nie zwracaj surowego stderr (może zawierać ścieżki bezwzględne).
        log.warning("git status failed: %s", err.strip())
        return {"is_repo": False, "detail": "Not a git repository or git unavailable."}
    branch = ""
    files = []
    for ln in out.splitlines():
        if ln.startswith("##"):
            branch = ln[3:].strip()
        elif ln.strip():
            files.append({"status": ln[:2].strip(), "path": ln[3:]})
    return {"is_repo": True, "branch": branch, "files": files}


@router.get("/diff")
def diff(path: str = "", ws=Depends(require_workspace)) -> dict:
    args = ["diff"]
    if path:
        args += ["--", path]
    code, out, err = _run_git(ws, args)
    if code != 0 and err.strip():
        log.warning("git diff failed: %s", err.strip())  # P1-13
        return {"is_repo": False, "detail": "git diff failed."}
    return {"diff": out}


@router.post("/add")
def stage(req: StageReq, ws=Depends(require_workspace)) -> dict:
    """Stage'uje wskazane ścieżki, lub wszystko (`git add -A`) gdy lista pusta."""
    args = ["add"] + (["--", *req.paths] if req.paths else ["-A"])
    code, out, err = _run_git(ws, args)
    if code != 0:
        log.warning("git add failed: %s", err.strip())  # P1-13
        raise HTTPException(status_code=400, detail="git add failed")
    return {"ok": True}


@router.post("/commit")
def commit(req: CommitReq, ws=Depends(require_workspace)) -> dict:
    message = (req.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Commit message is required")
    if req.stage_all:
        code, out, err = _run_git(ws, ["add", "-A"])
        if code != 0:
            log.warning("git add (stage_all) failed: %s", err.strip())  # P1-13
            raise HTTPException(status_code=400, detail="git add failed")
    code, out, err = _run_git(ws, ["commit", "-m", message])
    if code != 0:
        # P1-13: stdout+stderr gita (ścieżki, nazwy plików) tylko do logu.
        log.warning("git commit failed: %s", (out + err).strip())
        raise HTTPException(status_code=400, detail="git commit failed")
    return {"ok": True, "output": out.strip()}
