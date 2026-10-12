"""Zmiany xAI Imagine z 2026-09/10 (docs.x.ai: Video overview, Video generation,
Reference-to-video, migracja „imagine-image-quality-nov-2").

Pilnuje, że NOWE pola trafiają na drut tylko do modeli, które je znają (xAI odrzuca
całe żądanie 4xx przy nieznanym parametrze), oraz że trasa/rejestr odrzucają
kombinacje, których API nie przyjmuje — zanim zapłacimy za wywołanie.
"""

from __future__ import annotations

import pytest

import api_manager  # type: ignore

from caelo_core.models.capabilities import CapabilityError
from caelo_core.models.pricing import estimate_cost
from caelo_core.models.registry import get_model_registry
from caelo_core.routes.genjobs import ImageJobReq, VideoJobReq

IMG = "data:image/png;base64,AA"


class _Resp:
    status_code = 200

    def __init__(self, body: dict) -> None:
        self._body = body

    def json(self) -> dict:
        return self._body

    def raise_for_status(self) -> None:
        return None


@pytest.fixture()
def sent(monkeypatch):
    calls: list[tuple[str, dict]] = []

    def fake_post(url, headers=None, json=None, timeout=None):  # noqa: A002
        calls.append((url, json))
        if url.endswith("/videos/generations"):
            return _Resp({"request_id": "req-1"})
        return _Resp({"data": [{"url": "https://x/out.png"}]})

    monkeypatch.setattr(api_manager.requests, "post", fake_post)
    return calls


def _api():
    return api_manager.APIManager(lambda: "key")


def test_v15_payload_carries_pinned_frames_voices_and_silent_audio(sent) -> None:
    _api().create_video_job(
        "<IMAGE_0> greets <AUDIO_0>", 8, "720p", "16:9", model="grok-imagine-video-1.5",
        image_data_uri=IMG, reference_images=[IMG] * 15, last_frame=IMG,
        keyframes=[{"image": IMG, "timestamp_s": 4}] * 5,
        reference_audios=["eve", "leo", "ara", "rex"], generate_audio=False,
    )
    _, body = sent[-1]
    assert len(body["reference_images"]) == 14
    assert body["last_frame"] == {"url": IMG}
    assert body["keyframes"][0] == {"image": {"url": IMG}, "timestamp_s": 4.0}
    assert len(body["keyframes"]) == 4
    assert body["reference_audios"] == [{"voice_id": v} for v in ("eve", "leo", "ara")]
    assert body["generate_audio"] is False


def test_unsupported_fields_never_reach_lite_or_base(sent) -> None:
    _api().create_video_job("x", 6, "480p", "Original", model="grok-imagine-video-1.5-lite",
                            reference_images=[IMG], last_frame=IMG,
                            keyframes=[{"image": IMG, "timestamp_s": 1}],
                            reference_audios=["eve"])
    _, lite = sent[-1]
    assert not {"reference_images", "last_frame", "keyframes", "reference_audios",
                "generate_audio", "aspect_ratio"} & set(lite)
    _api().create_video_job("x", 6, "480p", "16:9", model="grok-imagine-video",
                            reference_images=[IMG] * 9, last_frame=IMG, reference_audios=["eve"])
    _, base = sent[-1]
    assert len(base["reference_images"]) == 7
    assert "last_frame" not in base and "reference_audios" not in base


def test_retired_image_slug_goes_out_as_2_0_low(sent) -> None:
    _api().generate_image("a cat", 1, "auto", "1k", model="grok-imagine-image-quality")
    _, body = sent[-1]
    assert body["model"] == "grok-imagine-image-2.0" and body["quality"] == "low"
    _api().edit_image_b64("sketch", [IMG], model="grok-imagine-image-quality", quality="medium")
    _, body = sent[-1]
    assert body["model"] == "grok-imagine-image-2.0" and body["quality"] == "medium"


def test_image_route_rewrites_retired_slug() -> None:
    req = ImageJobReq(prompt="a cat", model="grok-imagine-image-quality")
    assert (req.model, req.quality) == ("grok-imagine-image-2.0", "low")
    # 2.0 przyjmuje do 5 źródeł edycji, 1.0 — 3.
    ImageJobReq(op="edit", prompt="x", model="grok-imagine-image-2.0", images=[IMG] * 5)
    with pytest.raises(ValueError):
        ImageJobReq(op="edit", prompt="x", model="grok-imagine-image", images=[IMG] * 4)


def _validate(op: str, model: str, **params) -> None:
    get_model_registry().validate("xai", "video", op, params, model)


def test_registry_enforces_reference_limits_per_model() -> None:
    _validate("reference_to_video", "grok-imagine-video-1.5", reference_images=[IMG] * 14,
              resolution="720p", duration=15, image=IMG)
    with pytest.raises(CapabilityError):  # bazowy: max 7
        _validate("reference_to_video", "grok-imagine-video", reference_images=[IMG] * 8)
    with pytest.raises(CapabilityError):  # bazowy: max 10 s z referencjami
        _validate("reference_to_video", "grok-imagine-video", reference_images=[IMG], duration=12)
    with pytest.raises(CapabilityError):  # bazowy nie łączy kadru startowego z referencjami
        _validate("reference_to_video", "grok-imagine-video", reference_images=[IMG], image=IMG)
    with pytest.raises(CapabilityError):  # referencje: ≤720p
        _validate("reference_to_video", "grok-imagine-video-1.5", reference_images=[IMG],
                  resolution="1080p")
    with pytest.raises(CapabilityError):  # lite: brak referencji
        _validate("reference_to_video", "grok-imagine-video-1.5-lite", reference_images=[IMG])


def test_registry_gates_voices_and_keyframes() -> None:
    _validate("text2video", "grok-imagine-video-1.5", reference_audios=["eve"],
              keyframe_images=[IMG] * 4)
    with pytest.raises(CapabilityError):
        _validate("text2video", "grok-imagine-video", reference_audios=["eve"])
    with pytest.raises(CapabilityError):
        _validate("text2video", "grok-imagine-video-1.5", reference_audios=["nobody"])
    with pytest.raises(CapabilityError):
        _validate("text2video", "grok-imagine-video-1.5-lite", keyframe_images=[IMG])
    _validate("extend", "grok-imagine-video", duration=5)  # extend przechodzi walidację


def test_video_route_keyframe_rules() -> None:
    VideoJobReq(prompt="x", duration=6, keyframe_images=[IMG, IMG],
                keyframe_times=[1 / 3, 3.0])
    for times in ([0.5], [0.0], [6.0], [2.0, 2.0]):
        with pytest.raises(ValueError):
            VideoJobReq(prompt="x", duration=6, keyframe_images=[IMG] * len(times),
                        keyframe_times=times)
    with pytest.raises(ValueError):
        VideoJobReq(prompt="x", keyframe_images=[IMG], keyframe_times=[])
    with pytest.raises(ValueError):
        VideoJobReq(op="extend", prompt="x", video="https://x/v.mp4", reference_audios=["eve"])
    assert VideoJobReq(op="reference_to_video", prompt="x",
                       reference_audios=["EVE"]).reference_audios == ["eve"]


def test_pricing_lite_and_retired_slug() -> None:
    # Stawki per rozdzielczość ze strony modelu: 480p $0.02, 720p $0.03, 1080p $0.14 /s.
    lite = {"model": "grok-imagine-video-1.5-lite", "duration": 10}
    assert estimate_cost("video", "text2video", {**lite, "resolution": "480p"}) == 0.2
    assert estimate_cost("video", "text2video", {**lite, "resolution": "720p"}) == 0.3
    assert estimate_cost("video", "text2video", {**lite, "resolution": "1080p"}) == 1.4
    assert estimate_cost("image", "text2img", {"model": "grok-imagine-image-quality"}) == 0.04


def test_image_to_video_aspect_is_automatic(sent) -> None:
    # docs.x.ai: „Automatic: matches the input image" — UI wysyła wtedy 'Original'.
    for model in ("grok-imagine-video-1.5", "grok-imagine-video-1.5-lite", "grok-imagine-video"):
        assert get_model_registry().find("xai", model).capabilities.image_to_video_auto_aspect
        _validate("img2video", model, aspect_ratio="Original", image=IMG)
    _api().create_video_job("x", 6, "720p", "Original", model="grok-imagine-video-1.5",
                            image_data_uri=IMG)
    assert "aspect_ratio" not in sent[-1][1]
