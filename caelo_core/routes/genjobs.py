"""M11: trasy zadań generacji (jednolita kolejka obrazu/wideo) — `GenJob`.

  POST /genjobs/image          — zakolejkuj obraz (text2img | edit | variation)
  POST /genjobs/video          — zakolejkuj wideo (text2video | img2video)
  GET  /genjobs                — lista zadań (+ active/project_id/paginacja) + suma kosztu
  GET  /genjobs/{id}           — status pojedynczego zadania
  POST /genjobs/{id}/cancel    — anuluj (queued → od razu; running → sygnał)
  POST /genjobs/{id}/retry     — ponów failed/cancelled jako NOWE zadanie

Silnik: `caelo_core.genjobs.GenJobManager` przez `Backend.genjobs` (worker w wątku;
wyjścia → artefakty M9). Wszystkie trasy są pod globalnym guardem tokenu w `server.py`
(P1-10, fail-closed). Limity wejścia z `validation.py` (naruszenie → 422). Transport
statusu to REST polling (renderer odpytuje `/genjobs`) — patrz PLAN_M11 §0.
"""

from __future__ import annotations

from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator, model_validator

from caelo_core import validation as V
from caelo_core.genjobs import GenJobQueueFull
from caelo_core.state import Backend, get_backend

router = APIRouter(tags=["genjobs"])

# PLAN_M11: edycja/warianty komponują z DO 3 obrazów referencyjnych.
MAX_EDIT_REFS = 3


class ImageJobReq(BaseModel):
    op: Literal["text2img", "edit", "variation"] = "text2img"
    prompt: str = Field(..., min_length=1, max_length=V.MAX_PROMPT)
    n: int = Field(1, ge=1, le=V.MAX_N)
    aspect_ratio: str = Field("auto", max_length=16)
    resolution: str = Field("1k", max_length=8)
    model: Optional[str] = Field(None, max_length=64)
    images: List[str] = Field(default_factory=list, max_length=MAX_EDIT_REFS)  # data-URI

    @field_validator("images")
    @classmethod
    def _check_images(cls, v: List[str]) -> List[str]:
        return [V.validate_image_uri(u) for u in v]

    @model_validator(mode="after")
    def _check_op(self) -> "ImageJobReq":
        if self.op == "text2img":
            if self.images:
                raise ValueError("text2img takes no reference images")
        elif not self.images:
            raise ValueError(f"{self.op} requires 1-{MAX_EDIT_REFS} reference images")
        return self


class VideoJobReq(BaseModel):
    op: Literal["text2video", "img2video", "edit", "extend"] = "text2video"
    prompt: str = Field(..., min_length=1, max_length=V.MAX_PROMPT)
    duration: int = Field(6, ge=1, le=V.MAX_VIDEO_DURATION)
    resolution: str = Field("480p", max_length=8)
    aspect_ratio: str = Field("Original", max_length=16)
    model: Optional[str] = Field(None, max_length=64)
    image: Optional[str] = None  # data-URI: kadr startowy dla img2video
    video: Optional[str] = None  # https URL lub data:video — źródło dla edit/extend

    @field_validator("image")
    @classmethod
    def _check_image(cls, v: Optional[str]) -> Optional[str]:
        return V.validate_image_uri(v) if v else v

    @field_validator("video")
    @classmethod
    def _check_video(cls, v: Optional[str]) -> Optional[str]:
        return V.validate_video_ref(v) if v else v

    @model_validator(mode="after")
    def _check_op(self) -> "VideoJobReq":
        if self.op == "img2video" and not self.image:
            raise ValueError("img2video requires a source image")
        if self.op == "text2video" and self.image:
            raise ValueError("text2video takes no source image")
        if self.op in ("edit", "extend"):
            if not self.video:
                raise ValueError(f"{self.op} requires a source video")
            if self.image:
                raise ValueError(f"{self.op} takes no source image")
            if self.op == "extend" and self.duration > V.MAX_EXTEND_DURATION:
                raise ValueError(f"extend duration must be <= {V.MAX_EXTEND_DURATION}s")
        elif self.video:
            raise ValueError(f"{self.op} takes no source video")
        return self


def _submit(b: Backend, *, kind: str, op: str, params: dict) -> dict:
    try:
        job = b.genjobs.submit(kind=kind, op=op, params=params,
                               project_id=b.current_project_id)
    except GenJobQueueFull as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    return {"job": job.to_dict()}


@router.post("/genjobs/image")
def submit_image(req: ImageJobReq, b: Backend = Depends(get_backend)) -> dict:
    # op jest polem GenJob, nie parametrem — nie duplikuj go w params.
    return _submit(b, kind="image", op=req.op, params=req.model_dump(exclude={"op"}))


@router.post("/genjobs/video")
def submit_video(req: VideoJobReq, b: Backend = Depends(get_backend)) -> dict:
    return _submit(b, kind="video", op=req.op, params=req.model_dump(exclude={"op"}))


@router.get("/genjobs")
def list_jobs(
    b: Backend = Depends(get_backend),
    active: Optional[bool] = Query(None),
    project_id: Optional[str] = Query(None, max_length=V.MAX_ID_LEN),
    limit: int = Query(50, ge=1, le=V.MAX_HISTORY_LIMIT),
    offset: int = Query(0, ge=0),
) -> dict:
    jobs = b.genjobs.list_jobs(active=active, project_id=project_id,
                               limit=limit, offset=offset)
    # Koszt INCURRED = suma po zadaniach zakończonych sukcesem (BYO-key, B5).
    total_cost = round(sum(j.cost for j in jobs if j.status == "done"), 4)
    return {"jobs": [j.to_dict() for j in jobs],
            "total_cost": total_cost, "count": len(jobs),
            "limit": limit, "offset": offset}


@router.delete("/genjobs")
def clear_jobs(
    b: Backend = Depends(get_backend),
    kind: Optional[str] = Query(None, max_length=16),
    project_id: Optional[str] = Query(None, max_length=V.MAX_ID_LEN),
) -> dict:
    """Wyczyść zakończone zadania z listy (done/failed/cancelled). Artefakty (media)
    NIE są usuwane — zostają w galerii. Aktywne zadania pozostają."""
    cleared = b.genjobs.clear_finished(kind=kind, project_id=project_id)
    return {"cleared": cleared}


@router.get("/genjobs/{job_id}")
def get_job(job_id: str, b: Backend = Depends(get_backend)) -> dict:
    job = b.genjobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"job": job.to_dict()}


@router.delete("/genjobs/{job_id}")
def delete_job(job_id: str, b: Backend = Depends(get_backend)) -> dict:
    """Usuń jedno zakończone zadanie z listy (artefakt zostaje). Aktywne → 409."""
    if b.genjobs.get(job_id) is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if not b.genjobs.remove(job_id):
        raise HTTPException(status_code=409, detail="Job is still active")
    return {"ok": True}


@router.post("/genjobs/{job_id}/cancel")
def cancel_job(job_id: str, b: Backend = Depends(get_backend)) -> dict:
    job = b.genjobs.cancel(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"job": job.to_dict()}


@router.post("/genjobs/{job_id}/retry")
def retry_job(job_id: str, b: Backend = Depends(get_backend)) -> dict:
    try:
        job = b.genjobs.retry(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except GenJobQueueFull as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"job": job.to_dict()}
