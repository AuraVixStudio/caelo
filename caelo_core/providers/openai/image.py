"""Generowanie i edycja obrazów przez OpenAI Images API."""

from __future__ import annotations

import base64
from typing import Any

from caelo_core.providers.base import ImageGenerationRequest, ImageGenerationResult, MediaOutput
from caelo_core.providers.errors import ErrorCategory, ProviderError, normalize_provider_error

from .client import OpenAIClient


_FORMAT_MEDIA = {
    "png": ("image/png", ".png"),
    "jpeg": ("image/jpeg", ".jpg"),
    "webp": ("image/webp", ".webp"),
}
_MIME_FORMAT = {mime: fmt for fmt, (mime, _) in _FORMAT_MEDIA.items()}
_PORTRAIT_RATIOS = {"9:16", "2:3", "3:4", "4:5", "1:2", "9:19.5", "9:20"}
_LANDSCAPE_RATIOS = {"16:9", "3:2", "4:3", "5:4", "2:1", "19.5:9", "20:9", "21:9"}


def _parse_data_uri(value: str) -> tuple[str, bytes]:
    if not isinstance(value, str) or not value.startswith("data:image/") or ";base64," not in value:
        raise ProviderError(
            "OpenAI image inputs must be base64 image data URIs",
            provider="openai", category=ErrorCategory.INVALID_INPUT,
        )
    header, encoded = value.split(",", 1)
    mime = header[5:].split(";", 1)[0].lower()
    try:
        return mime, base64.b64decode(encoded, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise ProviderError(
            "Invalid base64 image input", provider="openai",
            category=ErrorCategory.INVALID_INPUT, cause=exc,
        ) from exc


def _size(request: ImageGenerationRequest) -> str:
    value = str(request.resolution or "auto").lower()
    if value == "auto" or "x" in value:
        return value
    ratio = str(request.aspect_ratio or "auto")
    if value == "4k":
        return "2160x3840" if ratio in _PORTRAIT_RATIOS else "3840x2160"
    if value == "2k":
        if ratio in _PORTRAIT_RATIOS:
            return "1152x2048"
        if ratio in _LANDSCAPE_RATIOS:
            return "2048x1152"
        return "2048x2048"
    if ratio in _PORTRAIT_RATIOS:
        return "1024x1536"
    if ratio in _LANDSCAPE_RATIOS:
        return "1536x1024"
    return "1024x1024"


def _role_hint(roles: tuple[str, ...]) -> str:
    hints: list[str] = []
    if "starting_image" in roles:
        hints.append("Treat the first starting image as the base composition to edit.")
    for role, instruction in (
        ("character", "preserve character identity"),
        ("object", "preserve the depicted objects"),
        ("style", "use only as visual style references"),
    ):
        count = roles.count(role)
        if count:
            hints.append(f"Use {count} {role} reference image(s) to {instruction}.")
    return " ".join(hints)


class OpenAIImageProvider:
    provider_id = "openai"

    def __init__(self, client: OpenAIClient) -> None:
        self.client = client

    def validate_connection(self) -> dict[str, Any]:
        return self.client.validate_connection()

    @staticmethod
    def _format(request: ImageGenerationRequest) -> str:
        requested = str(request.output_format or "").lower()
        if requested in _FORMAT_MEDIA:
            return requested
        return _MIME_FORMAT.get(str(request.mime_type or "").lower(), "png")

    def _fields(self, request: ImageGenerationRequest) -> dict[str, Any]:
        output_format = self._format(request)
        roles = request.reference_roles or tuple("general" for _ in request.images)
        hint = _role_hint(roles)
        prompt = f"{request.prompt}\n\nReference guidance: {hint}" if hint else request.prompt
        fields: dict[str, Any] = {
            "model": request.model or "gpt-image-2",
            "prompt": prompt,
            "n": max(1, int(request.count)),
            "size": _size(request),
            "quality": request.quality or "auto",
            "output_format": output_format,
            # OpenAI does not offer OFF; low is the least restrictive documented mode.
            "moderation": request.moderation or "low",
        }
        if request.background:
            fields["background"] = request.background
        if request.output_compression is not None and output_format in {"jpeg", "webp"}:
            fields["output_compression"] = int(request.output_compression)
        return fields

    @staticmethod
    def _raise_for_error(response: Any) -> None:
        status = int(getattr(response, "status_code", 200) or 200)
        if status < 400:
            return
        try:
            payload = response.json()
        except Exception:  # noqa: BLE001
            payload = {}
        error = payload.get("error") if isinstance(payload, dict) else {}
        error = error if isinstance(error, dict) else {}
        code = str(error.get("code") or "") or None
        error_type = str(error.get("type") or "")
        if code == "moderation_blocked":
            details = error.get("moderation_details") or {}
            stage = details.get("moderation_stage") if isinstance(details, dict) else None
            message = "OpenAI blocked image generation under its content policy"
            if stage in {"input", "output"}:
                message += f" ({stage})"
            raise ProviderError(
                message, provider="openai", category=ErrorCategory.SAFETY,
                retryable=False, code=code, status_code=status,
            )
        if error_type == "image_generation_user_error":
            raise ProviderError(
                "OpenAI rejected the image request; revise the prompt or reference images",
                provider="openai", category=ErrorCategory.INVALID_INPUT,
                retryable=False, code=code, status_code=status,
            )
        try:
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            raise normalize_provider_error(exc, "openai") from exc
        raise ProviderError(
            "OpenAI image request failed", provider="openai",
            category=ErrorCategory.REMOTE, retryable=status >= 500,
            code=code, status_code=status,
        )

    def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        if request.operation not in {"text2img", "edit", "variation"}:
            raise ProviderError(
                f"Unsupported OpenAI image operation: {request.operation}",
                provider="openai", category=ErrorCategory.UNSUPPORTED,
            )
        if request.operation != "text2img" and not request.images:
            raise ProviderError(
                f"{request.operation} requires reference images", provider="openai",
                category=ErrorCategory.INVALID_INPUT,
            )

        fields = self._fields(request)
        headers = {
            "Authorization": f"Bearer {self.client.api_key()}",
            "Accept": "application/json",
        }
        try:
            if request.operation == "text2img":
                response = self.client.session.post(
                    f"{self.client.base_url}/images/generations",
                    headers=headers, json=fields, timeout=180,
                )
            else:
                files = []
                for index, image in enumerate(request.images, start=1):
                    mime, raw = _parse_data_uri(image)
                    extension = _FORMAT_MEDIA.get(_MIME_FORMAT.get(mime, "png"), (mime, ".png"))[1]
                    files.append(("image[]", (f"reference-{index}{extension}", raw, mime)))
                response = self.client.session.post(
                    f"{self.client.base_url}/images/edits",
                    headers=headers,
                    data={key: str(value) for key, value in fields.items()},
                    files=files,
                    timeout=180,
                )
            self._raise_for_error(response)
            payload = response.json()
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise normalize_provider_error(exc, "openai") from exc

        output_format = self._format(request)
        mime, extension = _FORMAT_MEDIA[output_format]
        outputs: list[MediaOutput] = []
        try:
            for item in payload.get("data") or []:
                encoded = item.get("b64_json") if isinstance(item, dict) else None
                if encoded:
                    outputs.append(MediaOutput(
                        data=base64.b64decode(encoded, validate=True),
                        mime_type=mime, extension=extension,
                    ))
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(
                "OpenAI returned invalid image data", provider="openai",
                category=ErrorCategory.REMOTE, retryable=True, code="INVALID_IMAGE_DATA",
                cause=exc,
            ) from exc
        if not outputs:
            raise ProviderError(
                "OpenAI completed without returning an image", provider="openai",
                category=ErrorCategory.REMOTE, retryable=True, code="NO_IMAGE",
            )

        metadata: dict[str, Any] = {
            "model": fields["model"], "transport": "images_api",
            "size": fields["size"], "quality": fields["quality"],
            "output_format": output_format,
        }
        if isinstance(payload.get("usage"), dict):
            metadata["usage"] = payload["usage"]
        request_id = getattr(response, "headers", {}).get("x-request-id")
        if request_id:
            metadata["request_id"] = request_id
        return ImageGenerationResult(tuple(outputs), metadata=metadata)
