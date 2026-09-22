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
from caelo_core.models.capabilities import CapabilityError
from caelo_core.models.registry import get_model_registry
from caelo_core.providers import (
    ImageGenerationRequest,
    VideoGenerationRequest,
    VideoSubmission,
)
from caelo_core.state import Backend, get_backend

router = APIRouter(tags=["media"])


class GenerateImageReq(BaseModel):
    provider: str = Field("xai", max_length=32)
    prompt: str = Field(..., min_length=1, max_length=V.MAX_PROMPT)
    n: int = Field(1, ge=1, le=V.MAX_N)
    aspect_ratio: str = Field("auto", max_length=16)
    resolution: str = Field("1k", max_length=8)
    model: Optional[str] = Field(None, max_length=64)
    thinking_level: Optional[str] = Field(None, max_length=16)
    search_grounding: bool = False


class EditImageReq(BaseModel):
    provider: str = Field("xai", max_length=32)
    prompt: str = Field(..., min_length=1, max_length=V.MAX_PROMPT)
    images: List[str] = Field(..., min_length=1, max_length=V.MAX_IMAGES)  # data-URI
    n: int = Field(1, ge=1, le=V.MAX_N)
    aspect_ratio: str = Field("auto", max_length=16)
    resolution: str = Field("1k", max_length=8)
    model: Optional[str] = Field(None, max_length=64)
    reference_roles: List[str] = Field(default_factory=list, max_length=14)
    thinking_level: Optional[str] = Field(None, max_length=16)
    search_grounding: bool = False

    @field_validator("images")
    @classmethod
    def _check_images(cls, v: List[str]) -> List[str]:
        return [V.validate_image_uri(u) for u in v]


class VideoJobReq(BaseModel):
    provider: str = Field("xai", max_length=32)
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
    provider: str = Field("xai", max_length=32)
    prompt: str = Field(..., min_length=1, max_length=V.MAX_PROMPT)
    video: str  # URL (https) lub data-URI źródłowego wideo
    model: Optional[str] = Field(None, max_length=64)

    @field_validator("video")
    @classmethod
    def _check_video(cls, v: str) -> str:
        return V.validate_video_ref(v)


class VideoExtendReq(BaseModel):
    provider: str = Field("xai", max_length=32)
    prompt: str = Field(..., min_length=1, max_length=V.MAX_PROMPT)
    video: str  # URL (https) lub data-URI źródłowego wideo
    duration: Optional[int] = Field(None, ge=1, le=V.MAX_EXTEND_DURATION)  # dodane sekundy
    model: Optional[str] = Field(None, max_length=64)

    @field_validator("video")
    @classmethod
    def _check_video(cls, v: str) -> str:
        return V.validate_video_ref(v)


def _validate(provider: str, media_type: str, operation: str,
              model: Optional[str], params: dict):
    try:
        return get_model_registry().validate(provider, media_type, operation, params, model)
    except KeyError as exc:
        raise upstream_error(exc, "Unknown provider or model", status=422)
    except CapabilityError as exc:
        raise upstream_error(exc, str(exc), status=422)


@router.post("/images/generate")
def images_generate(req: GenerateImageReq, b: Backend = Depends(get_backend)) -> dict:
    params = req.model_dump()
    descriptor = _validate(req.provider, "image", "text2img", req.model, params)
    try:
        result = b.get_provider(req.provider).generate_image(ImageGenerationRequest(
            prompt=req.prompt, model=req.model or descriptor.id, count=req.n,
            aspect_ratio=req.aspect_ratio, resolution=req.resolution,
            thinking_level=req.thinking_level, search_grounding=req.search_grounding,
        ))
    except Exception as exc:
        raise upstream_error(exc, "Media provider request failed")
    return {"results": b.save_provider_outputs(result.outputs, req.prompt, "generate", ".png",
                                                meta_extra={"provider": req.provider})}


@router.post("/images/edit")
def images_edit(req: EditImageReq, b: Backend = Depends(get_backend)) -> dict:
    params = req.model_dump()
    descriptor = _validate(req.provider, "image", "edit", req.model, params)
    try:
        result = b.get_provider(req.provider).generate_image(ImageGenerationRequest(
            prompt=req.prompt, operation="edit", model=req.model or descriptor.id, count=req.n,
            aspect_ratio=req.aspect_ratio, resolution=req.resolution,
            images=tuple(req.images),
            reference_roles=tuple(req.reference_roles), thinking_level=req.thinking_level,
            search_grounding=req.search_grounding,
        ))
    except Exception as exc:
        raise upstream_error(exc, "Media provider request failed")
    return {"results": b.save_provider_outputs(result.outputs, req.prompt, "edit", ".png",
                                                meta_extra={"provider": req.provider})}


@router.post("/video/jobs")
def video_create(req: VideoJobReq, b: Backend = Depends(get_backend)) -> dict:
    operation = "img2video" if req.image else "text2video"
    descriptor = _validate(req.provider, "video", operation, req.model, req.model_dump())
    try:
        submission = b.get_provider(req.provider).submit_video(VideoGenerationRequest(
            prompt=req.prompt, operation=operation, model=req.model or descriptor.id, duration=req.duration,
            resolution=req.resolution, aspect_ratio=req.aspect_ratio, image=req.image,
        ))
    except Exception as exc:
        raise upstream_error(exc, "Media provider request failed")
    return {"request_id": submission.remote_id, "provider": submission.provider}


@router.post("/video/edits")
def video_edit(req: VideoEditReq, b: Backend = Depends(get_backend)) -> dict:
    descriptor = _validate(req.provider, "video", "edit", req.model, req.model_dump())
    try:
        submission = b.get_provider(req.provider).submit_video(VideoGenerationRequest(
            prompt=req.prompt, operation="edit", model=req.model or descriptor.id, video=req.video,
        ))
    except Exception as exc:
        raise upstream_error(exc, "Media provider request failed")
    return {"request_id": submission.remote_id, "provider": submission.provider}


@router.post("/video/extensions")
def video_extend(req: VideoExtendReq, b: Backend = Depends(get_backend)) -> dict:
    descriptor = _validate(req.provider, "video", "extend", req.model, req.model_dump())
    try:
        submission = b.get_provider(req.provider).submit_video(VideoGenerationRequest(
            prompt=req.prompt, operation="extend", model=req.model or descriptor.id, video=req.video,
            duration=req.duration,
        ))
    except Exception as exc:
        raise upstream_error(exc, "Media provider request failed")
    return {"request_id": submission.remote_id, "provider": submission.provider}


@router.get("/video/jobs/{job_id}")
def video_poll(job_id: str, provider: str = "xai",
               b: Backend = Depends(get_backend)) -> dict:
    try:
        normalized = b.get_provider(provider).poll_video(VideoSubmission(provider, job_id))
    except Exception as exc:
        raise upstream_error(exc, "Media provider request failed")
    # Dla xAI zwracamy oryginalny slownik 1:1. To utrzymuje kontrakt starego UI.
    st = dict(normalized.raw)
    if provider != "xai":
        st.setdefault("status", "done" if normalized.state == "succeeded" else normalized.state)
        st["provider"] = provider
    if normalized.state == "succeeded" and normalized.output:
        if normalized.output.url:
            saved = b.save_provider_outputs([normalized.output], "", "video", ".mp4",
                                            meta_extra={"provider": provider})
            if saved:
                st["local_path"] = saved[0].get("path")
        elif normalized.output.data is not None:
            saved = b.save_provider_outputs([normalized.output], "", "video", ".mp4",
                                            meta_extra={"provider": provider})
            if saved:
                st["local_path"] = saved[0].get("path")
    return st
