"""Trasy mediów: generowanie/edycja obrazów i zadania wideo (opakowanie APIManager).

Auto-zapis wyników do folderu wyjściowego + rejestracja w historii — jak w
legacy (ResultCard / _auto_save_video).
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator

from caelo_core import validation as V
from caelo_core.errors import upstream_error
from caelo_core.state import Backend, get_backend

router = APIRouter(tags=["media"])


class GenerateImageReq(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=V.MAX_PROMPT)
    n: int = Field(1, ge=1, le=V.MAX_N)
    aspect_ratio: str = Field("auto", max_length=16)
    resolution: str = Field("1k", max_length=8)
    model: Optional[str] = Field(None, max_length=64)


class EditImageReq(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=V.MAX_PROMPT)
    images: List[str] = Field(..., min_length=1, max_length=V.MAX_IMAGES)  # data-URI
    n: int = Field(1, ge=1, le=V.MAX_N)
    aspect_ratio: str = Field("auto", max_length=16)
    resolution: str = Field("1k", max_length=8)
    model: Optional[str] = Field(None, max_length=64)

    @field_validator("images")
    @classmethod
    def _check_images(cls, v: List[str]) -> List[str]:
        return [V.validate_image_uri(u) for u in v]


class VideoJobReq(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=V.MAX_PROMPT)
    duration: int = Field(8, ge=1, le=V.MAX_VIDEO_DURATION)
    resolution: str = Field("480p", max_length=8)
    aspect_ratio: str = Field("Original", max_length=16)
    model: Optional[str] = Field(None, max_length=64)
    image: Optional[str] = None  # data-URI: kadr startowy dla image-to-video

    @field_validator("image")
    @classmethod
    def _check_image(cls, v: Optional[str]) -> Optional[str]:
        return V.validate_image_uri(v) if v else v


class VideoEditReq(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=V.MAX_PROMPT)
    video: str  # URL (https) lub data-URI źródłowego wideo
    model: Optional[str] = Field(None, max_length=64)

    @field_validator("video")
    @classmethod
    def _check_video(cls, v: str) -> str:
        return V.validate_video_ref(v)


class VideoExtendReq(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=V.MAX_PROMPT)
    video: str  # URL (https) lub data-URI źródłowego wideo
    duration: Optional[int] = Field(None, ge=1, le=V.MAX_EXTEND_DURATION)  # dodane sekundy
    model: Optional[str] = Field(None, max_length=64)

    @field_validator("video")
    @classmethod
    def _check_video(cls, v: str) -> str:
        return V.validate_video_ref(v)


@router.post("/images/generate")
def images_generate(req: GenerateImageReq, b: Backend = Depends(get_backend)) -> dict:
    try:
        urls = b.api.generate_image(
            req.prompt, req.n, req.aspect_ratio, req.resolution, model=req.model
        )
    except Exception as exc:
        raise upstream_error(exc, "Media request to xAI failed")
    return {"results": b.save_media_urls(urls, req.prompt, "generate", ".png")}


@router.post("/images/edit")
def images_edit(req: EditImageReq, b: Backend = Depends(get_backend)) -> dict:
    try:
        urls = b.api.edit_image_b64(
            req.prompt, req.images, req.n, req.aspect_ratio, req.resolution, model=req.model
        )
    except Exception as exc:
        raise upstream_error(exc, "Media request to xAI failed")
    return {"results": b.save_media_urls(urls, req.prompt, "edit", ".png")}


@router.post("/video/jobs")
def video_create(req: VideoJobReq, b: Backend = Depends(get_backend)) -> dict:
    try:
        job_id = b.api.create_video_job(
            req.prompt, req.duration, req.resolution, req.aspect_ratio, None,
            model=req.model, image_data_uri=req.image
        )
    except Exception as exc:
        raise upstream_error(exc, "Media request to xAI failed")
    return {"request_id": job_id}


@router.post("/video/edits")
def video_edit(req: VideoEditReq, b: Backend = Depends(get_backend)) -> dict:
    try:
        job_id = b.api.edit_video_job(req.prompt, req.video, model=req.model)
    except Exception as exc:
        raise upstream_error(exc, "Media request to xAI failed")
    return {"request_id": job_id}


@router.post("/video/extensions")
def video_extend(req: VideoExtendReq, b: Backend = Depends(get_backend)) -> dict:
    try:
        job_id = b.api.extend_video_job(
            req.prompt, req.video, duration=req.duration, model=req.model
        )
    except Exception as exc:
        raise upstream_error(exc, "Media request to xAI failed")
    return {"request_id": job_id}


@router.get("/video/jobs/{job_id}")
def video_poll(job_id: str, b: Backend = Depends(get_backend)) -> dict:
    try:
        st = b.api.poll_video_status(job_id)
    except Exception as exc:
        raise upstream_error(exc, "Media request to xAI failed")
    if isinstance(st, dict) and st.get("status") == "done":
        url = (st.get("video") or {}).get("url")
        if url:
            saved = b.save_media_urls([url], "", "video", ".mp4")
            if saved:
                st["local_path"] = saved[0].get("path")
    return st
