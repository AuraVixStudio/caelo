"""Katalog modeli Google obslugiwanych przez media i czat Caelo."""

from __future__ import annotations

from .capabilities import ModelCapabilities
from .types import ModelDescriptor


IMAGE_RATIOS = ("1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9")
VIDEO_RATIOS = ("16:9", "9:16")


def google_models() -> tuple[ModelDescriptor, ...]:
    chat_specs = (
        # model, label, tier, status, default, configurable thinking, temperature
        # 3.8 Flash = GA 2026-09-02, najmocniejszy Flash (long-horizon coding/agenty).
        # `thinking_level` przyjmuje tylko low/medium/high — MINIMAL zwraca blad walidacji.
        ("gemini-3.8-flash", "Gemini 3.8 Flash", "pro", "stable", True, True, False),
        ("gemini-3.7-flash", "Gemini 3.7 Flash", "pro", "stable", False, True, False),
        ("gemini-3.6-flash", "Gemini 3.6 Flash", "standard", "stable", False, True, False),
        ("gemini-3.5-flash", "Gemini 3.5 Flash", "pro", "stable", False, True, False),
        ("gemini-3.1-pro-preview", "Gemini 3.1 Pro", "pro", "preview", False, True, False),
        ("gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite", "economy", "stable", False, True, False),
        ("gemini-3.1-flash-lite", "Gemini 3.1 Flash-Lite", "economy", "stable", False, True, False),
        ("gemini-2.5-pro", "Gemini 2.5 Pro", "legacy", "stable", False, False, True),
        ("gemini-2.5-flash", "Gemini 2.5 Flash", "legacy", "stable", False, False, True),
    )
    chats = tuple(ModelDescriptor(
        id=model_id, provider="google", label=label, media_type="chat",
        tier=tier, status=status, is_default=is_default,
        notes="Streaming text, image and PDF input. xAI/X live-search tools are unavailable.",
        capabilities=ModelCapabilities(
            operations=("chat",),
            input_modalities=("text", "image", "document"),
            output_modalities=("text",),
            supports_streaming=True,
            supports_tools=True,
            supports_temperature=supports_temperature,
            thinking=thinking,
            thinking_levels=("low", "medium", "high") if thinking else (),
            multi_turn=True,
        ),
    ) for (model_id, label, tier, status, is_default, thinking,
           supports_temperature) in chat_specs)

    image_specs = (
        # model, label, resolutions, thinking, grounding, total, characters, objects, styles,
        # tier, default, status
        ("gemini-3.1-flash-image", "Nano Banana 2", ("0.5k", "1k", "2k", "4k"), True, True, 14, 4, 10, 0, "standard", True, "stable"),
        ("gemini-3.1-flash-lite-image", "Nano Banana 2 Lite", ("1k",), False, False, 14, 0, 14, 0, "economy", False, "stable"),
        ("gemini-3-pro-image", "Nano Banana Pro", ("1k", "2k", "4k"), True, True, 14, 5, 6, 3, "pro", False, "stable"),
        # Google zapowiedzialo wylaczenie na 2026-10-02 — zostaje jako wybor wsteczny,
        # ale oznaczony, zeby nikt nie budowal na nim nowego workflow.
        ("gemini-2.5-flash-image", "Nano Banana (legacy)", ("1k",), False, False, 3, 1, 3, 0, "legacy", False, "deprecated"),
    )
    images = tuple(ModelDescriptor(
        id=model_id, provider="google", label=label, media_type="image",
        tier=tier, is_default=is_default, status=status,
        notes=("Google announced shutdown on 2026-10-02; prefer Nano Banana 2."
               if status == "deprecated" else
               "Verified against the Vertex AI publisher catalog on 2026-09-01."),
        capabilities=ModelCapabilities(
            operations=("text2img", "edit", "variation"),
            input_modalities=("text", "image"), output_modalities=("image",),
            aspect_ratios=IMAGE_RATIOS, resolutions=resolutions,
            max_reference_images=max_refs,
            max_character_reference_images=max_character_refs,
            max_object_reference_images=max_object_refs,
            max_style_reference_images=max_style_refs,
            thinking=thinking,
            thinking_levels=("minimal", "low", "medium", "high") if thinking else (),
            search_grounding=grounding, multi_turn=model_id.startswith("gemini-3"),
        ),
    ) for (model_id, label, resolutions, thinking, grounding, max_refs,
           max_character_refs, max_object_refs, max_style_refs, tier, is_default,
           status) in image_specs)

    omni = ModelDescriptor(
        id="gemini-omni-1.1-flash", provider="google", label="Gemini Omni 1.1 Flash",
        media_type="video", tier="standard", is_default=True,
        capabilities=ModelCapabilities(
            operations=("text2video", "img2video", "reference_to_video", "edit", "extend"),
            input_modalities=("text", "image", "video"), output_modalities=("video",),
            aspect_ratios=VIDEO_RATIOS, resolutions=("360p", "720p", "1080p", "4k"),
            duration_min=3, duration_max=10, max_reference_images=3,
            max_character_reference_images=3,
            max_object_reference_images=3,
            max_style_reference_images=3,
            multi_turn=True, native_audio=True, video_extension=True,
            edit_uploaded_video=True,
        ),
    )
    veo_specs = (
        ("veo-3.1-generate-preview", "Veo 3.1", "pro", True, True),
        ("veo-3.1-fast-generate-preview", "Veo 3.1 Fast", "fast", True, True),
        ("veo-3.1-lite-generate-preview", "Veo 3.1 Lite", "economy", False, False),
    )
    veo = tuple(ModelDescriptor(
        id=model_id, provider="google", label=label, media_type="video", tier=tier,
        status="preview",
        capabilities=ModelCapabilities(
            operations=(("text2video", "img2video", "reference_to_video", "first_last_frame", "extend")
                        if extension else ("text2video", "img2video")),
            input_modalities=("text", "image", "video"), output_modalities=("video",),
            aspect_ratios=VIDEO_RATIOS, resolutions=("720p", "1080p", "4k"),
            duration_min=4, duration_max=8, durations=(4, 6, 8),
            max_reference_images=3 if references else 0, native_audio=True,
            max_character_reference_images=3 if references else 0,
            max_object_reference_images=3 if references else 0,
            max_style_reference_images=3 if references else 0,
            supports_seed=True, first_last_frame=references, video_extension=extension,
            extension_seconds=7 if extension else None,
            extension_resolutions=("720p",) if extension else (),
            supports_negative_prompt=True,
        ),
    ) for model_id, label, tier, references, extension in veo_specs)
    return (*chats, *images, omni, *veo)
