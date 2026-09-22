"""Adapter Gemini Omni i Veo 3.1 z pollingiem asynchronicznych operacji."""

from __future__ import annotations

import base64
from typing import Any, Iterable, Optional

from caelo_core.providers.base import MediaOutput, VideoGenerationRequest, VideoPollStatus, VideoSubmission
from caelo_core.providers.errors import ErrorCategory, ProviderError

from .client import GoogleClient
from .files import GoogleFileManager
from .image import extract_inline_media, parse_data_uri


VERTEX_VEO_IDS = {
    "veo-3.1-generate-preview": "veo-3.1-generate-001",
    "veo-3.1-fast-generate-preview": "veo-3.1-fast-generate-001",
    "veo-3.1-lite-generate-preview": "veo-3.1-lite-generate-001",
}
# Ta sama sytuacja co przy Veo: AI Studio i Vertex nazywaja TEN SAM model inaczej.
# LIVE 2026-09-01 na Interactions Vertexa: `gemini-omni-1.1-flash` -> 400 "Unsupported
# model interaction", a `gemini-omni-1.1-flash-preview` przechodzi walidacje modelu.
# Mapujemy wylacznie NA DRUCIE, zeby id w katalogu, cenniku, zadaniach i artefaktach
# zostalo jedno (dokladnie jak `VERTEX_VEO_IDS`).
VERTEX_OMNI_IDS = {
    "gemini-omni-1.1-flash": "gemini-omni-1.1-flash-preview",
}


def _walk(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _inline(value: str, expected: str) -> dict[str, str]:
    mime, data = parse_data_uri(value, expected)
    return {"bytesBase64Encoded": data, "mimeType": mime}


def _video_output(value: Any, client: GoogleClient) -> Optional[MediaOutput]:
    inline = extract_inline_media(value, "video")
    if inline:
        return inline[0]
    for node in _walk(value):
        mime = str(node.get("mimeType") or node.get("mime_type") or "video/mp4")
        data = (node.get("bytesBase64Encoded") or node.get("bytes_base64_encoded")
                or node.get("videoBytes") or (node.get("data") if node.get("type") == "video" else None))
        if isinstance(data, str) and (mime.startswith("video/") or "video" in node):
            return MediaOutput(data=base64.b64decode(data), mime_type=mime, extension=".mp4")
        uri = node.get("uri") or node.get("videoUri") or node.get("video_uri") or node.get("gcsUri")
        if isinstance(uri, str) and (mime.startswith("video/") or node.get("type") == "video"):
            if uri.startswith("https://"):
                return MediaOutput(data=client.download(uri), mime_type=mime, extension=".mp4")
            return MediaOutput(url=uri, mime_type=mime, extension=".mp4")
    return None


def _task(operation: str) -> str:
    return {
        "img2video": "image_to_video",
        "reference_to_video": "reference_to_video",
        "first_last_frame": "image_to_video",
        "edit": "edit",
        "extend": "extend",
    }.get(operation, "text_to_video")


class GoogleVideoProvider:
    provider_id = "google"

    def __init__(self, client: GoogleClient, remote_cache=None) -> None:
        self.client = client
        self.files = GoogleFileManager(client, remote_cache)

    def validate_connection(self) -> dict[str, Any]:
        return self.client.validate_connection()

    def submit_video(self, request: VideoGenerationRequest) -> VideoSubmission:
        if not request.model:
            raise ProviderError("Google video model is required", provider="google",
                                category=ErrorCategory.INVALID_INPUT)
        if request.model.startswith("gemini-omni"):
            return self._submit_omni(request)
        if request.model.startswith("veo-"):
            return self._submit_veo(request)
        raise ProviderError("Unsupported Google video engine", provider="google",
                            category=ErrorCategory.UNSUPPORTED)

    def _submit_omni(self, request: VideoGenerationRequest) -> VideoSubmission:
        content: list[dict[str, Any]] = [{"type": "text", "text": request.prompt}]
        for value in ((request.image,) if request.image else ()) + request.reference_images:
            mime, data = parse_data_uri(value, "image")
            content.append({"type": "image", "data": data, "mime_type": mime})
        if request.video:
            mime, data = parse_data_uri(request.video, "video")
            if self.client.config().is_vertex:
                content.append({"type": "video", "data": data, "mime_type": mime})
            else:
                remote = self.files.upload_bytes(base64.b64decode(data), mime, "caelo-video-input")
                content.append({"type": "video", "uri": remote.uri, "mime_type": mime})
        response_format: dict[str, Any] = {
            "type": "video", "delivery": "inline",
            "aspect_ratio": "16:9" if request.aspect_ratio in {"Original", "auto"} else request.aspect_ratio,
            "resolution": request.resolution, "duration": f"{request.duration}s",
        }
        config = self.client.config()
        wire_model = (VERTEX_OMNI_IDS.get(request.model, request.model)
                      if config.is_vertex else request.model)
        payload: dict[str, Any] = {
            "model": wire_model, "input": content,
            "response_format": [response_format] if config.is_vertex else response_format,
            "generation_config": {"video_config": {"task": _task(request.operation)}},
            "store": True, "background": True,
        }
        if request.previous_interaction_id:
            payload["previous_interaction_id"] = request.previous_interaction_id
        response = self.client.create_interaction(payload)
        remote_id = str(response.get("id") or response.get("name") or "")
        if not remote_id:
            raise ProviderError(
                "Google accepted the Omni request without an interaction id; do not retry automatically",
                provider="google", category=ErrorCategory.REMOTE,
            )
        return VideoSubmission("google", remote_id, request.model,
                               {"kind": "interaction", "engine": "omni",
                                "wire_model": wire_model, "response": response})

    def _submit_veo(self, request: VideoGenerationRequest) -> VideoSubmission:
        c = self.client.config()
        wire_model = VERTEX_VEO_IDS.get(request.model, request.model) if c.is_vertex else request.model
        instance: dict[str, Any] = {"prompt": request.prompt}
        parameters: dict[str, Any] = {
            "sampleCount": 1, "fps": 24, "durationSeconds": request.duration or 8,
            "aspectRatio": "16:9" if request.aspect_ratio in {"Original", "auto"} else request.aspect_ratio,
            "resolution": request.resolution, "generateAudio": request.generate_audio,
        }
        if request.seed is not None:
            parameters["seed"] = request.seed
        if request.negative_prompt:
            parameters["negativePrompt"] = request.negative_prompt
        if request.operation == "img2video":
            if not request.image:
                raise ProviderError("Image-to-video requires a starting image", provider="google",
                                    category=ErrorCategory.INVALID_INPUT)
            instance["image"] = _inline(request.image, "image")
        elif request.operation == "first_last_frame":
            if not request.image or not request.last_image:
                raise ProviderError("First/last frame requires two images", provider="google",
                                    category=ErrorCategory.INVALID_INPUT)
            instance["image"] = _inline(request.image, "image")
            parameters["lastFrame"] = _inline(request.last_image, "image")
        elif request.operation == "reference_to_video":
            parameters["referenceImages"] = [
                {"image": _inline(value, "image"),
                 "referenceType": "style" if idx < len(request.reference_roles)
                 and request.reference_roles[idx] == "style" else "asset"}
                for idx, value in enumerate(request.reference_images)
            ]
            parameters["durationSeconds"] = 8
        elif request.operation == "extend":
            if not request.video:
                raise ProviderError("Video extension requires a source video", provider="google",
                                    category=ErrorCategory.INVALID_INPUT)
            if c.is_vertex:
                instance["video"] = _inline(request.video, "video")
            else:
                mime, encoded = parse_data_uri(request.video, "video")
                remote = self.files.upload_bytes(base64.b64decode(encoded), mime, "caelo-veo-input")
                instance["video"] = {"uri": remote.uri, "mimeType": mime}
            parameters["resolution"] = "720p"
            parameters["durationSeconds"] = 7
        payload = {"instances": [instance], "parameters": parameters}
        response = self.client.submit_veo(wire_model, payload)
        operation = str(response.get("name") or "")
        if not operation:
            raise ProviderError(
                "Google accepted the Veo request without an operation name; do not retry automatically",
                provider="google", category=ErrorCategory.REMOTE,
            )
        return VideoSubmission("google", operation, request.model,
                               {"kind": "operation", "engine": "veo", "wire_model": wire_model,
                                "response": response})

    def poll_video(self, submission: VideoSubmission) -> VideoPollStatus:
        kind = submission.metadata.get("kind")
        if kind == "interaction" or (submission.model or "").startswith("gemini-omni"):
            response = self.client.get_interaction(submission.remote_id)
            status = str(response.get("status") or "").lower()
            if status in {"failed", "cancelled", "incomplete", "budget_exceeded"}:
                return VideoPollStatus("failed", error_message=f"Google reported {status}", raw=response)
            if status not in {"completed", "succeeded", "done"}:
                return VideoPollStatus("running", raw=response)
            output = _video_output(response, self.client)
        else:
            wire_model = str(submission.metadata.get("wire_model") or submission.model or "")
            response = self.client.get_veo_operation(wire_model, submission.remote_id)
            if not response.get("done"):
                return VideoPollStatus("running", raw=response)
            error = response.get("error")
            if error:
                message = error.get("message") if isinstance(error, dict) else str(error)
                return VideoPollStatus("failed", error_message=message or "Veo failed", raw=response)
            output = _video_output(response.get("response", response), self.client)
        if output is None:
            return VideoPollStatus("failed", error_message="Google finished without returning video data",
                                   raw=response)
        return VideoPollStatus("succeeded", output=output, progress_percent=100, raw=response)
