"""Faza 4 OpenAI: wersjonowany cennik i koszt z rzeczywistego usage."""

from caelo_core.models.pricing import (
    OPENAI_IMAGE_PRICING_UPDATED,
    OPENAI_TEXT_PRICING_UPDATED,
    estimate_cost,
    openai_image_cost_from_usage,
    openai_image_output_tokens,
    openai_cost_from_usage,
)


def test_openai_cost_separates_cached_input_and_output_tokens() -> None:
    cost = openai_cost_from_usage("gpt-5.6-terra", {
        "input_tokens": 1_000_000,
        "input_tokens_details": {"cached_tokens": 250_000},
        "output_tokens": 100_000,
    })
    assert cost == 2.75
    # Snapshot cennika jest jawnie wersjonowany — data rusza się tylko po ponownym
    # sprawdzeniu stawek u dostawcy (ostatnio: katalog OpenAI, 2026-09-01).
    assert OPENAI_TEXT_PRICING_UPDATED == "2026-09-01"


def test_openai_unknown_model_has_no_false_zero_cost() -> None:
    assert openai_cost_from_usage("future-model", {
        "input_tokens": 100, "output_tokens": 10,
    }) is None


def test_openai_invalid_usage_is_not_priced() -> None:
    assert openai_cost_from_usage("gpt-5.6-terra", {
        "input_tokens": "not-a-number",
    }) is None


def test_gpt_image_2_estimate_matches_official_calculator_presets() -> None:
    assert openai_image_output_tokens("1024x1024", "low") == 196
    assert estimate_cost("image", "text2img", {
        "provider": "openai", "model": "gpt-image-2",
        "resolution": "1024x1024", "quality": "medium", "n": 1,
    }) == 0.05268
    assert estimate_cost("image", "text2img", {
        "provider": "openai", "model": "gpt-image-2",
        "resolution": "1024x1536", "quality": "high", "n": 1,
    }) == 0.16464
    assert OPENAI_IMAGE_PRICING_UPDATED == "2026-09-01"


def test_gpt_image_2_actual_cost_uses_modal_usage_breakdown() -> None:
    assert openai_image_cost_from_usage({
        "input_tokens": 300,
        "input_tokens_details": {"text_tokens": 100, "image_tokens": 200},
        "output_tokens": 1_000,
    }, has_image_input=True) == 0.0321


def test_gpt_image_2_edit_without_modal_breakdown_is_not_falsely_priced() -> None:
    assert openai_image_cost_from_usage({
        "input_tokens": 300, "output_tokens": 1_000,
    }, has_image_input=True) is None
