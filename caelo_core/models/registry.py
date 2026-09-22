"""Jedno zrodlo prawdy o dostawcach, modelach i ich mozliwosciach."""

from __future__ import annotations

from typing import Any, Iterable, Optional

import config  # type: ignore

from .capabilities import ModelCapabilities, validate_capabilities
from .google_models import google_models
from .openai_models import openai_models
from .types import ModelDescriptor, ProviderDescriptor


class ModelRegistry:
    def __init__(self, providers: Iterable[ProviderDescriptor],
                 models: Iterable[ModelDescriptor]) -> None:
        self._providers = {p.id: p for p in providers}
        self._models = {(m.provider, m.id): m for m in models}

    def providers(self) -> list[ProviderDescriptor]:
        return list(self._providers.values())

    def provider(self, provider_id: str) -> Optional[ProviderDescriptor]:
        return self._providers.get(provider_id)

    def models(self, *, provider: Optional[str] = None,
               media_type: Optional[str] = None) -> list[ModelDescriptor]:
        values = self._models.values()
        return [m for m in values
                if (provider is None or m.provider == provider)
                and (media_type is None or m.media_type == media_type)]

    def find(self, provider: str, model_id: str) -> Optional[ModelDescriptor]:
        return self._models.get((provider, model_id))

    def default_for(self, provider: str, media_type: str) -> Optional[ModelDescriptor]:
        candidates = self.models(provider=provider, media_type=media_type)
        return next((m for m in candidates if m.is_default), candidates[0] if candidates else None)

    def resolve(self, provider: str, media_type: str,
                model_id: Optional[str] = None) -> ModelDescriptor:
        if self.provider(provider) is None:
            raise KeyError(f"Unknown provider: {provider}")
        model = self.find(provider, model_id) if model_id else self.default_for(provider, media_type)
        if model is None or model.media_type != media_type:
            raise KeyError(f"Unknown {media_type} model for {provider}: {model_id or '<default>'}")
        return model

    def validate(self, provider: str, media_type: str, operation: str,
                 params: Optional[dict[str, Any]] = None,
                 model_id: Optional[str] = None) -> ModelDescriptor:
        model = self.resolve(provider, media_type, model_id)
        # Gdy klient nie wskazal modelu, wybierz domyslny zdolny wykonac dana
        # operacje (np. bazowy model xAI dla edit/extend wideo).
        if model_id is None and operation not in model.capabilities.operations:
            model = next((candidate for candidate in self.models(
                provider=provider, media_type=media_type
            ) if operation in candidate.capabilities.operations), model)
        validate_capabilities(model.capabilities, operation, params)
        return model


_IMAGE_RATIOS = tuple(config.ASPECT_RATIOS)
_IMAGE_RESOLUTIONS = tuple(config.RESOLUTIONS)
_VIDEO_RATIOS = ("16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3")


def _image_model(model_id: str) -> ModelDescriptor:
    quality = model_id in config.IMAGE_QUALITY_MODELS
    max_references = 5 if model_id == "grok-imagine-image-2.0" else 3
    return ModelDescriptor(
        id=model_id,
        provider="xai",
        label=model_id,
        media_type="image",
        is_default=model_id == config.DEFAULT_IMAGE_MODEL,
        tier="pro" if model_id.endswith("quality") else "standard",
        capabilities=ModelCapabilities(
            operations=("text2img", "edit", "variation"),
            input_modalities=("text", "image"),
            output_modalities=("image",),
            aspect_ratios=_IMAGE_RATIOS,
            resolutions=_IMAGE_RESOLUTIONS,
            supports_quality=quality,
            quality_levels=tuple(config.IMAGE_QUALITY_LEVELS) if quality else (),
            max_reference_images=max_references,
            max_character_reference_images=max_references,
            max_object_reference_images=max_references,
            max_style_reference_images=max_references,
        ),
    )


def _video_model(model_id: str) -> ModelDescriptor:
    is_v15 = model_id == "grok-imagine-video-1.5"
    return ModelDescriptor(
        id=model_id,
        provider="xai",
        label=model_id,
        media_type="video",
        is_default=model_id == config.DEFAULT_VIDEO_MODEL,
        capabilities=ModelCapabilities(
            operations=(("text2video", "img2video", "reference_to_video") if is_v15 else
                        ("text2video", "img2video", "edit", "extend")),
            input_modalities=("text", "image", "video"),
            output_modalities=("video",),
            aspect_ratios=_VIDEO_RATIOS,
            resolutions=tuple(config.VIDEO_RESOLUTIONS_BY_MODEL[model_id]),
            duration_min=1,
            duration_max=15,
            max_reference_images=config.MAX_VIDEO_REFERENCE_IMAGES if is_v15 else 0,
            max_character_reference_images=config.MAX_VIDEO_REFERENCE_IMAGES if is_v15 else 0,
            max_object_reference_images=config.MAX_VIDEO_REFERENCE_IMAGES if is_v15 else 0,
            max_style_reference_images=config.MAX_VIDEO_REFERENCE_IMAGES if is_v15 else 0,
            notes=(("Reference images are supported; edit and extend use the base model.",)
                   if is_v15 else ()),
        ),
    )


def _chat_model(model_id: str) -> ModelDescriptor:
    thinking_levels = {
        "grok-4.6": ("low", "medium", "high", "xhigh"),
        "grok-4.5": ("low", "medium", "high"),
        "grok-4.3": ("none", "low", "medium", "high"),
        "grok-4.20-0309-reasoning": ("none", "low", "medium", "high"),
        "grok-4.20-multi-agent-0309": ("low", "medium", "high", "xhigh"),
    }.get(model_id, ())
    has_reasoning = model_id != "grok-4.20-0309-non-reasoning"
    return ModelDescriptor(
        id=model_id, provider="xai", label=model_id, media_type="chat",
        is_default=model_id == config.DEFAULT_CHAT_MODEL,
        status="stable",
        tier="pro" if model_id in {"grok-4.6", "grok-4.5"} else "standard",
        notes="Current xAI API model documented for text and image input.",
        capabilities=ModelCapabilities(
            operations=("chat",), input_modalities=("text", "image", "document"),
            output_modalities=("text",), supports_streaming=True, supports_tools=True,
            supports_temperature=True,
            thinking=has_reasoning,
            thinking_levels=thinking_levels,
            multi_turn=True,
        ),
    )


def _mock_model(model_id: str, media_type: str, operations: tuple[str, ...]) -> ModelDescriptor:
    return ModelDescriptor(
        id=model_id, provider="mock", label=f"Mock {media_type}", media_type=media_type,
        is_default=True, status="development", tier="free",
        notes="Local deterministic provider; performs no billable API calls.",
        capabilities=ModelCapabilities(
            operations=operations,
            input_modalities=("text", "image", "video"),
            output_modalities=(media_type if media_type != "chat" else "text",),
            aspect_ratios=_IMAGE_RATIOS if media_type == "image" else _VIDEO_RATIOS,
            resolutions=_IMAGE_RESOLUTIONS if media_type == "image" else ("480p", "720p", "1080p"),
            duration_min=1 if media_type == "video" else None,
            duration_max=15 if media_type == "video" else None,
            supports_quality=media_type == "image",
            quality_levels=("low", "medium") if media_type == "image" else (),
            max_reference_images=3,
            max_character_reference_images=3 if media_type in {"image", "video"} else 0,
            max_object_reference_images=3 if media_type in {"image", "video"} else 0,
            max_style_reference_images=3 if media_type in {"image", "video"} else 0,
            supports_streaming=media_type == "chat",
            supports_tools=media_type == "chat",
            supports_temperature=media_type == "chat",
        ),
    )


_REGISTRY = ModelRegistry(
    providers=(
        ProviderDescriptor("xai", "xAI", ("chat", "image", "video", "voice"),
                           ("oauth", "api_key")),
        ProviderDescriptor("mock", "Mock (local)", ("chat", "image", "video"),
                           ("none",), no_cost=True, status="development"),
        ProviderDescriptor("google", "Google Gemini / Vertex AI", ("chat", "image", "video"),
                           ("adc", "api_key")),
        ProviderDescriptor("openai", "OpenAI", ("chat", "image"), ("api_key",)),
    ),
    models=(
        *(_chat_model(m) for m in config.DEFAULT_CHAT_MODELS),
        *(_image_model(m) for m in config.IMAGE_MODELS),
        *(_video_model(m) for m in config.VIDEO_MODELS),
        _mock_model("mock-chat", "chat", ("chat",)),
        _mock_model("mock-image", "image", ("text2img", "edit", "variation")),
        _mock_model("mock-video", "video", ("text2video", "img2video", "edit", "extend")),
        *google_models(),
        *openai_models(),
    ),
)


def get_model_registry() -> ModelRegistry:
    return _REGISTRY
