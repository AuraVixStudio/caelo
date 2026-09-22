"""Wspolny cennik i szacunki kosztu dostawcow (USD, informacyjne)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_HALF_UP
from math import ceil
from typing import Optional


IMAGE_COST_PER_IMAGE = {
    "grok-imagine-image": 0.02,
    "grok-imagine-image-2.0": 0.04,
    "grok-imagine-image-quality": 0.05,
}
XAI_IMAGE_OUTPUT_USD = {
    "grok-imagine-image-2.0": {
        ("1k", "low"): 0.04,
        ("2k", "low"): 0.06,
        ("1k", "medium"): 0.06,
        ("2k", "medium"): 0.08,
    },
    "grok-imagine-image-quality": {
        ("1k", "default"): 0.05,
        ("2k", "default"): 0.07,
    },
}
XAI_IMAGE_INPUT_USD = {
    "grok-imagine-image": 0.002,
    "grok-imagine-image-2.0": 0.01,
    "grok-imagine-image-quality": 0.01,
}
VIDEO_COST_PER_SECOND = {
    "grok-imagine-video": {"480p": 0.05, "720p": 0.07},
    "grok-imagine-video-1.5": {"480p": 0.08, "720p": 0.14, "1080p": 0.25},
}
DEFAULT_IMAGE_COST_PER_IMAGE = 0.02
DEFAULT_VIDEO_COST_PER_SECOND = 0.08

# Przeniesione z Gemini Desktop Studio. Pozostaja nieaktywne do podlaczenia
# adaptera Google w fazie 2, ale cennik ma juz jedno miejsce utrzymania.
GOOGLE_IMAGE_PRICING_UPDATED = "2026-09-01"
GOOGLE_IMAGE_OUTPUT_USD = {
    "gemini-3.1-flash-image": {
        "0.5k": 0.045, "1k": 0.067, "2k": 0.101, "4k": 0.151,
    },
    "gemini-3.1-flash-lite-image": {"1k": 0.0336},
    "gemini-3-pro-image": {"1k": 0.134, "2k": 0.134, "4k": 0.24},
    "gemini-2.5-flash-image": {"1k": 0.039},
}
GOOGLE_VIDEO_PER_SECOND_USD = {
    "gemini-omni-1.1-flash": 0.10,
    "veo-3.1-generate-preview": 0.40,
    "veo-3.1-fast-generate-preview": 0.10,
    "veo-3.1-lite-generate-preview": 0.05,
}
# Stawki wideo Google sa publikowane per model i rozdzielczosc.
GOOGLE_VIDEO_RATES_USD = {
    "veo-3.1-generate-preview": {"720p": 0.40, "1080p": 0.40, "4k": 0.60},
    "veo-3.1-fast-generate-preview": {"720p": 0.10, "1080p": 0.12, "4k": 0.30},
    "veo-3.1-lite-generate-preview": {"720p": 0.05, "1080p": 0.08},
    "gemini-omni-1.1-flash": {"360p": 0.10, "720p": 0.10, "1080p": 0.15, "4k": 0.25},
}

# Oficjalne stawki OpenAI API za 1M tokenów, zweryfikowane 2026-09-01.
# To jawnie wersjonowany snapshot: nieznany model zwraca None zamiast pozornego $0.
OPENAI_TEXT_PRICING_UPDATED = "2026-09-01"
OPENAI_TEXT_PER_MTOK_USD = {
    "gpt-5.6-sol": {"input": 4.00, "cached_input": 0.40, "output": 20.00},
    "gpt-5.6-terra": {"input": 2.00, "cached_input": 0.20, "output": 12.00},
    "gpt-5.6-luna": {"input": 0.20, "cached_input": 0.02, "output": 1.20},
}

# GPT Image 2: oficjalne stawki za 1M tokenow. Szacunek przed wyslaniem
# odwzorowuje kalkulator OpenAI, a po odpowiedzi jest zastepowany kosztem
# policzonym z rzeczywistego pola ``usage``.
OPENAI_IMAGE_PRICING_UPDATED = "2026-09-01"
OPENAI_IMAGE_PER_MTOK_USD = {
    "text_input": 5.00,
    "cached_text_input": 1.25,
    "image_input": 8.00,
    "cached_image_input": 2.00,
    "image_output": 30.00,
}
OPENAI_IMAGE_QUALITY_AXIS = {"low": 16, "medium": 48, "high": 96}


def _parse_image_size(size: object) -> Optional[tuple[int, int]]:
    value = str(size or "").lower().strip()
    if value == "auto":
        return 1024, 1024
    try:
        width, height = (int(part) for part in value.split("x", 1))
    except (TypeError, ValueError):
        return None
    if (
        width <= 0 or height <= 0
        or width % 16 or height % 16
        or width * height < 655_360 or width * height > 8_294_400
        or max(width, height) > 3_840
        or max(width, height) > 3 * min(width, height)
    ):
        return None
    return width, height


def openai_image_output_tokens(size: object, quality: object) -> Optional[int]:
    """Odwzoruj oficjalny kalkulator tokenow wyjściowych GPT Image 2.

    ``auto`` jest niepoznawalne przed wykonaniem, dlatego do preflightu stosujemy
    neutralny profil medium/1024x1024. Wynik rzeczywisty nadpisuje ten szacunek.
    """
    dimensions = _parse_image_size(size)
    if dimensions is None:
        return None
    quality_id = str(quality or "auto").lower()
    axis = OPENAI_IMAGE_QUALITY_AXIS.get(quality_id, OPENAI_IMAGE_QUALITY_AXIS["medium"])
    width, height = dimensions
    long_edge, short_edge = max(width, height), min(width, height)
    short_axis = int(
        (Decimal(axis * short_edge) / Decimal(long_edge)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    return ceil(
        axis * short_axis * (2_000_000 + width * height) / 4_000_000
    )


def openai_image_estimate(params: dict) -> Optional[float]:
    """Przybliz koszt outputu GPT Image 2; input rozliczy rzeczywiste ``usage``."""
    tokens = openai_image_output_tokens(
        params.get("resolution") or "auto", params.get("quality") or "auto"
    )
    if tokens is None:
        return None
    try:
        count = max(1, int(params.get("n", 1) or 1))
    except (TypeError, ValueError):
        return None
    amount = tokens * count * OPENAI_IMAGE_PER_MTOK_USD["image_output"] / 1_000_000
    return round(amount, 6)


def openai_image_cost_from_usage(
    usage: dict, *, has_image_input: bool = False
) -> Optional[float]:
    """Policz faktyczny koszt Images API z licznikow zwroconych przez OpenAI."""
    if not isinstance(usage, dict):
        return None
    try:
        input_tokens = max(0, int(usage.get("input_tokens", 0) or 0))
        output_tokens = max(0, int(usage.get("output_tokens", 0) or 0))
        details = usage.get("input_tokens_details") or {}
        if not isinstance(details, dict):
            details = {}
        text_tokens_raw = details.get("text_tokens")
        image_tokens_raw = details.get("image_tokens")
        if text_tokens_raw is None and image_tokens_raw is None:
            # Dla text-to-image cala czesc wejściowa jest tekstem. Przy edit bez
            # rozbicia modalności nie zgadujemy kosztu obrazu referencyjnego.
            if has_image_input:
                return None
            text_tokens, image_tokens = input_tokens, 0
        else:
            text_tokens = max(0, int(text_tokens_raw or 0))
            image_tokens = max(0, int(image_tokens_raw or 0))
        if text_tokens + image_tokens > input_tokens and input_tokens:
            return None
    except (TypeError, ValueError):
        return None
    rates = OPENAI_IMAGE_PER_MTOK_USD
    amount = (
        text_tokens * rates["text_input"]
        + image_tokens * rates["image_input"]
        + output_tokens * rates["image_output"]
    ) / 1_000_000
    return round(amount, 6)


def openai_cost_from_usage(model: str, usage: dict) -> Optional[float]:
    """Policz koszt z rzeczywistych liczników API; None dla nieznanego modelu.

    ``input_tokens`` obejmuje cache hits, dlatego odejmujemy ``cached_tokens`` od
    części pełnopłatnej. Reasoning tokens są już zawarte w ``output_tokens``.
    """
    rates = OPENAI_TEXT_PER_MTOK_USD.get(str(model or ""))
    if rates is None or not isinstance(usage, dict):
        return None
    try:
        input_tokens = max(0, int(usage.get("input_tokens", 0) or 0))
        output_tokens = max(0, int(usage.get("output_tokens", 0) or 0))
        details = usage.get("input_tokens_details") or {}
        cached_tokens = max(0, int(details.get("cached_tokens", 0) or 0)) \
            if isinstance(details, dict) else 0
        cached_tokens = min(cached_tokens, input_tokens)
    except (TypeError, ValueError):
        return None
    uncached_tokens = input_tokens - cached_tokens
    amount = (
        uncached_tokens * rates["input"]
        + cached_tokens * rates["cached_input"]
        + output_tokens * rates["output"]
    ) / 1_000_000
    return round(amount, 6)


@dataclass(frozen=True)
class PriceEstimate:
    provider: str
    model: str
    amount_usd: float
    estimated: bool = True
    no_cost: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def video_rate_per_second(model: str, resolution: Optional[str]) -> float:
    tiers = VIDEO_COST_PER_SECOND.get(model or "")
    if not tiers:
        return DEFAULT_VIDEO_COST_PER_SECOND
    res = str(resolution or "").lower()
    return tiers.get(res, tiers.get("480p", DEFAULT_VIDEO_COST_PER_SECOND))


def estimate_cost(kind: str, op: str, params: dict, provider: Optional[str] = None) -> float:
    """Zwraca dotychczasowy float, aby nie zmienic kontraktu kolejki."""
    provider_id = provider or params.get("provider") or "xai"
    if provider_id == "mock":
        return 0.0
    if provider_id == "google":
        try:
            model = str(params.get("model") or "")
            if kind == "image":
                tiers = GOOGLE_IMAGE_OUTPUT_USD.get(model)
                if not tiers:
                    return 0.0
                resolution = str(params.get("resolution") or "1k").lower()
                rate = tiers.get(resolution)
                if rate is None:
                    return 0.0
                return round(rate * max(1, int(params.get("n", 1) or 1)), 4)
            if kind == "video":
                resolution = str(params.get("resolution") or "720p").lower()
                tiers = GOOGLE_VIDEO_RATES_USD.get(model, {})
                rate = tiers.get(resolution, GOOGLE_VIDEO_PER_SECOND_USD.get(model, 0.20))
                seconds = max(1, int(params.get("duration", 8) or 8))
                return round(rate * seconds, 4)
        except (TypeError, ValueError):
            return 0.0
    if provider_id == "openai":
        if kind == "image" and str(params.get("model") or "gpt-image-2") == "gpt-image-2":
            return openai_image_estimate(params) or 0.0
        return 0.0
    if provider_id != "xai":
        return 0.0
    try:
        model = params.get("model") or ""
        if kind == "image":
            n = int(params.get("n", 1) or 1)
            resolution = str(params.get("resolution") or "1k").lower()
            quality = str(params.get("quality") or "auto").lower()
            if model == "grok-imagine-image-2.0" and quality == "auto":
                quality = "medium" if params.get("images") else "low"
            tiers = XAI_IMAGE_OUTPUT_USD.get(model, {})
            rate = tiers.get(
                (resolution, quality),
                tiers.get((resolution, "default"), IMAGE_COST_PER_IMAGE.get(
                    model, DEFAULT_IMAGE_COST_PER_IMAGE
                )),
            )
            reference_cost = (
                len(params.get("images") or ()) * XAI_IMAGE_INPUT_USD.get(model, 0.0)
            )
            return round(rate * max(1, n) + reference_cost, 4)
        if kind == "video":
            rate = video_rate_per_second(model, params.get("resolution"))
            duration = int(params.get("duration", 6) or 6)
            source = int(params.get("source_duration", 0) or 0)
            if op == "edit":
                billed = source or duration
            elif op == "extend":
                billed = source + duration if source else duration
            else:
                billed = duration
            return round(rate * max(1, billed), 4)
    except (TypeError, ValueError):
        pass
    return 0.0


def estimate(kind: str, op: str, params: dict, provider: Optional[str] = None) -> PriceEstimate:
    provider_id = provider or params.get("provider") or "xai"
    return PriceEstimate(provider_id, str(params.get("model") or ""),
                         estimate_cost(kind, op, params, provider_id),
                         no_cost=provider_id == "mock")
