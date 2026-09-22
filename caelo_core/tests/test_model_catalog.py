"""Snapshot katalogu modeli trzech dostawców — sprawdzony 2026-09-01.

Katalog jest ręcznie utrzymywaną listą, więc łatwo o ciche rozjechanie się z tym, co
dostawca faktycznie serwuje. Te asercje pilnują ustaleń z ostatniej weryfikacji:

* xAI — `docs.x.ai/developers/models` (7 modeli czatu, 3 obrazu, 2 wideo). Slugi
  wycofane 2026-05-15 (`grok-4-0709`/`grok-4`, `grok-3`, `grok-code-fast-1`,
  `grok-imagine-image-pro`, rodziny `*-fast-*`) NADAL się rozwiązują, ale milcząco
  przekierowują na `grok-4.3` i są po jego cenach — nie mogą wrócić do menu.
* Google — lista publisher models z Vertex AI (projekt użytkownika, ADC).
  `gemini-2.5-flash-image` ma ogłoszone wyłączenie 2026-10-02.
* OpenAI — `developers.openai.com/api/docs/models`. `gpt-5.6-cyber` i `gpt-daybreak-*`
  wymagają osobnej zgody (program Daybreak), więc CELOWO nie ma ich w katalogu:
  dla zwykłego konta byłyby pozycją, która zawsze kończy się błędem.
"""

from __future__ import annotations

import config  # type: ignore

from caelo_core.models.registry import get_model_registry


CATALOG_VERIFIED = "2026-09-01"

# Wycofane u dostawcy — pozycja w menu kłamałaby, który model faktycznie liczy.
RETIRED_XAI_SLUGS = {
    "grok-4", "grok-4-0709", "grok-3", "grok-3-mini", "grok-code-fast-1",
    "grok-4-fast-reasoning", "grok-4-fast-non-reasoning",
    "grok-4-1-fast-reasoning", "grok-4-1-fast-non-reasoning",
    "grok-imagine-image-pro",
}
# Dostępne wyłącznie po zgodzie programu Daybreak — nie dla zwykłego klucza.
GATED_OPENAI_MODELS = {"gpt-5.6-cyber", "gpt-daybreak-red-latest", "gpt-daybreak-blue-latest"}


def ids(provider: str, media_type: str) -> list[str]:
    return [m.id for m in get_model_registry().models(provider=provider, media_type=media_type)]


def test_xai_catalog_matches_published_models() -> None:
    assert ids("xai", "chat") == [
        "grok-4.6", "grok-4.5", "grok-4.3",
        "grok-4.20-0309-non-reasoning", "grok-4.20-0309-reasoning",
        "grok-4.20-multi-agent-0309", "grok-build-0.1",
    ]
    assert ids("xai", "image") == [
        "grok-imagine-image", "grok-imagine-image-2.0", "grok-imagine-image-quality",
    ]
    assert ids("xai", "video") == ["grok-imagine-video-1.5", "grok-imagine-video"]


def test_retired_xai_slugs_are_not_offered() -> None:
    offered = set(ids("xai", "chat")) | set(ids("xai", "image")) | set(ids("xai", "video"))
    assert offered.isdisjoint(RETIRED_XAI_SLUGS)
    assert set(config.DEFAULT_CHAT_MODELS).isdisjoint(RETIRED_XAI_SLUGS)


def test_voice_realtime_model_is_pinned_to_a_version() -> None:
    # Docs zalecają pin; alias `grok-voice-latest` przeskoczył z 1.0 na 2.0 2026-08-05.
    assert config.VOICE_REALTIME_MODEL == "grok-voice-think-fast-2.0"
    assert "latest" not in config.VOICE_REALTIME_MODEL


def test_google_catalog_matches_vertex_publisher_list() -> None:
    assert ids("google", "chat") == [
        "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash",
        "gemini-3.1-pro-preview", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite",
        "gemini-2.5-pro", "gemini-2.5-flash",
    ]
    assert ids("google", "image") == [
        "gemini-3.1-flash-image", "gemini-3.1-flash-lite-image",
        "gemini-3-pro-image", "gemini-2.5-flash-image",
    ]
    assert ids("google", "video") == [
        "gemini-omni-1.1-flash", "veo-3.1-generate-preview",
        "veo-3.1-fast-generate-preview", "veo-3.1-lite-generate-preview",
    ]


def test_nano_banana_legacy_is_flagged_before_its_shutdown() -> None:
    legacy = get_model_registry().find("google", "gemini-2.5-flash-image")
    assert legacy is not None
    assert legacy.status == "deprecated"
    assert "2026-10-02" in (legacy.notes or "")


def test_openai_catalog_excludes_approval_gated_models() -> None:
    assert ids("openai", "chat") == ["gpt-5.6-terra", "gpt-5.6-sol", "gpt-5.6-luna"]
    assert ids("openai", "image") == ["gpt-image-2"]
    assert set(ids("openai", "chat")).isdisjoint(GATED_OPENAI_MODELS)


def test_context_windows_follow_the_published_catalogs() -> None:
    assert config.context_window_for("grok-4.6") == 500_000
    assert config.context_window_for("grok-4.5") == 500_000
    assert config.context_window_for("grok-4.3") == 1_000_000
    assert config.context_window_for("grok-4.20-0309-reasoning") == 1_000_000
    assert config.context_window_for("grok-build-0.1") == 256_000
    assert config.context_window_for("gpt-5.6-sol") == 1_050_000
    assert config.context_window_for("gemini-3.7-flash") == 1_048_576
    assert config.context_window_for("model-ktorego-nie-znamy") == 256_000
