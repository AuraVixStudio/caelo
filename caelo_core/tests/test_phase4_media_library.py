import asyncio
import base64
from pathlib import Path
from types import SimpleNamespace

import config

from caelo_core.history_store import HistoryStore
from starlette.requests import Request

from caelo_core.routes.history import (
    ReferenceImageUpload,
    build_input_payload,
    upload_reference_file,
    upload_reference_image,
    get_artifact_thumbnail,
)
from caelo_core.media_paths import media_bases


def test_artifact_favorites_tags_and_lineage(tmp_path):
    store = HistoryStore(tmp_path / "history.db")
    source = store.add_artifact(type="image", mode="image")
    result = store.add_artifact(type="image", mode="image")

    assert store.set_artifact_favorite(result.id, True)
    assert store.set_artifact_tags(result.id, ["hero", " style ", "hero"]) == ["hero", "style"]
    store.media.generations.add_reference(result.id, source.id, "character")

    loaded = store.get_artifact(result.id)
    assert loaded is not None
    assert loaded.favorite is True
    assert loaded.tags == ["hero", "style"]
    assert store.artifact_lineage(result.id)["parents"] == [
        {"artifact_id": source.id, "role": "character"}
    ]


def test_media_diagnostics_reports_latest_migration(tmp_path):
    store = HistoryStore(tmp_path / "history.db")
    diagnostics = store.media_diagnostics()
    assert diagnostics["migrations"][-1]["version"] == 4
    assert diagnostics["artifacts"] == 0


def test_reference_library_import_persists_reusable_image(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    store = HistoryStore(tmp_path / "history.db")
    backend = SimpleNamespace(history_store=store)
    raw = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
    body = ReferenceImageUpload(
        name=r"C:\Pictures\hero.png",
        data="data:image/png;base64," + base64.b64encode(raw).decode("ascii"),
    )

    response = upload_reference_image(body, b=backend)
    artifact = store.get_artifact(response["artifact"]["id"])

    assert artifact is not None
    assert artifact.mode == "reference"
    assert artifact.meta["name"] == "hero.png"
    assert Path(artifact.path).read_bytes() == raw
    assert Path(artifact.path).parent == tmp_path / "reference_library"
    assert artifact.thumb_path and Path(artifact.thumb_path).is_file()
    assert [item.id for item in store.list_artifacts(mode="reference")] == [artifact.id]
    input_payload = build_input_payload(artifact, media_bases())
    assert input_payload["data_uri"].startswith("data:image/png;base64,")


def test_reference_library_binary_import_avoids_base64_json(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    store = HistoryStore(tmp_path / "history.db")
    backend = SimpleNamespace(history_store=store)
    raw = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": raw, "more_body": False}

    request = Request({
        "type": "http",
        "method": "POST",
        "path": "/reference-library/file",
        "headers": [(b"content-type", b"image/png"), (b"content-length", str(len(raw)).encode())],
    }, receive)
    response = asyncio.run(upload_reference_file(request, name="binary.png", b=backend))
    artifact = store.get_artifact(response["artifact"]["id"])

    assert artifact is not None
    assert artifact.meta["name"] == "binary.png"
    assert Path(artifact.path).read_bytes() == raw


def test_generated_image_thumbnail_is_cached_outside_output_folder(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    monkeypatch.setattr(config, "DATA_DIR", data_dir)
    store = HistoryStore(data_dir / "history.db")
    raw = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
    source = output_dir / "generated.png"
    source.write_bytes(raw)
    artifact = store.add_artifact(
        type="image", mode="image", mime="image/png", path=str(source), thumb_path=""
    )
    backend = SimpleNamespace(
        history_store=store,
        history=SimpleNamespace(get_save_path=lambda: str(output_dir)),
    )

    response = get_artifact_thumbnail(artifact.id, b=backend)
    thumbnail = Path(response.path)

    assert thumbnail.is_file()
    assert thumbnail.parent == data_dir / "thumbnail_cache" / "Thumbnails"
    assert thumbnail.name == f"{artifact.id}.webp"
    assert list(output_dir.iterdir()) == [source]
