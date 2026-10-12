"""Publiczne linki artefaktów przez xAI Files API (docs.x.ai „Public URLs").

Pilnuje zgody (bez `confirm` nic nie wychodzi z maszyny), jednokrotnego uploadu
(`xai_file_id` w meta), ponownego uploadu tylko gdy plik zniknął z Files API (404),
sandboxa ścieżek i limitów typu/rozmiaru — wszystko na atrapie HTTP.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from caelo_core.history_store import HistoryStore
from caelo_core.providers.xai import files as xai_files
from caelo_core.routes import public_urls
from caelo_core.routes.public_urls import PublicUrlReq, create_public_url, revoke_public_url


class _Resp:
    def __init__(self, status: int, body: dict) -> None:
        self.status_code = status
        self._body = body
        self.text = str(body)
        self.encoding = None

    def json(self) -> dict:
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    store = HistoryStore(tmp_path / "h.db")
    media = tmp_path / "media"
    media.mkdir()
    image = media / "out.png"
    image.write_bytes(b"\x89PNG data")
    art = store.add_artifact(type="image", mode="generate", mime="image/png", path=str(image))
    monkeypatch.setattr(public_urls, "_media_bases", lambda b: [media])
    calls: list[tuple[str, object]] = []
    state = {"gone": False, "uploads": 0}

    def fake_post(url, headers=None, data=None, files=None, json=None, timeout=None):  # noqa: A002
        calls.append((url, json))
        if url.endswith("/files"):
            state["uploads"] += 1
            state["gone"] = False
            return _Resp(200, {"id": f"file_{state['uploads']}"})
        if url.endswith("/public-url"):
            if state["gone"]:
                return _Resp(404, {"error": "not found"})
            body = {"public_url": "https://files-cdn.x.ai/tok/out.png"}
            if json and json.get("expires_after"):
                body["expires_at"] = 1_900_000_000
            return _Resp(200, body)
        if url.endswith("/revoke"):
            return _Resp(200, {"id": "file_1", "revoked": True})
        raise AssertionError(url)

    monkeypatch.setattr(xai_files.requests, "post", fake_post)
    backend = SimpleNamespace(history_store=store, get_api_key=lambda: "key")
    return SimpleNamespace(store=store, art=art, b=backend, calls=calls, state=state, media=media)


def test_requires_explicit_confirmation(env) -> None:
    with pytest.raises(HTTPException) as exc:
        create_public_url(env.art.id, PublicUrlReq(), env.b)
    assert exc.value.status_code == 400
    assert env.calls == []


def test_uploads_once_and_records_the_link(env) -> None:
    first = create_public_url(env.art.id, PublicUrlReq(confirm=True, expires_after=86400), env.b)
    assert first == {"public_url": "https://files-cdn.x.ai/tok/out.png",
                     "expires_at": 1_900_000_000, "file_id": "file_1"}
    create_public_url(env.art.id, PublicUrlReq(confirm=True), env.b)
    assert env.state["uploads"] == 1  # drugi raz bez ponownego uploadu
    meta = env.store.get_artifact(env.art.id).meta
    assert meta["xai_file_id"] == "file_1" and meta["public_url"].startswith("https://")
    assert "public_url_expires_at" not in meta  # link bez wygaśnięcia nadpisał poprzedni stan


def test_reuploads_when_file_vanished_from_files_api(env) -> None:
    create_public_url(env.art.id, PublicUrlReq(confirm=True), env.b)
    env.state["gone"] = True
    result = create_public_url(env.art.id, PublicUrlReq(confirm=True), env.b)
    assert env.state["uploads"] == 2 and result["file_id"] == "file_2"


def test_revoke_clears_the_link_but_keeps_file_id(env) -> None:
    create_public_url(env.art.id, PublicUrlReq(confirm=True), env.b)
    result = revoke_public_url(env.art.id, env.b)
    assert result["revoked"] is True and result["public_url"] is None
    assert env.store.get_artifact(env.art.id).meta["xai_file_id"] == "file_1"


def test_rejects_unsupported_type_and_paths_outside_media(env, tmp_path) -> None:
    doc = env.store.add_artifact(type="doc", mode="x", mime="text/plain",
                                 path=str(env.media / "a.txt"))
    with pytest.raises(HTTPException) as exc:
        create_public_url(doc.id, PublicUrlReq(confirm=True), env.b)
    assert exc.value.status_code == 415
    outside = tmp_path / "secret.png"
    outside.write_bytes(b"x")
    stray = env.store.add_artifact(type="image", mode="x", mime="image/png", path=str(outside))
    with pytest.raises(HTTPException) as exc:
        create_public_url(stray.id, PublicUrlReq(confirm=True), env.b)
    assert exc.value.status_code == 403
    assert env.calls == []


def test_expiry_bounds_follow_the_docs() -> None:
    PublicUrlReq(confirm=True, expires_after=3600)
    PublicUrlReq(confirm=True, expires_after=2_592_000)
    for bad in (3599, 2_592_001):
        with pytest.raises(ValueError):
            PublicUrlReq(confirm=True, expires_after=bad)
