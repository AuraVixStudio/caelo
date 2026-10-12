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

import config  # type: ignore

from caelo_core import validation as V
from caelo_core.genjobs import CostLimitExceeded, GenJobQueueFull
from caelo_core.models.capabilities import CapabilityError
from caelo_core.models.registry import get_model_registry
from caelo_core.state import Backend, get_backend

router = APIRouter(tags=["genjobs"])

# Google Nano Banana przyjmuje wiecej referencji; xAI zachowuje limit 3.
MAX_EDIT_REFS = 14


class ImageJobReq(BaseModel):
    provider: str = Field("xai", max_length=32)
    op: Literal["text2img", "edit", "variation"] = "text2img"
    prompt: str = Field(..., min_length=1, max_length=V.MAX_PROMPT)
    n: int = Field(1, ge=1, le=V.MAX_N)
    aspect_ratio: str = Field("auto", max_length=16)
    resolution: str = Field("1k", max_length=16)
    model: Optional[str] = Field(None, max_length=64)
    images: List[str] = Field(default_factory=list, max_length=MAX_EDIT_REFS)  # data-URI
    # grok-imagine-image-2.0: low|medium|auto (docs 2026-08). Dla innych modeli parametr jest
    # POMIJANY w `api_manager._apply_quality` (xAI odrzuca go 4xx), więc tu tylko go
    # walidujemy — nie zgadujemy, czy model go obsłuży.
    quality: Optional[Literal["low", "medium", "high", "auto"]] = None
    reference_roles: List[str] = Field(default_factory=list, max_length=14)
    thinking_level: Optional[Literal["minimal", "low", "medium", "high"]] = None
    search_grounding: bool = False
    mime_type: Literal["image/png", "image/jpeg", "image/webp"] = "image/png"
    output_format: Optional[Literal["png", "jpeg", "webp"]] = None
    output_compression: Optional[int] = Field(None, ge=0, le=100)
    background: Optional[Literal["auto", "opaque", "transparent"]] = None
    moderation: Optional[Literal["auto", "low"]] = None
    source_artifact_ids: List[str] = Field(default_factory=list, max_length=MAX_EDIT_REFS)
    source_artifact_roles: List[str] = Field(default_factory=list, max_length=MAX_EDIT_REFS)

    @field_validator("images")
    @classmethod
    def _check_images(cls, v: List[str]) -> List[str]:
        return [V.validate_image_uri(u) for u in v]

    @model_validator(mode="after")
    def _check_op(self) -> "ImageJobReq":
        if self.provider == "xai":
            # `grok-imagine-image-quality` (wycofany 2026-11-02) → 2.0 + low, także dla
            # starych ustawień renderera i retry; jawna jakość użytkownika zostaje.
            self.model, self.quality = config.normalize_image_model(self.model, self.quality)
            descriptor = get_model_registry().resolve(
                "xai", "image", self.model or None
            )
            limit = descriptor.capabilities.max_reference_images
            if len(self.images) > limit:
                raise ValueError(
                    f"{descriptor.id} image editing accepts at most {limit} reference images"
                )
        if self.background == "transparent" and self.output_format == "jpeg":
            raise ValueError("transparent background requires PNG or WebP output")
        if self.output_compression is not None and self.output_format not in {"jpeg", "webp"}:
            raise ValueError("output compression requires JPEG or WebP output")
        if self.op == "text2img":
            if self.images:
                raise ValueError("text2img takes no reference images")
        elif not self.images:
            raise ValueError(f"{self.op} requires 1-{MAX_EDIT_REFS} reference images")
        return self


class VideoJobReq(BaseModel):
    provider: str = Field("xai", max_length=32)
    op: Literal["text2video", "img2video", "reference_to_video", "first_last_frame", "edit", "extend"] = "text2video"
    prompt: str = Field(..., min_length=1, max_length=V.MAX_PROMPT)
    duration: int = Field(6, ge=1, le=V.MAX_VIDEO_DURATION)
    resolution: str = Field("480p", max_length=8)
    aspect_ratio: str = Field("Original", max_length=16)
    model: Optional[str] = Field(None, max_length=64)
    image: Optional[str] = None  # data-URI: kadr startowy dla img2video
    last_image: Optional[str] = None  # drugi kadr dla interpolacji Veo
    video: Optional[str] = None  # https URL lub data:video — źródło dla edit/extend
    # Reference-to-video (xAI: 1.5 do 14, bazowy do 7 — limit per model w rejestrze): obrazy
    # przenoszą postać/produkt/miejsce do klipu BEZ blokowania pierwszej klatki. Na 1.5
    # ortogonalne do `image` (kadr startowy) — mogą wystąpić razem; bazowy tego nie łączy.
    reference_images: List[str] = Field(default_factory=list, max_length=V.MAX_VIDEO_REFS)
    reference_roles: List[str] = Field(default_factory=list, max_length=V.MAX_VIDEO_REFS)
    # xAI 1.5: głosy presetowe (id z rosteru TTS) z lip-synciem, w promptcie <AUDIO_0>…
    reference_audios: List[str] = Field(default_factory=list, max_length=V.MAX_VIDEO_VOICES)
    # xAI 1.5: przypięte klatki pośrednie — dwie równoległe listy (data-URI + sekunda).
    keyframe_images: List[str] = Field(default_factory=list, max_length=V.MAX_VIDEO_KEYFRAMES)
    keyframe_times: List[float] = Field(default_factory=list, max_length=V.MAX_VIDEO_KEYFRAMES)
    generate_audio: bool = True
    seed: Optional[int] = Field(None, ge=0, le=4_294_967_295)
    negative_prompt: Optional[str] = Field(None, max_length=V.MAX_PROMPT)
    previous_interaction_id: Optional[str] = Field(None, max_length=256)
    # ROAD-3.6-d: długość źródła (s) dla edit/extend — wyjście zachowuje długość
    # źródła, więc koszt liczymy z niej, nie z domyślnego `duration`. Opcjonalne;
    # klient podaje, gdy zna długość źródła (np. z HTMLVideoElement.duration).
    source_duration: Optional[int] = Field(None, ge=1, le=V.MAX_VIDEO_DURATION)
    source_artifact_ids: List[str] = Field(default_factory=list, max_length=V.MAX_VIDEO_REFS + 2)
    source_artifact_roles: List[str] = Field(default_factory=list, max_length=V.MAX_VIDEO_REFS + 2)

    @field_validator("image")
    @classmethod
    def _check_image(cls, v: Optional[str]) -> Optional[str]:
        return V.validate_image_uri(v) if v else v

    @field_validator("last_image")
    @classmethod
    def _check_last_image(cls, v: Optional[str]) -> Optional[str]:
        return V.validate_image_uri(v) if v else v

    @field_validator("video")
    @classmethod
    def _check_video(cls, v: Optional[str]) -> Optional[str]:
        return V.validate_video_ref(v) if v else v

    @field_validator("reference_images", "keyframe_images")
    @classmethod
    def _check_reference_images(cls, v: List[str]) -> List[str]:
        return [V.validate_image_uri(u) for u in v]

    @field_validator("reference_audios")
    @classmethod
    def _check_voices(cls, v: List[str]) -> List[str]:
        return [str(x).strip().lower() for x in v if str(x).strip()]

    @model_validator(mode="after")
    def _check_op(self) -> "VideoJobReq":
        # Domysly starego formularza xAI nie sa prawidlowe dla Google. Przy
        # jawnym providerze ustaw bezpieczny podstawowy profil Google.
        if self.provider == "google":
            if self.resolution == "480p":
                self.resolution = "720p"
            if self.aspect_ratio == "Original":
                self.aspect_ratio = "16:9"
            if self.op == "extend" and (self.model or "").startswith("veo-"):
                self.duration = 7
            if self.op == "reference_to_video" and (self.model or "").startswith("veo-"):
                self.duration = 8
        if self.op == "img2video" and not self.image:
            raise ValueError("img2video requires a source image")
        if self.op == "text2video" and self.image:
            raise ValueError("text2video takes no source image")
        if self.op == "first_last_frame" and (not self.image or not self.last_image):
            raise ValueError("first_last_frame requires a starting and ending image")
        if self.op != "first_last_frame" and self.last_image:
            raise ValueError(f"{self.op} takes no ending image")
        if self.op == "reference_to_video" and not (self.reference_images or self.reference_audios):
            raise ValueError("reference_to_video requires reference images or voices")
        if len(self.keyframe_images) != len(self.keyframe_times):
            raise ValueError("each keyframe needs exactly one timestamp")
        if self.keyframe_times:
            # docs.x.ai: siatka 1/3 s, ściśle wewnątrz klipu, odstęp ≥ 1/3 s.
            thirds = [round(t * 3) for t in self.keyframe_times]
            if any(abs(t * 3 - q) > 1e-6 for t, q in zip(self.keyframe_times, thirds)):
                raise ValueError("keyframe timestamps must sit on a 1/3-second grid")
            if any(q <= 0 or q >= self.duration * 3 for q in thirds):
                raise ValueError("keyframe timestamps must fall strictly inside the clip")
            ordered = sorted(thirds)
            if any(b - a < 1 for a, b in zip(ordered, ordered[1:])):
                raise ValueError("keyframes must be at least 1/3 s apart")
        if self.op in ("edit", "extend"):
            if not self.video:
                raise ValueError(f"{self.op} requires a source video")
            if self.image:
                raise ValueError(f"{self.op} takes no source image")
            # /videos/edits i /videos/extensions nie znają `reference_images` — nie
            # przepuszczaj ich cicho, bo user straciłby je bez śladu.
            if self.reference_images or self.reference_audios or self.keyframe_images:
                raise ValueError(f"{self.op} takes no reference images, voices or keyframes")
            if self.op == "extend" and self.duration > V.MAX_EXTEND_DURATION:
                raise ValueError(f"extend duration must be <= {V.MAX_EXTEND_DURATION}s")
        elif self.video:
            raise ValueError(f"{self.op} takes no source video")
        return self


def _submit(b: Backend, *, kind: str, op: str, params: dict) -> dict:
    provider = params.get("provider") or "xai"
    try:
        descriptor = get_model_registry().validate(
            provider, kind, op, params, params.get("model") or None
        )
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except CapabilityError as exc:
        raise HTTPException(status_code=422, detail=exc.to_dict())
    # Utrwal konkretny model, aby koszt, retry i adapter uzywaly tego samego
    # wyboru (szczegolnie edit/extend wideo -> model bazowy xAI).
    if not params.get("model"):
        params["model"] = descriptor.id
    try:
        job = b.genjobs.submit(kind=kind, op=op, params=params,
                               project_id=b.current_project_id)
    except GenJobQueueFull as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    except CostLimitExceeded as exc:
        raise HTTPException(status_code=402, detail=str(exc))
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
