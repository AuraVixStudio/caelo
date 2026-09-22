"""Testowany katalog modeli OpenAI dla Chat i Code/Agent."""

from __future__ import annotations

from .capabilities import ModelCapabilities
from .types import ModelDescriptor


def openai_models() -> tuple[ModelDescriptor, ...]:
    # id, label, tier, default, poziomy reasoning_effort.
    # gpt-6-astra to flagowiec (1.05M kontekstu), ale kosztuje 5x wiecej na wejsciu i
    # ~4x na wyjsciu niz Terra, wiec domyslnym modelem pozostaje Terra — wybor Astry
    # jest swiadoma decyzja uzytkownika. Astra NIE dokumentuje poziomu `none`.
    _ALL_EFFORTS = ("none", "low", "medium", "high", "xhigh", "max")
    specs = (
        ("gpt-6-astra", "GPT-6 Astra", "pro", False,
         ("low", "medium", "high", "xhigh", "max")),
        ("gpt-5.6-terra", "GPT-5.6 Terra", "standard", True, _ALL_EFFORTS),
        ("gpt-5.6-sol", "GPT-5.6 Sol", "pro", False, _ALL_EFFORTS),
        ("gpt-5.6-luna", "GPT-5.6 Luna", "economy", False, _ALL_EFFORTS),
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
            thinking_levels=thinking_levels,
            multi_turn=True,
        ),
    ) for model_id, label, tier, is_default, thinking_levels in specs)
    # GPT Image 2.5 (sunburst/flare) doklada poziomy jakosci `xhigh`/`max` i wlasne
    # wymiary WxH (wielokrotnosc 16, proporcje 1:3..3:1). Cennik tokenowy jest wspolny
    # dla calej rodziny, wiec `pricing.OPENAI_IMAGE_PER_MTOK_USD` zostaje jeden.
    image_specs = (
        # id, label, tier, default, poziomy quality
        ("gpt-image-2", "GPT Image 2", "pro", True,
         ("low", "medium", "high", "auto")),
        ("gpt-image-2.5-sunburst", "GPT Image 2.5 Sunburst", "pro", False,
         ("low", "medium", "high", "xhigh", "max", "auto")),
        ("gpt-image-2.5-flare", "GPT Image 2.5 Flare", "standard", False,
         ("low", "medium", "high", "xhigh", "max", "auto")),
    )
    image_models = tuple(ModelDescriptor(
        id=model_id,
        provider="openai",
        label=label,
        media_type="image",
        tier=tier,
        is_default=is_default,
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
            quality_levels=quality_levels,
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
    ) for model_id, label, tier, is_default, quality_levels in image_specs)
    return (*chat_models, *image_models)
