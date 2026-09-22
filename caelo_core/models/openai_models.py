"""Testowany katalog modeli OpenAI dla Chat i Code/Agent."""

from __future__ import annotations

from .capabilities import ModelCapabilities
from .types import ModelDescriptor


def openai_models() -> tuple[ModelDescriptor, ...]:
    specs = (
        # id, label, tier, default
        ("gpt-5.6-terra", "GPT-5.6 Terra", "standard", True),
        ("gpt-5.6-sol", "GPT-5.6 Sol", "pro", False),
        ("gpt-5.6-luna", "GPT-5.6 Luna", "economy", False),
    )
    chat_models = tuple(ModelDescriptor(
        id=model_id,
        provider="openai",
        label=label,
        media_type="chat",
        tier=tier,
        is_default=is_default,
        notes=(
            "OpenAI Responses API; streaming, image/file input and function calling. "
            "Availability is verified against the authenticated API project."
        ),
        capabilities=ModelCapabilities(
            operations=("chat",),
            input_modalities=("text", "image", "document"),
            output_modalities=("text",),
            supports_streaming=True,
            supports_tools=True,
            supports_temperature=False,
            thinking=True,
            thinking_levels=("none", "low", "medium", "high", "xhigh", "max"),
            multi_turn=True,
        ),
    ) for model_id, label, tier, is_default in specs)
    image_model = ModelDescriptor(
        id="gpt-image-2",
        provider="openai",
        label="GPT Image 2",
        media_type="image",
        tier="pro",
        is_default=True,
        notes=(
            "OpenAI Images API generation and high-fidelity multi-image editing. "
            "Content filtering is always active; low is the least restrictive mode."
        ),
        capabilities=ModelCapabilities(
            operations=("text2img", "edit", "variation"),
            input_modalities=("text", "image"),
            output_modalities=("image",),
            resolutions=(
                "1024x1024", "1536x1024", "1024x1536", "2048x2048",
                "2048x1152", "3840x2160", "2160x3840", "auto",
            ),
            supports_quality=True,
            quality_levels=("low", "medium", "high", "auto"),
            output_formats=("png", "jpeg", "webp"),
            backgrounds=("auto", "opaque", "transparent"),
            supports_output_compression=True,
            moderation_levels=("low", "auto"),
            # OpenAI documents one-or-more reference images but no smaller public
            # model limit; Caelo keeps its existing upload cap as a local guard.
            max_reference_images=14,
            max_character_reference_images=14,
            max_object_reference_images=14,
            max_style_reference_images=14,
        ),
    )
    return (*chat_models, image_model)
