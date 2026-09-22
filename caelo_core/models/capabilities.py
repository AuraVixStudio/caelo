"""Deklaratywne mozliwosci modeli i walidacja przed platnym wywolaniem."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class ModelCapabilities:
    operations: tuple[str, ...]
    input_modalities: tuple[str, ...]
    output_modalities: tuple[str, ...]
    aspect_ratios: tuple[str, ...] = ()
    resolutions: tuple[str, ...] = ()
    duration_min: Optional[int] = None
    duration_max: Optional[int] = None
    durations: tuple[int, ...] = ()
    supports_quality: bool = False
    quality_levels: tuple[str, ...] = ()
    output_formats: tuple[str, ...] = ()
    backgrounds: tuple[str, ...] = ()
    supports_output_compression: bool = False
    moderation_levels: tuple[str, ...] = ()
    max_reference_images: int = 0
    max_character_reference_images: int = 0
    max_object_reference_images: int = 0
    max_style_reference_images: int = 0
    supports_streaming: bool = False
    supports_tools: bool = False
    supports_temperature: bool = False
    thinking: bool = False
    thinking_levels: tuple[str, ...] = ()
    search_grounding: bool = False
    multi_turn: bool = False
    native_audio: bool = False
    supports_seed: bool = False
    first_last_frame: bool = False
    video_extension: bool = False
    extension_seconds: Optional[int] = None
    extension_resolutions: tuple[str, ...] = ()
    edit_uploaded_video: bool = False
    supports_negative_prompt: bool = False
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CapabilityViolation:
    field: str
    message: str


class CapabilityError(ValueError):
    def __init__(self, violations: list[CapabilityViolation]) -> None:
        self.violations = tuple(violations)
        super().__init__(" ".join(v.message for v in violations))

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": "unsupported_capability",
            "violations": [asdict(v) for v in self.violations],
        }


def validate_capabilities(
    capabilities: ModelCapabilities,
    operation: str,
    params: Optional[dict[str, Any]] = None,
) -> None:
    """Rzuca CapabilityError z wszystkimi naruszeniami, nie tylko pierwszym."""
    p = params or {}
    violations: list[CapabilityViolation] = []
    if operation not in capabilities.operations:
        violations.append(CapabilityViolation(
            "operation", f"Model does not support operation {operation}."
        ))

    ratio = p.get("aspect_ratio")
    if ratio and ratio != "Original" and capabilities.aspect_ratios \
            and ratio not in capabilities.aspect_ratios:
        violations.append(CapabilityViolation(
            "aspect_ratio", f"Model does not support aspect ratio {ratio}."
        ))
    resolution = p.get("resolution")
    if resolution and capabilities.resolutions and resolution not in capabilities.resolutions:
        violations.append(CapabilityViolation(
            "resolution", f"Model does not support resolution {resolution}."
        ))
    quality = p.get("quality")
    if quality and not capabilities.supports_quality:
        violations.append(CapabilityViolation(
            "quality", "Model does not support the quality parameter."
        ))
    elif quality and capabilities.quality_levels and quality not in capabilities.quality_levels:
        violations.append(CapabilityViolation(
            "quality", f"Model does not support quality level {quality}."
        ))

    output_format = p.get("output_format")
    if output_format and output_format not in capabilities.output_formats:
        violations.append(CapabilityViolation(
            "output_format", "Model does not support the requested output format."
        ))
    background = p.get("background")
    if background and background not in capabilities.backgrounds:
        violations.append(CapabilityViolation(
            "background", "Model does not support the requested background mode."
        ))
    compression = p.get("output_compression")
    if compression is not None and not capabilities.supports_output_compression:
        violations.append(CapabilityViolation(
            "output_compression", "Model does not support output compression."
        ))
    moderation = p.get("moderation")
    if moderation and moderation not in capabilities.moderation_levels:
        violations.append(CapabilityViolation(
            "moderation", "Model does not support the requested moderation level."
        ))

    refs = p.get("reference_images") or p.get("images") or []
    if len(refs) > capabilities.max_reference_images:
        violations.append(CapabilityViolation(
            "references",
            f"Model accepts at most {capabilities.max_reference_images} reference images.",
        ))
    roles = list(p.get("reference_roles") or [])
    allowed_roles = {"character", "general", "object", "style", "starting_image"}
    unknown_roles = sorted({str(role) for role in roles if role not in allowed_roles})
    if unknown_roles:
        violations.append(CapabilityViolation(
            "reference_roles", f"Unknown reference role(s): {', '.join(unknown_roles)}.",
        ))
    if roles and len(roles) != len(refs):
        violations.append(CapabilityViolation(
            "reference_roles", "Each reference image must have exactly one role.",
        ))

    role_limits = {
        "character": capabilities.max_character_reference_images,
        "object": capabilities.max_object_reference_images,
        "style": capabilities.max_style_reference_images,
    }
    for role, limit in role_limits.items():
        count = roles.count(role)
        if count > limit:
            message = (f"Model does not support {role} reference images." if limit == 0 else
                       f"Model accepts at most {limit} {role} reference images.")
            violations.append(CapabilityViolation("reference_roles", message))
    if roles.count("starting_image") > 1:
        violations.append(CapabilityViolation(
            "reference_roles", "Only one starting image is allowed.",
        ))
    if roles.count("starting_image") and "edit" not in capabilities.operations:
        violations.append(CapabilityViolation(
            "reference_roles", "Model does not support a starting image for editing.",
        ))
    duration = p.get("duration")
    if duration is not None:
        try:
            seconds = int(duration)
            if capabilities.duration_min is not None and seconds < capabilities.duration_min:
                violations.append(CapabilityViolation(
                    "duration", f"Duration must be at least {capabilities.duration_min}s."
                ))
            if capabilities.duration_max is not None and seconds > capabilities.duration_max:
                violations.append(CapabilityViolation(
                    "duration", f"Duration must be at most {capabilities.duration_max}s."
                ))
            if operation != "extend" and capabilities.durations and seconds not in capabilities.durations:
                allowed = ", ".join(str(v) for v in capabilities.durations)
                violations.append(CapabilityViolation(
                    "duration", f"Duration must be one of: {allowed}s."
                ))
        except (TypeError, ValueError):
            violations.append(CapabilityViolation("duration", "Duration must be an integer."))

    thinking = p.get("thinking_level")
    if thinking and not capabilities.thinking:
        violations.append(CapabilityViolation(
            "thinking_level", "Model does not support configurable thinking."
        ))
    elif thinking and capabilities.thinking_levels and thinking not in capabilities.thinking_levels:
        violations.append(CapabilityViolation(
            "thinking_level", f"Model does not support thinking level {thinking}."
        ))
    if p.get("search_grounding") and not capabilities.search_grounding:
        violations.append(CapabilityViolation(
            "search_grounding", "Model does not support Google Search grounding."
        ))
    if p.get("seed") is not None and not capabilities.supports_seed:
        violations.append(CapabilityViolation("seed", "Model does not support seed."))
    if p.get("negative_prompt") and not capabilities.supports_negative_prompt:
        violations.append(CapabilityViolation(
            "negative_prompt", "Model does not support a negative prompt."
        ))
    if operation == "first_last_frame" and not capabilities.first_last_frame:
        violations.append(CapabilityViolation(
            "operation", "Model does not support first/last frame interpolation."
        ))
    if operation == "extend" and not capabilities.video_extension:
        violations.append(CapabilityViolation(
            "operation", "Model does not support video extension."
        ))

    if violations:
        raise CapabilityError(violations)
