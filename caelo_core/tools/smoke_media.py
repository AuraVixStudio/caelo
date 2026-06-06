"""api_smoke — grupa self-checków: smoke_media (P3-13 split). Funkcje `_unit_*`/`_live_*(checks)` wołane przez `api_smoke.main()`."""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from caelo_core.tools._smoke_common import (  # noqa: F401
    PREFIX, REPO_DIR, THIS_DIR, PKG_DIR,
    _read_handshake, _get, _post, _delete, _cors_acao, _capture_no_token_warn,
    _ws_check, _ws_bad_token_rejected,
)


def _unit_collections(checks: list) -> None:
    """M10-B5 (wiedza projektu LOKALNA — xAI nie ma vector stores, 404): upload
    zapisuje plik pod PROJECT_DOCS_DIR + rekord (path/mime), list/content/remove,
    anty-traversal, guard projektu. Bez sieci. Magazyn + katalog docs → temp."""
    import base64
    import tempfile
    from pathlib import Path

    sys.path.insert(0, REPO_DIR)
    import config  # type: ignore  # noqa: E402
    from fastapi import HTTPException  # noqa: E402
    from fastapi.responses import FileResponse  # noqa: E402
    import caelo_core.history_store as HS  # noqa: E402
    from caelo_core.history_store import HistoryStore  # noqa: E402
    from caelo_core.routes import collections as coll_route  # noqa: E402
    from caelo_core.state import Backend  # noqa: E402

    with tempfile.TemporaryDirectory() as d:
        store = HistoryStore(Path(d) / "h.db")
        prev_store = HS._default_store
        prev_docs = config.PROJECT_DOCS_DIR
        HS._default_store = store
        config.PROJECT_DOCS_DIR = Path(d) / "project_docs"
        try:
            b = Backend.__new__(Backend)  # bez __init__ (bez I/O / sieci)

            # bez aktywnego projektu → upload ValueError (wiedza jest per projekt)
            no_proj = False
            try:
                b.collection_upload(b"x", "a.pdf", "application/pdf")
            except ValueError:
                no_proj = True
            checks.append(("collections: upload without project -> ValueError", no_proj))

            proj = store.add_project(name="Proj")
            b.current_project_id = proj.id

            cf = b.collection_upload(b"PDFBYTES", "report.pdf", "application/pdf")
            on_disk = Path(cf.path).is_file() and Path(cf.path).read_bytes() == b"PDFBYTES"
            under = Path(config.PROJECT_DOCS_DIR).resolve() in Path(cf.path).resolve().parents
            checks.append(("collections: upload saves file locally under project_docs",
                           on_disk and under and cf.mime == "application/pdf"
                           and cf.name == "report.pdf" and cf.bytes == 8))

            b.collection_upload(b"MORE", "notes.pdf", "application/pdf")
            checks.append(("collections: list files (2)", len(b.collection_files()) == 2))

            r = coll_route.list_collection(b=b)
            checks.append(("/collections list shape",
                           isinstance(r.get("files"), list) and len(r["files"]) == 2
                           and r.get("has_collection") is True))

            # content endpoint → FileResponse (sandbox pod PROJECT_DOCS_DIR)
            resp = coll_route.get_collection_file_content(cf.id, b=b)
            checks.append(("/collections content -> FileResponse",
                           isinstance(resp, FileResponse)
                           and Path(resp.path).name == Path(cf.path).name))

            # trasa POST /collections/files (data-URI w JSON) — MIME z data-URI
            data_uri = "data:application/pdf;base64," + base64.b64encode(b"PDF").decode()
            rr = coll_route.upload_collection_file(
                coll_route.UploadDocReq(name="t.pdf", data=data_uri), b=b)
            checks.append(("/collections upload (data-URI) ok + mime parsed",
                           rr["file"]["name"] == "t.pdf"
                           and rr["file"]["mime"] == "application/pdf"
                           and len(b.collection_files()) == 3))

            # remove kasuje plik lokalny + rekord
            path_before = cf.path
            ok = b.collection_remove(cf.id)
            checks.append(("collections: remove deletes local file + record",
                           ok and not Path(path_before).exists() and len(b.collection_files()) == 2))

            # anty-traversal: rekord wskazujący POZA PROJECT_DOCS_DIR → 404, nie serwuj
            evil = Path(d).resolve().parent / "grok_b5_evil_marker.bin"
            outside = store.add_collection_file(project_id=proj.id, name="x",
                                                path=str(evil), mime="application/pdf")
            checks.append(("collections: path outside project_docs refused",
                           b.collection_file_path(outside.id) is None))
            denied = False
            try:
                coll_route.get_collection_file_content(outside.id, b=b)
            except HTTPException as e:
                denied = e.status_code == 404
            checks.append(("/collections content outside dir -> 404", denied))

            # trasa upload bez aktywnego projektu → 400
            b.current_project_id = None
            r400 = False
            try:
                coll_route.upload_collection_file(
                    coll_route.UploadDocReq(name="x.pdf", data=data_uri), b=b)
            except HTTPException as e:
                r400 = e.status_code == 400
            checks.append(("/collections upload without project -> 400", r400))

            # walidacja: nie-data-URI odrzucone (Pydantic)
            from pydantic import ValidationError  # noqa: E402
            bad = False
            try:
                coll_route.UploadDocReq(name="x", data="http://evil/x.pdf")
            except ValidationError:
                bad = True
            checks.append(("/collections upload non-data-URI rejected", bad))
        except Exception as exc:  # noqa: BLE001
            checks.append((f"collections: scenario ran ({exc})", False))
        finally:
            HS._default_store = prev_store
            config.PROJECT_DOCS_DIR = prev_docs
            store.close()


def _unit_voice_converse(checks: list) -> None:
    """M12-B3/B5: pipeline rozmowy głosowej — transkrypt -> Responses -> TTS -> audio,
    barge-in (stop przerywa, bez TTS), licznik kosztu. Bez xAI: podmieniamy
    `responses_client.stream_response` i `api.text_to_speech` atrapami; handler z
    atrapą WS (jak _unit_chat_bridge). Plus czyste funkcje kosztu."""
    import threading as _th
    import time as _time
    import types as _types

    sys.path.insert(0, REPO_DIR)
    from fastapi import WebSocketDisconnect  # noqa: E402
    from caelo_core import responses_client as rc  # noqa: E402
    from caelo_core.routes import voice as voice_route  # noqa: E402

    # --- czyste funkcje kosztu (B5) ---
    checks.append(("voice cost: STT stream rate ($0.20/h)", voice_route.stt_cost(3600, streaming=True) == 0.20))
    checks.append(("voice cost: STT batch rate ($0.10/h)", voice_route.stt_cost(3600) == 0.10))
    checks.append(("voice cost: TTS per-char monotone", voice_route.tts_cost(2000) > voice_route.tts_cost(1000) > 0))
    checks.append(("voice cost: zero/negative clamps to 0", voice_route.stt_cost(-5) == 0.0 and voice_route.tts_cost(-5) == 0.0))

    class _FakeWS:
        def __init__(self, backend, frames, on_send):
            self.app = _types.SimpleNamespace(
                state=_types.SimpleNamespace(session_token="t", backend=backend))
            self.headers = {}
            self.query_params = {"token": "t"}
            self._frames = list(frames)
            self._i = 0
            self._on_send = on_send

        async def accept(self):
            pass

        async def close(self, code=1000):
            pass

        async def send_json(self, item):
            await self._on_send(item)

        async def receive_text(self):
            if self._i < len(self._frames):
                f = self._frames[self._i]
                self._i += 1
                return f
            await self._wait_then_disconnect()
            raise WebSocketDisconnect(code=1000)

    def _backend(tts_fn=None):
        api = _types.SimpleNamespace(
            text_to_speech=tts_fn or (lambda text, voice, lang: (b"AUDIO", "audio/mpeg")))
        return _types.SimpleNamespace(
            api=api, read_settings=lambda: {},
            get_api_key=lambda: "k", record_event=lambda **k: None)

    async def _run(frames, backend, wait):
        sent: list = []
        async def on_send(item):
            sent.append(item)
            if item.get("type") in ("done", "error"):
                if hasattr(wait, "on_done"):
                    wait.on_done()
        ws = _FakeWS(backend, frames, on_send)
        ws._wait_then_disconnect = wait
        await asyncio.wait_for(voice_route.voice_converse(ws), timeout=10)
        return sent

    orig_stream = rc.stream_response

    # --- scenariusz 1: pełny pipeline transkrypt -> tekst -> audio -> done + koszt ---
    def stub_ok(messages, **kw):
        # ostatnia wiadomość = transkrypt usera (pipeline dokleja {role:user}).
        kw["on_delta"]("Hi", "Hi")
        kw["on_delta"](" there", "Hi there")
        return {"text": "Hi there", "citations": [{"url": "https://a", "title": "A"}],
                "usage": {"output_tokens": 3}, "tool_calls": 0}

    try:
        rc.stream_response = stub_ok
        done_evt = asyncio.Event()
        async def wait1():
            await done_evt.wait()
        wait1.on_done = done_evt.set
        sent = asyncio.run(_run(
            [json.dumps({"type": "converse", "transcript": "hello", "model": "grok-4.3",
                         "voice_id": "eve", "language": "en"})],
            _backend(), wait1))
        deltas = [m for m in sent if m.get("type") == "delta"]
        audio = [m for m in sent if m.get("type") == "audio"]
        cost = [m for m in sent if m.get("type") == "cost"]
        done = [m for m in sent if m.get("type") == "done"]
        cits = [m for m in sent if m.get("type") == "citations"]
        import base64 as _b64
        checks.append(("voice converse: deltas accumulate to full",
                       "".join(d.get("delta", "") for d in deltas) == "Hi there"))
        checks.append(("voice converse: TTS audio frame (base64 of synthesized bytes)",
                       bool(audio) and audio[0].get("audio_b64") == _b64.b64encode(b"AUDIO").decode("ascii")))
        checks.append(("voice converse: cost frame counts TTS chars",
                       bool(cost) and cost[0].get("tts_chars") == len("Hi there") and cost[0].get("tts_cost") > 0))
        checks.append(("voice converse: done carries full", bool(done) and done[0].get("full") == "Hi there"))
        checks.append(("voice converse: citations forwarded",
                       bool(cits) and cits[0]["citations"][0]["url"] == "https://a"))
    except Exception as exc:  # noqa: BLE001
        checks.append((f"voice converse: pipeline scenario ran ({exc})", False))
    finally:
        rc.stream_response = orig_stream

    # --- scenariusz 2: barge-in (stop) przerywa turę PRZED TTS ---
    def stub_bargein(messages, **kw):
        kw["on_delta"]("A", "A")
        for _ in range(500):  # czekaj aż handler ustawi stop (z ramki 'stop')
            if kw["stop_flag"]():
                break
            _time.sleep(0.01)
        return {"text": "A", "citations": [], "usage": {}, "tool_calls": 0}

    def stub_tts_should_not_run(text, voice, lang):
        raise AssertionError("TTS must not run after barge-in")

    try:
        rc.stream_response = stub_bargein
        done_evt2 = asyncio.Event()
        async def wait2():
            await done_evt2.wait()
        wait2.on_done = done_evt2.set
        sent = asyncio.run(_run(
            [json.dumps({"type": "converse", "transcript": "hello", "model": "grok-4.3"}),
             json.dumps({"type": "stop"})],
            _backend(tts_fn=stub_tts_should_not_run), wait2))
        audio = [m for m in sent if m.get("type") == "audio"]
        cost = [m for m in sent if m.get("type") == "cost"]
        done = [m for m in sent if m.get("type") == "done"]
        checks.append(("voice converse: barge-in stop skips TTS (no audio frame)", not audio))
        checks.append(("voice converse: barge-in still reports zero TTS cost + done",
                       bool(done) and bool(cost) and cost[0].get("tts_chars") == 0))
    except Exception as exc:  # noqa: BLE001
        checks.append((f"voice converse: barge-in scenario ran ({exc})", False))
    finally:
        rc.stream_response = orig_stream


def _unit_media_download_guard(checks: list) -> None:
    """P1-14: pobieranie mediów — tylko https, twardy limit rozmiaru (Content-Length)."""
    import tempfile
    import types
    from pathlib import Path

    sys.path.insert(0, REPO_DIR)
    import caelo_core.state as state_mod  # noqa: E402  (Backend)
    import caelo_core.backend_media as media_mod  # noqa: E402  # P2-13: requests/limit tutaj

    class _Resp:
        def __init__(self, chunks, headers=None):
            self._chunks = chunks
            self.headers = headers or {}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def raise_for_status(self):
            pass

        def iter_content(self, n):
            for c in self._chunks:
                yield c

    calls = {"n": 0}

    def fake_get(url, **kw):
        calls["n"] += 1
        if "BIG" in url:
            return _Resp([b"x"], headers={"Content-Length": str(media_mod.MAX_MEDIA_BYTES + 1)})
        return _Resp([b"abc", b"def"])

    orig = media_mod.requests
    media_mod.requests = types.SimpleNamespace(get=fake_get)
    try:
        b = state_mod.Backend.__new__(state_mod.Backend)  # bez __init__ (bez I/O)
        with tempfile.TemporaryDirectory() as d:
            save_dir = Path(d)

            p = b._download_media("https://x/v.mp4", save_dir, "video", ".mp4")
            checks.append(("media guard: https streamed to disk",
                           Path(p).exists() and Path(p).read_bytes() == b"abcdef" and calls["n"] == 1))

            calls["n"] = 0
            refused = False
            try:
                b._download_media("http://internal/x", save_dir, "video", ".mp4")
            except ValueError:
                refused = True
            checks.append(("media guard: non-https refused before fetch",
                           refused and calls["n"] == 0))

            capped = False
            try:
                b._download_media("https://x/BIG.mp4", save_dir, "video", ".mp4")
            except ValueError:
                capped = True
            checks.append(("media guard: oversize (Content-Length) refused", capped))
    finally:
        media_mod.requests = orig


def _live_media_voice_routes(base: str, token: str, checks: list) -> None:
    """P3-1: żywe trasy media/voice — bramka tokenu (401/403) i kształt wejścia
    (Pydantic → 422). Walidacja zachodzi PRZED ciałem trasy, więc te przypadki
    NIE dotykają sieci xAI (bezpieczne i szybkie w CI)."""
    # --- bramka tokenu (POST jak GET-y wyżej) ---
    s, _ = _post(base, "/images/generate", {"prompt": "x"})
    checks.append(("/images/generate (no token) == 401", s == 401))
    s, _ = _post(base, "/images/generate", {"prompt": "x"}, "wrong")
    checks.append(("/images/generate (bad token) == 403", s == 403))
    s, _ = _post(base, "/voice/tts", {"text": "hi"})
    checks.append(("/voice/tts (no token) == 401", s == 401))
    s, _ = _post(base, "/voice/tts", {"text": "hi"}, "wrong")
    checks.append(("/voice/tts (bad token) == 403", s == 403))

    # --- kształt wejścia (422), bez wywołania xAI ---
    s, _ = _post(base, "/images/generate", {"prompt": ""}, token)
    checks.append(("/images/generate (empty prompt) == 422", s == 422))
    s, _ = _post(base, "/images/generate", {"prompt": "x", "n": 999}, token)
    checks.append(("/images/generate (n out of range) == 422", s == 422))
    s, _ = _post(base, "/images/edit", {"prompt": "x", "images": ["http://evil/x.png"]}, token)
    checks.append(("/images/edit (non-data-URI image) == 422", s == 422))
    s, _ = _post(base, "/video/extensions",
                 {"prompt": "x", "video": "https://x/v.mp4", "duration": 99}, token)
    checks.append(("/video/extensions (duration out of range) == 422", s == 422))
    s, _ = _post(base, "/voice/tts", {"text": ""}, token)
    checks.append(("/voice/tts (empty text) == 422", s == 422))


def _live_genjobs_routes(base: str, token: str, checks: list) -> None:
    """M11: trasy /genjobs — bramka tokenu (401/403), kształt wejścia (Pydantic → 422,
    PRZED ciałem trasy, więc bez sieci xAI), list shape i 404. NIE wysyłamy poprawnego
    zadania (uruchomiłoby workera dążącego do xAI + zapis do realnej bazy)."""
    # --- bramka tokenu ---
    s, _ = _post(base, "/genjobs/image", {"prompt": "x"})
    checks.append(("/genjobs/image (no token) == 401", s == 401))
    s, _ = _post(base, "/genjobs/image", {"prompt": "x"}, "wrong")
    checks.append(("/genjobs/image (bad token) == 403", s == 403))
    s, _ = _get(base, "/genjobs")
    checks.append(("/genjobs (no token) == 401", s == 401))

    # --- kształt wejścia (422), bez wywołania xAI ---
    s, _ = _post(base, "/genjobs/image", {"prompt": ""}, token)
    checks.append(("/genjobs/image (empty prompt) == 422", s == 422))
    s, _ = _post(base, "/genjobs/image", {"op": "edit", "prompt": "x"}, token)
    checks.append(("/genjobs/image (edit without images) == 422", s == 422))
    s, _ = _post(base, "/genjobs/image",
                 {"op": "text2img", "prompt": "x", "images": ["data:image/png;base64,AA"]}, token)
    checks.append(("/genjobs/image (text2img with images) == 422", s == 422))
    s, _ = _post(base, "/genjobs/image",
                 {"op": "edit", "prompt": "x", "images": ["http://evil/x.png"]}, token)
    checks.append(("/genjobs/image (non-data-URI ref) == 422", s == 422))
    s, _ = _post(base, "/genjobs/video", {"op": "img2video", "prompt": "x"}, token)
    checks.append(("/genjobs/video (img2video without image) == 422", s == 422))
    s, _ = _post(base, "/genjobs/video", {"prompt": "x", "duration": 999}, token)
    checks.append(("/genjobs/video (duration out of range) == 422", s == 422))
    s, _ = _post(base, "/genjobs/video", {"op": "edit", "prompt": "x"}, token)
    checks.append(("/genjobs/video (edit without source video) == 422", s == 422))
    s, _ = _post(base, "/genjobs/video",
                 {"op": "extend", "prompt": "x", "video": "https://x/v.mp4", "duration": 99}, token)
    checks.append(("/genjobs/video (extend duration out of range) == 422", s == 422))

    # --- list shape + 404 (z tokenem) ---
    s, body = _get(base, "/genjobs", token)
    checks.append(("/genjobs == 200 + jobs list + total_cost",
                   s == 200 and body is not None and isinstance(body.get("jobs"), list)
                   and "total_cost" in body))
    s, _ = _get(base, "/genjobs/does-not-exist", token)
    checks.append(("/genjobs/{id} (unknown) == 404", s == 404))

    # --- czyszczenie listy (M11 follow-up) — token gate + kształt + 404 ---
    s, _ = _delete(base, "/genjobs")
    checks.append(("DELETE /genjobs (no token) == 401", s == 401))
    s, body = _delete(base, "/genjobs", token)
    checks.append(("DELETE /genjobs == 200 + cleared count",
                   s == 200 and body is not None and "cleared" in body))
    s, _ = _delete(base, "/genjobs/does-not-exist", token)
    checks.append(("DELETE /genjobs/{id} (unknown) == 404", s == 404))
