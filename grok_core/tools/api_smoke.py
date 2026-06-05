"""Smoke-test tras Fazy 1 — odwzorowuje, jak frontend rozmawia z backendem.

Spawnuje `python -m grok_core`, czyta handshake i weryfikuje:
  REST:  /health, /whoami(token), /auth/status, /models, /settings  -> 200
         /models bez tokenu -> 401, zły token -> 403
         media/voice (P3-1): /images/*, /video/*, /voice/* — auth (401/403)
           oraz kształt wejścia (Pydantic -> 422) BEZ realnego wywołania xAI
  WS:    /chat/stream?token=<ok>   -> połączenie zaakceptowane
         /chat/stream?token=<zły>  -> odrzucone

Unity (bez sieci xAI): autoryzacja WS, timeouty APIManager, most czatu, walidacja
wejścia, dekodowanie SSE jako UTF-8 (P3-1), oraz strażnik własności plików JSON
(P3-1: zapis ustawień nie rusza grok_config.json — domena HistoryManagera).

Nie wykonuje realnych wywołań xAI (obraz/wideo/czat) — to weryfikuje użytkownik
z ważnymi poświadczeniami. Kod wyjścia 0 = wszystkie asercje OK.
"""

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

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PKG_DIR = os.path.dirname(THIS_DIR)
REPO_DIR = os.path.dirname(PKG_DIR)
PREFIX = "__GROK_CORE_READY__"


def _read_handshake(proc: subprocess.Popen, timeout: float = 25.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                err = proc.stderr.read() if proc.stderr else ""
                raise RuntimeError(f"sidecar exited before handshake:\n{err}")
            continue
        line = line.strip()
        if line.startswith(PREFIX):
            return json.loads(line[len(PREFIX):].strip())
    raise RuntimeError("timed out waiting for handshake")


def _get(base: str, path: str, token: str | None = None):
    req = urllib.request.Request(base + path)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, None


def _post(base: str, path: str, body: dict, token: str | None = None):
    """POST JSON; zwraca (status, body-lub-None). Błędy HTTP (401/403/422/5xx)
    zwracane jako kod (bez wyjątku) — używane do testów auth/walidacji tras."""
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(base + path, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, None


def _delete(base: str, path: str, token: str | None = None):
    """DELETE; zwraca (status, body-lub-None). Błędy HTTP zwracane jako kod."""
    req = urllib.request.Request(base + path, method="DELETE")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, None


def _cors_acao(base: str, path: str, origin: str) -> str | None:
    """Zwraca Access-Control-Allow-Origin dla żądania z danym Origin (P1-9)."""
    req = urllib.request.Request(base + path)
    req.add_header("Origin", origin)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.headers.get("access-control-allow-origin")
    except urllib.error.HTTPError as exc:
        return exc.headers.get("access-control-allow-origin")


async def _ws_check(port: int, token: str) -> tuple[bool, bool]:
    """Zwraca (ok_token_zaakceptowany, zły_token_odrzucony).

    P3-1: brak `websockets` NIE jest już cichym „pass" (fałszywie zielone testy) —
    wywołujący sprawdza dostępność biblioteki osobno i pomija żywe testy WS jawnie,
    więc tu zwracamy realną porażkę, gdyby mimo to import się nie powiódł."""
    try:
        import websockets  # type: ignore
    except Exception:
        return (False, False)

    ok_accepted = False
    bad_rejected = False
    try:
        async with asyncio.timeout(8):
            async with websockets.connect(f"ws://127.0.0.1:{port}/chat/stream?token={token}"):
                ok_accepted = True
    except Exception:
        ok_accepted = False
    try:
        async with asyncio.timeout(8):
            async with websockets.connect(f"ws://127.0.0.1:{port}/chat/stream?token=wrong-token") as ws:
                # serwer może zaakceptować i zaraz zamknąć — sprawdź, czy żyje
                await ws.recv()
        bad_rejected = False
    except Exception:
        bad_rejected = True
    return (ok_accepted, bad_rejected)


async def _ws_bad_token_rejected(port: int, path: str) -> bool:
    """True, jeśli WS pod `path` odrzuca zły token (P0-8: ważne dla /agent, /terminal)."""
    try:
        import websockets  # type: ignore
    except Exception:
        return False  # P3-1: brak biblioteki to nie „pass" (patrz _ws_check)
    try:
        async with asyncio.timeout(8):
            async with websockets.connect(f"ws://127.0.0.1:{port}{path}?token=wrong-token") as ws:
                await ws.recv()
        return False
    except Exception:
        return True


def _unit_ws_auth(checks: list) -> None:
    """Deterministyczny test logiki autoryzacji WS (P0-8) — bez sieci, na atrapie."""
    import types

    sys.path.insert(0, REPO_DIR)
    from grok_core.state import _ws_origin_ok, ws_authorized  # noqa: E402

    def fake(state_token: str, qtoken=None, origin=None):
        return types.SimpleNamespace(
            app=types.SimpleNamespace(state=types.SimpleNamespace(session_token=state_token)),
            query_params=({"token": qtoken} if qtoken is not None else {}),
            headers=({"origin": origin} if origin is not None else {}),
        )

    checks.append(("ws_auth: valid token accepted", ws_authorized(fake("secret", "secret")) is True))
    checks.append(("ws_auth: bad token rejected", ws_authorized(fake("secret", "nope")) is False))
    checks.append(("ws_auth: missing token rejected", ws_authorized(fake("secret")) is False))

    os.environ.pop("GROK_CORE_ALLOW_NO_TOKEN", None)
    checks.append(("ws_auth: no-token config -> DENIED (fail-closed)", ws_authorized(fake("", "x")) is False))
    os.environ["GROK_CORE_ALLOW_NO_TOKEN"] = "1"
    checks.append(("ws_auth: explicit opt-in allows no-token", ws_authorized(fake("", "x")) is True))
    os.environ.pop("GROK_CORE_ALLOW_NO_TOKEN", None)

    checks.append(("ws_auth: foreign origin rejected", ws_authorized(fake("secret", "secret", "https://evil.example")) is False))
    checks.append(("ws_auth: loopback origin ok", ws_authorized(fake("secret", "secret", "http://localhost:5173")) is True))
    checks.append(("origin: file:// ok", _ws_origin_ok("file://") is True))
    checks.append(("origin: null/none ok", _ws_origin_ok("null") is True and _ws_origin_ok(None) is True))


def _unit_responses_client(checks: list) -> None:
    """M10-B1/B2/B3: klient Responses API — bez sieci podmieniamy
    `responses_client.requests.post` na atrapę zwracającą udokumentowany strumień
    SSE (zdarzenia typowane). Sprawdzamy: dekodowanie UTF-8 (mojibake-guard), balans
    historii (role w `input`), aktywność narzędzi (live search), dedup cytowań,
    usage, licznik wywołań, off→bez narzędzi, oraz że klucz idzie z providera."""
    import types

    sys.path.insert(0, REPO_DIR)
    from grok_core import responses_client as rc  # noqa: E402

    text = "Zażółć gęślą jaźń — €µ✓ live"

    def _frame(d) -> bytes:
        # ensure_ascii=False → surowe wielobajtowe UTF-8 na drucie (test dekodowania).
        return b"data: " + json.dumps(d, ensure_ascii=False).encode("utf-8")

    frames = [
        _frame({"type": "response.created", "response": {"id": "r1"}}),
        _frame({"type": "response.web_search_call.in_progress", "item_id": "ws1"}),
        _frame({"type": "response.web_search_call.searching", "item_id": "ws1",
                "action": {"query": "grok news"}}),
        _frame({"type": "response.web_search_call.completed", "item_id": "ws1"}),
        _frame({"type": "response.output_text.delta", "delta": text[:9]}),
        _frame({"type": "response.output_text.delta", "delta": text[9:]}),
        _frame({"type": "response.output_text.annotation.added",
                "annotation": {"type": "url_citation", "url": "https://x.com/a", "title": "A"}}),
        b"",
        _frame({"type": "response.completed", "response": {
            "usage": {"input_tokens": 12, "output_tokens": 34},
            "output": [{"type": "message", "content": [
                {"type": "output_text", "text": text, "annotations": [
                    {"type": "url_citation", "url": "https://x.com/a", "title": "A"},
                    {"type": "url_citation", "url": "https://ex.com/n", "title": "News"}]}]}]}}),
        b"data: [DONE]",
    ]
    captured: dict = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def raise_for_status(self):
            pass

        def iter_lines(self, decode_unicode=False):
            captured["decode_unicode"] = decode_unicode
            for f in frames:
                yield f

    def _post(url, **kw):
        captured["url"] = url
        captured["json"] = kw.get("json")
        captured["stream"] = kw.get("stream")
        captured["timeout"] = kw.get("timeout")
        captured["auth"] = (kw.get("headers") or {}).get("Authorization")
        return _Resp()

    original = rc.requests
    rc.requests = types.SimpleNamespace(post=_post, get=getattr(original, "get", None))
    try:
        deltas: list = []
        tools_seen: list = []
        res = rc.stream_response(
            [{"role": "user", "content": "what is new"},
             {"role": "assistant", "content": "prior"},
             {"role": "user", "content": "now"}],
            model="grok-4.3", api_key_provider=lambda: "KEY",
            tools=rc.build_search_tools("auto"),
            on_delta=lambda d, f: deltas.append((d, f)),
            on_tool=lambda ev: tools_seen.append(ev),
        )
    finally:
        rc.requests = original

    checks.append(("responses: SSE decoded UTF-8 (no mojibake)", res["text"] == text))
    checks.append(("responses: deltas accumulate to full", bool(deltas) and deltas[-1][1] == text))
    checks.append(("responses: iter_lines(decode_unicode=False) (bytes path)",
                   captured.get("decode_unicode") is False))
    checks.append(("responses: POST /responses with stream + timeout",
                   str(captured.get("url", "")).endswith("/responses")
                   and captured.get("stream") is True and captured.get("timeout") is not None))
    checks.append(("responses: bearer from api_key_provider", captured.get("auth") == "Bearer KEY"))
    checks.append(("responses: history balance (input roles preserved)",
                   [i["role"] for i in captured["json"]["input"]] == ["user", "assistant", "user"]))
    checks.append(("responses: assistant uses output_text part",
                   captured["json"]["input"][1]["content"][0]["type"] == "output_text"))
    checks.append(("responses: tools attached for auto",
                   captured["json"].get("tools") == [{"type": "web_search"}, {"type": "x_search"}]))
    checks.append(("responses: tool activity events emitted (live search)",
                   any(ev["tool"] == "web_search" for ev in tools_seen)
                   and any(ev.get("query") == "grok news" for ev in tools_seen)))
    checks.append(("responses: tool_calls counted once per item", res["tool_calls"] == 1))
    cit_urls = sorted(c["url"] for c in res["citations"])
    checks.append(("responses: citations parsed + deduped",
                   cit_urls == ["https://ex.com/n", "https://x.com/a"]))
    checks.append(("responses: usage captured", res["usage"].get("output_tokens") == 34))
    checks.append(("responses: mode=off attaches no tools", rc.build_search_tools("off") is None))

    # M10-B4: document content part → Responses `input_file` (Q&A nad dokumentem inline).
    doc_in = rc.to_input([{"role": "user", "content": [
        {"type": "text", "text": "summarize"},
        {"type": "document", "document": {
            "data": "data:application/pdf;base64,JVBERi0xLjQK", "mime": "application/pdf",
            "name": "report.pdf"}}]}])
    doc_parts = doc_in[0]["content"] if doc_in else []
    checks.append(("responses: document part -> input_file (B4)",
                   any(p.get("type") == "input_file" and p.get("filename") == "report.pdf"
                       and str(p.get("file_data", "")).startswith("data:application/pdf")
                       for p in doc_parts)))

    # B4: dokument przekraczający cap jest POMINIĘTY (anti-OOM), bez wywracania tury.
    import grok_core.validation as Vmod  # noqa: E402
    cap = Vmod.MAX_DOCUMENT_URI
    Vmod.MAX_DOCUMENT_URI = 64
    try:
        over = rc.to_input([{"role": "user", "content": [
            {"type": "document", "document": {
                "data": "data:application/pdf;base64," + "A" * 200, "name": "big.pdf"}}]}])
    finally:
        Vmod.MAX_DOCUMENT_URI = cap
    checks.append(("responses: oversize document skipped (cap, no crash)", over == []))


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
    import grok_core.history_store as HS  # noqa: E402
    from grok_core.history_store import HistoryStore  # noqa: E402
    from grok_core.routes import collections as coll_route  # noqa: E402
    from grok_core.state import Backend  # noqa: E402

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


def _unit_chat_bridge(checks: list) -> None:
    """M10/P1-3: most czatu na **Responses API** — delty przyrostowe, done z full,
    tool_call + citations (live search), single-flight, fallback na legacy, gating
    wizji. Bez xAI: podmieniamy `responses_client.stream_response` (i legacy
    `api.chat_completion_stream` dla fallbacku) atrapami; handler z atrapą WS."""
    import threading as _th
    import types as _types

    sys.path.insert(0, REPO_DIR)
    from fastapi import WebSocketDisconnect  # noqa: E402
    from grok_core import responses_client as rc  # noqa: E402
    from grok_core.routes import chat as chat_route  # noqa: E402

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

    def _backend(legacy_fn=None):
        api = _types.SimpleNamespace(
            chat_completion_stream=legacy_fn or (lambda *a, **k: ""),
            chat_completion=lambda *a, **k: "")
        return _types.SimpleNamespace(
            api=api, read_settings=lambda: {},
            get_api_key=lambda: "k", record_event=lambda **k: None)

    async def _run(frames, backend, *, terminal=("done", "error")):
        sent: list = []
        done_evt = asyncio.Event()

        async def on_send(item):
            sent.append(item)
            if item.get("type") in terminal:
                done_evt.set()

        ws = _FakeWS(backend, frames, on_send)
        ws._wait_then_disconnect = done_evt.wait
        await asyncio.wait_for(chat_route.chat_stream(ws), timeout=10)
        return sent

    orig_stream = rc.stream_response

    # --- scenariusz 1: protokół delta/done + citations/usage (przez Responses) ---
    def stub_ok(messages, **kw):
        kw["on_delta"]("Hel", "Hel")
        kw["on_delta"]("lo", "Hello")
        return {"text": "Hello", "citations": [{"url": "https://a", "title": "A"}],
                "usage": {"output_tokens": 5}, "tool_calls": 0}

    try:
        rc.stream_response = stub_ok
        sent = asyncio.run(_run(
            [json.dumps({"type": "chat", "messages": [{"role": "user", "content": "hi"}],
                         "model": "grok-4.3"})],
            _backend()))
        deltas = [m for m in sent if m.get("type") == "delta"]
        done = [m for m in sent if m.get("type") == "done"]
        cits = [m for m in sent if m.get("type") == "citations"]
        checks.append(("chat bridge: deltas incremental (delta field, no full)",
                       bool(deltas) and all("delta" in d and "full" not in d for d in deltas)))
        checks.append(("chat bridge: deltas accumulate to full text",
                       "".join(d.get("delta", "") for d in deltas) == "Hello"))
        checks.append(("chat bridge: done carries full", bool(done) and done[0].get("full") == "Hello"))
        checks.append(("chat bridge: citations frame forwarded",
                       bool(cits) and cits[0]["citations"][0]["url"] == "https://a"))
    except Exception as exc:  # noqa: BLE001
        checks.append((f"chat bridge: protocol scenario ran ({exc})", False))
    finally:
        rc.stream_response = orig_stream

    # --- scenariusz 2: live search → ramka tool_call ---
    def stub_search(messages, **kw):
        kw["on_tool"]({"tool": "web_search", "status": "searching", "query": "q"})
        kw["on_delta"]("R", "R")
        return {"text": "R", "citations": [{"url": "https://s", "title": "S"}],
                "usage": {}, "tool_calls": 1}

    try:
        rc.stream_response = stub_search
        sent = asyncio.run(_run(
            [json.dumps({"type": "chat", "messages": [{"role": "user", "content": "news?"}],
                         "model": "grok-4.3", "search_mode": "auto"})],
            _backend()))
        tcs = [m for m in sent if m.get("type") == "tool_call"]
        checks.append(("chat bridge: tool_call frame for live search",
                       bool(tcs) and tcs[0].get("tool") == "web_search"))
    except Exception as exc:  # noqa: BLE001
        checks.append((f"chat bridge: search scenario ran ({exc})", False))
    finally:
        rc.stream_response = orig_stream

    # --- scenariusz 3: fallback na legacy gdy Responses padnie (czysty czat) ---
    def stub_raise(messages, **kw):
        raise RuntimeError("responses unavailable")

    def legacy(messages, model=None, temperature=None, on_delta=None, stop_flag=None):
        on_delta("Leg", "Leg")
        on_delta("acy", "Legacy")
        return "Legacy"

    try:
        rc.stream_response = stub_raise
        sent = asyncio.run(_run(
            [json.dumps({"type": "chat", "messages": [{"role": "user", "content": "hi"}],
                         "model": "grok-4.3"})],
            _backend(legacy_fn=legacy)))
        done = [m for m in sent if m.get("type") == "done"]
        errs = [m for m in sent if m.get("type") == "error"]
        checks.append(("chat bridge: legacy fallback on Responses failure (no tools)",
                       bool(done) and done[0].get("full") == "Legacy" and not errs))
    except Exception as exc:  # noqa: BLE001
        checks.append((f"chat bridge: fallback scenario ran ({exc})", False))
    finally:
        rc.stream_response = orig_stream

    # --- scenariusz 4: wizja na modelu spoza grok-4 → czytelny błąd, bez tury ---
    try:
        img_msg = {"role": "user", "content": [
            {"type": "text", "text": "describe"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA"}}]}
        sent = asyncio.run(_run(
            [json.dumps({"type": "chat", "messages": [img_msg], "model": "grok-3"})],
            _backend()))
        errs = [m for m in sent if m.get("type") == "error"]
        dones = [m for m in sent if m.get("type") == "done"]
        checks.append(("chat bridge: vision on non-grok-4 -> clear error, no turn",
                       bool(errs) and "grok-4" in (errs[0].get("error") or "") and not dones))
    except Exception as exc:  # noqa: BLE001
        checks.append((f"chat bridge: vision gating scenario ran ({exc})", False))
    finally:
        rc.stream_response = orig_stream

    # --- scenariusz 5: single-flight (drugi chat w trakcie -> błąd busy) ---
    def stub_hold(release):
        def _s(messages, **kw):
            kw["on_delta"]("A", "A")
            release.wait(5)  # trzymaj workera, aż nadejdzie drugi chat
            return {"text": "A", "citations": [], "usage": {}, "tool_calls": 0}
        return _s

    async def scenario_single_flight():
        sent: list = []
        release = _th.Event()
        busy_evt = asyncio.Event()
        done_evt = asyncio.Event()

        async def on_send(item):
            sent.append(item)
            if item.get("type") == "error" and "already streaming" in (item.get("error") or ""):
                busy_evt.set()
            if item.get("type") == "done":
                done_evt.set()

        async def wait_then_disconnect():
            await busy_evt.wait()
            release.set()
            await done_evt.wait()

        rc.stream_response = stub_hold(release)
        frame = json.dumps({"type": "chat", "messages": [], "model": "grok-4.3"})
        ws = _FakeWS(_backend(), [frame, frame], on_send)
        ws._wait_then_disconnect = wait_then_disconnect
        await asyncio.wait_for(chat_route.chat_stream(ws), timeout=10)
        return sent

    try:
        sent2 = asyncio.run(scenario_single_flight())
        busy = [m for m in sent2 if m.get("type") == "error" and "already streaming" in (m.get("error") or "")]
        checks.append(("chat bridge: single-flight rejects 2nd chat", bool(busy)))
    except Exception as exc:  # noqa: BLE001
        checks.append((f"chat bridge: single-flight scenario ran ({exc})", False))
    finally:
        rc.stream_response = orig_stream


def _unit_api_timeouts(checks: list) -> None:
    """P1-4: każde wywołanie HTTP w APIManager przekazuje jawny timeout=.
    Bez sieci — podmieniamy `api_manager.requests` na atrapę nagrywającą kwargs."""
    import types

    sys.path.insert(0, REPO_DIR)
    import api_manager  # type: ignore  # noqa: E402

    calls: list = []

    class _FakeResp:
        status_code = 200
        headers = {"Content-Type": "audio/mpeg"}
        content = b""
        text = ""
        encoding = "utf-8"

        def raise_for_status(self):
            pass

        def json(self):
            return {
                "data": [{"url": "u"}],
                "request_id": "rid",
                "choices": [{"message": {"content": "x", "role": "assistant"}}],
            }

    def _rec(method):
        def f(url, **kw):
            calls.append((method, url, kw.get("timeout")))
            return _FakeResp()
        return f

    original = api_manager.requests
    api_manager.requests = types.SimpleNamespace(post=_rec("post"), get=_rec("get"))
    try:
        m = api_manager.APIManager(lambda: "k")
        m.generate_image("p", 1, "auto", "1k")
        m.edit_image_b64("p", ["data:image/jpeg;base64,AAAA"])
        m.create_video_job("p", 5, "720p", "Original")
        m.edit_video_job("p", "https://x/v.mp4")
        m.extend_video_job("p", "https://x/v.mp4")
        m.poll_video_status("rid")
        m.text_to_speech("hi")
        m.speech_to_text(b"x")
        m.chat_completion([{"role": "user", "content": "hi"}])
        m.chat_with_tools([{"role": "user", "content": "hi"}])
        m.list_models()
        # chat_completion_stream pomijamy — używa `with requests.post(...)` (context manager).
    finally:
        api_manager.requests = original

    missing = [(meth, url) for (meth, url, t) in calls if t is None]
    checks.append((f"api_manager: every HTTP call passes timeout ({len(calls)} calls)", not missing))
    if missing:
        for meth, url in missing:
            print(f"    [!] brak timeout: {meth} {url}")


def _unit_input_validation(checks: list) -> None:
    """P1-8: modele tras odrzucają złe wejście (Pydantic → 422)."""
    sys.path.insert(0, REPO_DIR)
    from pydantic import ValidationError  # noqa: E402
    from grok_core.routes.media import EditImageReq, GenerateImageReq, VideoExtendReq  # noqa: E402
    from grok_core.routes.voice import TTSReq  # noqa: E402

    def rejects(fn) -> bool:
        try:
            fn()
        except ValidationError:
            return True
        except Exception:
            return False
        return False

    ok = True
    try:
        GenerateImageReq(prompt="a cat", n=2)
        EditImageReq(prompt="x", images=["data:image/png;base64,AAAA"])
        TTSReq(text="hello")
        VideoExtendReq(prompt="x", video="https://x/v.mp4", duration=5)
    except Exception:
        ok = False
    checks.append(("validation: valid input accepted", ok))
    checks.append(("validation: n out of range rejected",
                   rejects(lambda: GenerateImageReq(prompt="x", n=999))))
    checks.append(("validation: empty prompt rejected",
                   rejects(lambda: GenerateImageReq(prompt="", n=1))))
    checks.append(("validation: non-data-URI image rejected",
                   rejects(lambda: EditImageReq(prompt="x", images=["http://evil/x.png"]))))
    checks.append(("validation: too many images rejected",
                   rejects(lambda: EditImageReq(prompt="x", images=["data:image/png;base64,AA"] * 50))))
    checks.append(("validation: extend duration out of range rejected",
                   rejects(lambda: VideoExtendReq(prompt="x", video="https://x/v.mp4", duration=99))))
    checks.append(("validation: empty TTS text rejected", rejects(lambda: TTSReq(text=""))))


def _unit_sse_utf8(checks: list) -> None:
    """P3-1: chat_completion_stream dekoduje SSE jako JAWNE UTF-8 (strażnik regresji
    mojibake — `requests` zgaduje ISO-8859-1 dla text/event-stream; CLAUDE.md).
    Bez sieci — podmieniamy `api_manager.requests.post` na atrapę zwracającą strumień
    bajtów (jak na drucie). Kontrolujemy też prefiks `data:`, `[DONE]` i akumulację."""
    import types

    sys.path.insert(0, REPO_DIR)
    import api_manager  # type: ignore  # noqa: E402

    text = "Zażółć gęślą jaźń — €µ✓"

    def _frame(content: str) -> bytes:
        # ensure_ascii=False → na drucie LĄDUJĄ surowe wielobajtowe sekwencje UTF-8
        # (nie \uXXXX), więc atrapa naprawdę testuje dekodowanie bajtów, nie JSON-a.
        body = json.dumps({"choices": [{"delta": {"content": content}}]}, ensure_ascii=False)
        return b"data: " + body.encode("utf-8")

    frames = [_frame(text[:8]), _frame(text[8:]), b"", b"data: [DONE]"]
    captured: dict = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def raise_for_status(self):
            pass

        def iter_lines(self, decode_unicode=False):
            captured["decode_unicode"] = decode_unicode
            for f in frames:
                yield f

    def _post(url, **kw):
        captured["stream"] = kw.get("stream")
        captured["timeout"] = kw.get("timeout")
        return _Resp()

    original = api_manager.requests
    api_manager.requests = types.SimpleNamespace(post=_post, get=getattr(original, "get", None))
    try:
        m = api_manager.APIManager(lambda: "k")
        deltas: list = []
        full = m.chat_completion_stream(
            [{"role": "user", "content": "x"}],
            on_delta=lambda d, f: deltas.append((d, f)),
        )
    finally:
        api_manager.requests = original

    checks.append(("sse utf-8: full text decoded (no mojibake)", full == text))
    checks.append(("sse utf-8: deltas accumulate to full",
                   bool(deltas) and deltas[-1][1] == text))
    checks.append(("sse utf-8: requests called with stream=True + timeout",
                   captured.get("stream") is True and captured.get("timeout") is not None))
    checks.append(("sse utf-8: iter_lines(decode_unicode=False) (bytes path)",
                   captured.get("decode_unicode") is False))


def _unit_settings_ownership(checks: list) -> None:
    """P3-1: zapis ustawień NIE rusza grok_config.json (CLAUDE.md: ten plik jest
    wyłączną domeną HistoryManagera — zapis czegokolwiek innego kasuje dane).

    Przekierowujemy WSZYSTKIE pliki danych do tempdir (config.* oraz nazwy już
    zaimportowane do legacy modułów), siejemy sentinel w grok_config.json, robimy
    Backend.update_settings(...) i sprawdzamy, że grok_config.json jest nietknięty,
    a patch trafił do grok_settings.json. Oryginalne ścieżki przywracamy w finally."""
    import tempfile

    sys.path.insert(0, REPO_DIR)
    import config  # type: ignore  # noqa: E402
    import chats_manager  # type: ignore  # noqa: E402
    import history_manager  # type: ignore  # noqa: E402
    from grok_core.state import Backend  # noqa: E402

    # config.* czytane są dynamicznie (atrybut); ale legacy moduły zrobiły
    # `from config import CONFIG_FILE/HISTORY_DIR/CHATS_FILE` → trzeba podmienić też u nich.
    saved_cfg = {k: getattr(config, k) for k in
                 ("SETTINGS_FILE", "CONFIG_FILE", "CHATS_FILE", "PERMISSIONS_FILE",
                  "AUTH_FILE", "HISTORY_DIR")}
    saved_hist = (history_manager.CONFIG_FILE, history_manager.HISTORY_DIR)
    saved_chats = chats_manager.CHATS_FILE

    with tempfile.TemporaryDirectory() as d:
        dp = __import__("pathlib").Path(d)
        try:
            config.SETTINGS_FILE = dp / "grok_settings.json"
            config.CONFIG_FILE = dp / "grok_config.json"
            config.CHATS_FILE = dp / "grok_chats.json"
            config.PERMISSIONS_FILE = dp / "grok_permissions.json"
            config.AUTH_FILE = dp / "grok_auth.json"
            config.HISTORY_DIR = dp / "generated_history"
            config.HISTORY_DIR.mkdir(exist_ok=True)
            history_manager.CONFIG_FILE = config.CONFIG_FILE
            history_manager.HISTORY_DIR = config.HISTORY_DIR
            chats_manager.CHATS_FILE = config.CHATS_FILE

            # Sentinel w domenie HistoryManagera (history/chat_history/save_path).
            sentinel = json.dumps(
                {"history": [{"mode": "generate", "url": "x", "prompt": "p"}],
                 "chat_history": [], "save_path": str(config.HISTORY_DIR)},
                ensure_ascii=False, indent=2)
            config.CONFIG_FILE.write_text(sentinel, encoding="utf-8")
            before = config.CONFIG_FILE.read_text(encoding="utf-8")

            b = Backend()
            b.update_settings({"chat_model": "grok-4", "api_key": "sk-SECRET-should-stay-put"})

            after = config.CONFIG_FILE.read_text(encoding="utf-8")
            checks.append(("settings ownership: grok_config.json untouched by settings write",
                           after == before))

            s = json.loads(config.SETTINGS_FILE.read_text(encoding="utf-8"))
            checks.append(("settings ownership: patch persisted to grok_settings.json",
                           s.get("chat_model") == "grok-4"))
            checks.append(("settings ownership: api key stored (has_api_key)",
                           b.has_api_key() is True))
        except Exception as exc:  # noqa: BLE001
            checks.append((f"settings ownership: scenario ran ({exc})", False))
        finally:
            for k, v in saved_cfg.items():
                setattr(config, k, v)
            history_manager.CONFIG_FILE, history_manager.HISTORY_DIR = saved_hist
            chats_manager.CHATS_FILE = saved_chats


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


def _unit_rest_token_auth(checks: list) -> None:
    """P1-10: require_token jest FAIL-CLOSED bez skonfigurowanego tokenu (jak WS)."""
    import types

    sys.path.insert(0, REPO_DIR)
    from fastapi import HTTPException  # noqa: E402
    from grok_core.state import require_token  # noqa: E402

    def fake(state_token: str):
        return types.SimpleNamespace(
            app=types.SimpleNamespace(state=types.SimpleNamespace(session_token=state_token)))

    def raises(state_token, authorization, status) -> bool:
        try:
            require_token(fake(state_token), authorization)
            return False
        except HTTPException as e:
            return e.status_code == status

    checks.append(("rest_auth: valid bearer accepted",
                   require_token(fake("secret"), "Bearer secret") is None))
    checks.append(("rest_auth: missing bearer rejected (401)", raises("secret", None, 401)))
    checks.append(("rest_auth: bad bearer rejected (403)", raises("secret", "Bearer nope", 403)))

    os.environ.pop("GROK_CORE_ALLOW_NO_TOKEN", None)
    checks.append(("rest_auth: no-token config -> DENIED (fail-closed)",
                   raises("", "Bearer anything", 401)))
    os.environ["GROK_CORE_ALLOW_NO_TOKEN"] = "1"
    checks.append(("rest_auth: explicit opt-in allows no-token",
                   require_token(fake(""), None) is None))
    os.environ.pop("GROK_CORE_ALLOW_NO_TOKEN", None)


def _unit_json_corrupt_backup(checks: list) -> None:
    """P1-11: load_json_or_backup — brak pliku → default; korupcja → kopia .corrupt."""
    import tempfile
    from pathlib import Path

    sys.path.insert(0, REPO_DIR)
    import config  # type: ignore  # noqa: E402

    with tempfile.TemporaryDirectory() as d:
        missing = Path(d) / "nope.json"
        checks.append(("json loader: missing file -> default",
                       config.load_json_or_backup(missing, {"x": 1}) == {"x": 1}))

        good = Path(d) / "good.json"
        good.write_text('{"a": 2}', encoding="utf-8")
        checks.append(("json loader: valid json returned",
                       config.load_json_or_backup(good, None) == {"a": 2}))

        bad = Path(d) / "bad.json"
        bad.write_text("{not valid json", encoding="utf-8")
        res = config.load_json_or_backup(bad, {"fallback": True})
        backup = Path(str(bad) + ".corrupt")
        checks.append(("json loader: corrupt -> default", res == {"fallback": True}))
        checks.append(("json loader: corrupt moved to .corrupt (original gone)",
                       backup.exists() and not bad.exists()))


def _unit_error_sanitization(checks: list) -> None:
    """P1-13: git nie zwraca surowego stderr (ścieżek FS) — generyczny detail."""
    import types
    from pathlib import Path

    sys.path.insert(0, REPO_DIR)
    from fastapi import HTTPException  # noqa: E402
    from grok_core.routes import git as git_route  # noqa: E402

    abs_path = "C:\\Users\\victim\\secret\\repo\\.git"
    fakews = types.SimpleNamespace(root=Path("."))

    orig = git_route._run_git
    git_route._run_git = lambda ws, args, timeout=20: (1, "", f"fatal: {abs_path}")
    try:
        st = git_route.status(ws=fakews)
        checks.append(("error sanit: git status detail generic (no abs path)",
                       abs_path not in (st.get("detail") or "")))
        try:
            git_route.commit(types.SimpleNamespace(message="x", stage_all=False), ws=fakews)
            commit_detail = ""
        except HTTPException as e:
            commit_detail = str(e.detail)
        checks.append(("error sanit: git commit detail generic (no abs path)",
                       abs_path not in commit_detail and commit_detail == "git commit failed"))
    finally:
        git_route._run_git = orig


def _unit_media_download_guard(checks: list) -> None:
    """P1-14: pobieranie mediów — tylko https, twardy limit rozmiaru (Content-Length)."""
    import tempfile
    import types
    from pathlib import Path

    sys.path.insert(0, REPO_DIR)
    import grok_core.state as state_mod  # noqa: E402

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
            return _Resp([b"x"], headers={"Content-Length": str(state_mod.MAX_MEDIA_BYTES + 1)})
        return _Resp([b"abc", b"def"])

    orig = state_mod.requests
    state_mod.requests = types.SimpleNamespace(get=fake_get)
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
        state_mod.requests = orig


def _unit_fs_routes(checks: list) -> None:
    """P3-8: zachowanie tras /fs (write/read/tree) + sandbox — in-process, bez xAI
    i bez zaśmiecania realnych plików danych (route'y wołane wprost na temp workspace)."""
    import tempfile
    from pathlib import Path

    sys.path.insert(0, REPO_DIR)
    from fastapi import HTTPException  # noqa: E402
    from grok_core.agent.workspace import Workspace  # noqa: E402
    from grok_core.routes import fs as fs_route  # noqa: E402

    def rejects400(fn) -> bool:
        try:
            fn()
            return False
        except HTTPException as e:
            return e.status_code == 400

    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        r = fs_route.write(fs_route.WriteReq(path="sub/hello.txt", content="hi from test"), ws=ws)
        checks.append(("/fs/write ok + on disk",
                       r.get("ok") is True
                       and (Path(d) / "sub/hello.txt").read_text(encoding="utf-8") == "hi from test"))

        r = fs_route.read("sub/hello.txt", ws=ws)
        checks.append(("/fs/read round-trips content", r.get("content") == "hi from test"))

        r = fs_route.tree(".", ws=ws)
        names = [e["name"] for e in r["entries"]]
        checks.append(("/fs/tree lists workspace entry", "sub" in names))

        # sandbox: ucieczki poza workspace → 400 (nie wyciekają plików spoza root)
        checks.append(("/fs/read rejects '..' escape (400)",
                       rejects400(lambda: fs_route.read("../../etc/passwd", ws=ws))))
        checks.append(("/fs/write rejects '..' escape (400)",
                       rejects400(lambda: fs_route.write(fs_route.WriteReq(path="../escape.txt", content="x"), ws=ws))))
        checks.append(("/fs/tree rejects '..' escape (400)",
                       rejects400(lambda: fs_route.tree("../..", ws=ws))))


def _unit_git_routes(checks: list) -> None:
    """P3-8: zachowanie tras /git (status/commit + walidacja) — in-process."""
    import subprocess
    import tempfile
    from pathlib import Path

    sys.path.insert(0, REPO_DIR)
    from fastapi import HTTPException  # noqa: E402
    from grok_core.agent.workspace import Workspace  # noqa: E402
    from grok_core.routes import git as git_route  # noqa: E402

    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        r = git_route.status(ws=ws)
        checks.append(("/git/status non-repo -> is_repo false", r.get("is_repo") is False))

        ready = True
        try:
            for args in (["init"], ["config", "user.email", "t@t.test"], ["config", "user.name", "Tester"]):
                subprocess.run(["git", *args], cwd=d, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=15, check=True)
        except Exception:
            ready = False

        if not ready:
            checks.append(("git unavailable — repo tests skipped", True))
            return

        (Path(d) / "a.txt").write_text("hello\n", encoding="utf-8")
        r = git_route.status(ws=ws)
        checks.append(("/git/status repo -> is_repo true", r.get("is_repo") is True))

        r = git_route.commit(git_route.CommitReq(message="test commit", stage_all=True), ws=ws)
        checks.append(("/git/commit (stage_all) -> ok", r.get("ok") is True))

        def rejects400(fn) -> bool:
            try:
                fn()
                return False
            except HTTPException as e:
                return e.status_code == 400

        checks.append(("/git/commit empty message -> 400",
                       rejects400(lambda: git_route.commit(
                           git_route.CommitReq(message="   ", stage_all=False), ws=ws))))


def _unit_history_routes(checks: list) -> None:
    """M9-B3: trasy /history i /artifacts (lista + filtry FTS + paginacja) oraz
    /artifacts/{id} i /artifacts/{id}/content (strumień + walidacja ścieżki).
    In-process: magazyn podmieniony na temp (HS._default_store), Backend bez I/O
    (__new__), legacy history zatrapowane — bez sieci i bez realnych plików danych."""
    import tempfile
    from pathlib import Path

    sys.path.insert(0, REPO_DIR)
    from fastapi import HTTPException  # noqa: E402
    from fastapi.responses import FileResponse  # noqa: E402
    import grok_core.history_store as HS  # noqa: E402
    from grok_core.history_store import HistoryStore  # noqa: E402
    from grok_core.routes import history as hist_route  # noqa: E402
    from grok_core.state import Backend  # noqa: E402

    with tempfile.TemporaryDirectory() as d:
        store = HistoryStore(Path(d) / "h.db")
        prev = HS._default_store
        HS._default_store = store  # Backend.history_store → temp
        try:
            b = Backend.__new__(Backend)  # bez __init__ (bez I/O / sieci)

            class _FakeHistory:
                def get_save_path(self_) -> str:
                    return d  # dozwolony katalog treści = temp

            b.history = _FakeHistory()

            # seed: artefakt-obraz z plikiem na dysku + zdarzenia dwóch trybów
            pic = Path(d) / "pic.png"
            pic.write_bytes(b"\x89PNG\r\n\x1a\nfake-bytes")
            art = store.add_artifact(type="image", mode="image", mime="image/png",
                                     path=str(pic), meta={"prompt": "neon cyberpunk"})
            store.record_event(mode="image", text="neon cyberpunk skyline", artifact_id=art.id)
            store.record_event(mode="chat", text="hello about dragons")

            def H(**kw):
                p = dict(q=None, mode=None, project_id=None, from_=None, to=None,
                         limit=50, offset=0)
                p.update(kw)
                return hist_route.list_history(b=b, **p)

            def A(**kw):
                p = dict(mode=None, project_id=None, from_=None, to=None,
                         limit=50, offset=0)
                p.update(kw)
                return hist_route.list_artifacts(b=b, **p)

            r = H()
            checks.append(("/history lists all events", len(r["events"]) == 2))
            r = H(q="cyberpunk")
            checks.append(("/history q (FTS) filters + ranks",
                           len(r["events"]) == 1 and r["events"][0]["mode"] == "image"))
            r = H(mode="chat")
            checks.append(("/history mode filter",
                           len(r["events"]) == 1 and r["events"][0]["mode"] == "chat"))
            r = H(limit=1)
            checks.append(("/history paginates (limit)", len(r["events"]) == 1 and r["limit"] == 1))

            r = A()
            checks.append(("/artifacts lists artifacts", len(r["artifacts"]) == 1))
            r = A(mode="video")
            checks.append(("/artifacts mode filter narrows", r["artifacts"] == []))

            meta = hist_route.get_artifact(art.id, b=b)
            checks.append(("/artifacts/{id} metadata",
                           meta["id"] == art.id and meta["mime"] == "image/png"))

            missing404 = False
            try:
                hist_route.get_artifact("does-not-exist", b=b)
            except HTTPException as e:
                missing404 = e.status_code == 404
            checks.append(("/artifacts/{id} missing -> 404", missing404))

            resp = hist_route.get_artifact_content(art.id, b=b)
            checks.append(("/artifacts/{id}/content -> FileResponse (inline)",
                           isinstance(resp, FileResponse)
                           and Path(resp.path).name == "pic.png"
                           and resp.media_type == "image/png"))

            # M9-B4: send-to bus — obraz → blok vision (image_url, base64 z dysku)
            ib = hist_route.artifact_input_block(art.id, b=b)
            checks.append(("/artifacts/{id}/input-block (image) -> vision block",
                           ib["block"]["type"] == "image_url"
                           and ib["block"]["image_url"]["url"].startswith("data:image/png;base64,")))
            ib_missing404 = False
            try:
                hist_route.artifact_input_block("does-not-exist", b=b)
            except HTTPException as e:
                ib_missing404 = e.status_code == 404
            checks.append(("/artifacts/{id}/input-block missing -> 404", ib_missing404))

            # anty-traversal: artefakt wskazujący POZA dozwolone katalogi → 403
            outside = Path(d).resolve().parent / "grok_b3_outside_marker.bin"
            evil = store.add_artifact(type="file", mode="file", path=str(outside))
            denied = False
            try:
                hist_route.get_artifact_content(evil.id, b=b)
            except HTTPException as e:
                denied = e.status_code == 403
            checks.append(("/artifacts/{id}/content outside allowed dirs -> 403", denied))

            # M11 follow-up: DELETE /artifacts/{id} kasuje rekord + plik (sandbox)
            pic2 = Path(d) / "del.png"
            pic2.write_bytes(b"\x89PNG\r\n\x1a\nx")
            delart = store.add_artifact(type="image", mode="image", mime="image/png", path=str(pic2))
            r = hist_route.delete_artifact(delart.id, b=b)
            checks.append(("/artifacts/{id} DELETE removes record + file",
                           r["ok"] is True and r["deleted_file"] is True
                           and not pic2.exists() and store.get_artifact(delart.id) is None))
            del404 = False
            try:
                hist_route.delete_artifact("does-not-exist", b=b)
            except HTTPException as e:
                del404 = e.status_code == 404
            checks.append(("/artifacts/{id} DELETE unknown -> 404", del404))

            # DELETE artefaktu spoza dozwolonych katalogów: rekord znika, pliku NIE ruszamy
            ext_marker = Path(d).resolve().parent / "grok_del_outside_marker.bin"
            ext_marker.write_bytes(b"keep")
            try:
                evil2 = store.add_artifact(type="file", mode="file", path=str(ext_marker))
                r2 = hist_route.delete_artifact(evil2.id, b=b)
                checks.append(("/artifacts/{id} DELETE outside dir: record gone, file kept",
                               r2["deleted_file"] is False and ext_marker.exists()
                               and store.get_artifact(evil2.id) is None))
            finally:
                if ext_marker.exists():
                    ext_marker.unlink()
        except Exception as exc:  # noqa: BLE001
            checks.append((f"history routes: scenario ran ({exc})", False))
        finally:
            HS._default_store = prev
            store.close()


def _unit_projects_routes(checks: list) -> None:
    """M9-B5: trasy /projects (list/create/select) + stemplowanie aktywnym projektem.
    In-process: magazyn → temp (HS._default_store), SETTINGS_FILE → temp (current_project
    i recent_workspaces nie dotykają realnego grok_settings.json), Backend bez I/O."""
    import tempfile
    from pathlib import Path

    sys.path.insert(0, REPO_DIR)
    import config  # type: ignore  # noqa: E402
    from fastapi import HTTPException  # noqa: E402
    import grok_core.history_store as HS  # noqa: E402
    from grok_core.history_store import HistoryStore  # noqa: E402
    from grok_core.routes import projects as proj_route  # noqa: E402
    from grok_core.state import Backend  # noqa: E402

    with tempfile.TemporaryDirectory() as d:
        store = HistoryStore(Path(d) / "h.db")
        prev_store = HS._default_store
        prev_settings = config.SETTINGS_FILE
        HS._default_store = store
        config.SETTINGS_FILE = Path(d) / "grok_settings.json"
        try:
            b = Backend.__new__(Backend)  # bez __init__; current_project_id = class default None

            r = proj_route.list_projects(b=b)
            checks.append(("/projects empty list + shape",
                           r["projects"] == [] and "current_project_id" in r
                           and "recent_workspaces" in r))

            r = proj_route.create_project(proj_route.CreateProjectReq(name="Alpha"), b=b)
            pid = r["project"]["id"]
            checks.append(("/projects create selects it as current", r["current_project_id"] == pid))

            # aktywny projekt stempluje zapisywane zdarzenia
            b.record_event(mode="chat", text="scoped alpha note")
            checks.append(("/projects active stamps recorded events",
                           len(store.list_events(project_id=pid)) == 1))

            r = proj_route.list_projects(b=b)
            checks.append(("/projects lists created project",
                           [p["id"] for p in r["projects"]] == [pid] and r["current_project_id"] == pid))

            r = proj_route.select_project(proj_route.SelectProjectReq(project_id=None), b=b)
            checks.append(("/projects/current null clears active",
                           b.current_project_id is None and r["project"] is None))

            unknown404 = False
            try:
                proj_route.select_project(proj_route.SelectProjectReq(project_id="does-not-exist"), b=b)
            except HTTPException as e:
                unknown404 = e.status_code == 404
            checks.append(("/projects/current unknown id -> 404", unknown404))

            # select istniejący ponownie ustawia aktywny
            proj_route.select_project(proj_route.SelectProjectReq(project_id=pid), b=b)
            checks.append(("/projects/current re-selects existing", b.current_project_id == pid))
        except Exception as exc:  # noqa: BLE001
            checks.append((f"projects routes: scenario ran ({exc})", False))
        finally:
            HS._default_store = prev_store
            config.SETTINGS_FILE = prev_settings
            store.close()


def _unit_agent_routes(checks: list) -> None:
    """M13-B5: trasy /agent/checkpoints, /agent/undo, /agent/grok-md — in-process,
    bez sieci. Backend bez __init__ (tylko workspace + checkpointy na temp)."""
    import tempfile
    from pathlib import Path

    sys.path.insert(0, REPO_DIR)
    from fastapi import HTTPException  # noqa: E402
    from grok_core.agent.workspace import Workspace  # noqa: E402
    from grok_core.routes import agent_api as ar  # noqa: E402
    from grok_core.state import Backend  # noqa: E402

    with tempfile.TemporaryDirectory() as d:
        b = Backend.__new__(Backend)  # bez __init__ (bez I/O / sieci)
        b._workspace = None
        b._checkpoints = None

        r = ar.list_checkpoints(b=b)
        checks.append(("/agent/checkpoints no workspace -> empty",
                       r["has_workspace"] is False and r["checkpoints"] == []))

        undo_400 = False
        try:
            ar.undo(ar.UndoReq(), b=b)
        except HTTPException as e:
            undo_400 = e.status_code == 400
        checks.append(("/agent/undo no workspace -> 400", undo_400))

        ws = Workspace(d)
        b._workspace = ws
        (ws.root / "a.txt").write_text("orig\n", encoding="utf-8")

        cp = b.get_checkpoints()
        cp.begin_turn(label="edit a")
        cp.snapshot("a.txt")
        (ws.root / "a.txt").write_text("changed\n", encoding="utf-8")
        cp.snapshot("new.txt")
        (ws.root / "new.txt").write_text("new\n", encoding="utf-8")

        r = ar.list_checkpoints(b=b)
        checks.append(("/agent/checkpoints lists session checkpoint",
                       r["has_workspace"] is True and len(r["checkpoints"]) == 1
                       and r["checkpoints"][0]["files"] == 2))

        r = ar.undo(ar.UndoReq(), b=b)
        checks.append(("/agent/undo restores + deletes",
                       (ws.root / "a.txt").read_text(encoding="utf-8") == "orig\n"
                       and not (ws.root / "new.txt").exists()
                       and "a.txt" in r["restored"] and "new.txt" in r["deleted"]))

        # nieznany checkpoint -> 404
        cp.begin_turn()
        cp.snapshot("a.txt")
        (ws.root / "a.txt").write_text("x\n", encoding="utf-8")
        unknown404 = False
        try:
            ar.undo(ar.UndoReq(checkpoint_id="does-not-exist"), b=b)
        except HTTPException as e:
            unknown404 = e.status_code == 404
        checks.append(("/agent/undo unknown checkpoint -> 404", unknown404))

        # GROK.md round-trip (atomowy zapis pod workspace, sandbox)
        gm = ar.get_grok_md(b=b)
        checks.append(("/agent/grok-md initial empty",
                       gm["exists"] is False and gm["content"] == ""))
        ar.put_grok_md(ar.GrokMdReq(content="never touch /vendor"), ws=ws)
        gm2 = ar.get_grok_md(b=b)
        checks.append(("/agent/grok-md round-trips",
                       gm2["exists"] is True and "never touch /vendor" in gm2["content"]))


def main() -> int:
    token = secrets.token_urlsafe(16)
    env = dict(os.environ, GROK_CORE_TOKEN=token)
    proc = subprocess.Popen(
        [sys.executable, "-m", "grok_core"],
        cwd=REPO_DIR, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        info = _read_handshake(proc)
        port = info["port"]
        base = f"http://127.0.0.1:{port}"
        print(f"[handshake] port={port} version={info.get('version')}")

        checks = []

        s, body = _get(base, "/health")
        checks.append(("/health == 200", s == 200 and bool(body)))

        # P3-4: wersja z JEDNEGO źródła — sidecar (handshake + /health) raportuje
        # wersję z desktop/package.json (tu bez env GROK_CORE_APP_VERSION → odczyt pliku).
        try:
            pkg_v = json.loads(
                (Path(REPO_DIR) / "desktop" / "package.json").read_text(encoding="utf-8")
            ).get("version")
        except Exception as exc:  # noqa: BLE001
            pkg_v = None
            checks.append((f"version: read desktop/package.json ({exc})", False))
        if pkg_v:
            checks.append(("version: handshake == package.json (single source)",
                           info.get("version") == pkg_v))
            checks.append(("version: /health == package.json",
                           bool(body) and body.get("version") == pkg_v))

        s, body = _get(base, "/whoami", token)
        checks.append(("/whoami(token) == 200 + backend_ready", s == 200 and body and body.get("backend_ready") is True))

        s, body = _get(base, "/auth/status", token)
        checks.append(("/auth/status == 200", s == 200 and body is not None and "authenticated" in body))

        s, body = _get(base, "/models", token)
        ok_models = s == 200 and body and isinstance(body.get("chat"), list) and len(body["chat"]) > 0
        checks.append(("/models == 200 + chat list", ok_models))
        if ok_models:
            print(f"  [info] models.default_chat={body.get('default_chat')} default_code={body.get('default_code')} chat_count={len(body['chat'])}")

        s, body = _get(base, "/settings", token)
        checks.append(("/settings == 200", s == 200 and body is not None and "chat_model" in body))

        s, body = _get(base, "/permissions", token)
        checks.append(("/permissions == 200 + rules list", s == 200 and body is not None and isinstance(body.get("rules"), list)))

        s, body = _get(base, "/fs/recent", token)
        checks.append(("/fs/recent == 200 + recent list", s == 200 and body is not None and isinstance(body.get("recent"), list)))

        # M9-B3: historia/artefakty huba — 200 + kształt (treść zależy od stanu bazy).
        s, body = _get(base, "/history", token)
        checks.append(("/history == 200 + events list",
                       s == 200 and body is not None and isinstance(body.get("events"), list)))
        s, body = _get(base, "/artifacts", token)
        checks.append(("/artifacts == 200 + artifacts list",
                       s == 200 and body is not None and isinstance(body.get("artifacts"), list)))
        s, _ = _get(base, "/history")
        checks.append(("/history (no token) == 401", s == 401))
        s, _ = _get(base, "/history", "wrong")
        checks.append(("/history (bad token) == 403", s == 403))
        # M9-B4: send-to bus route guarded + 404 for unknown id (with token).
        s, _ = _get(base, "/artifacts/nope/input-block")
        checks.append(("/artifacts/{id}/input-block (no token) == 401", s == 401))
        s, _ = _get(base, "/artifacts/nope/input-block", token)
        checks.append(("/artifacts/{id}/input-block (unknown id) == 404", s == 404))
        # M11 follow-up: usuwanie artefaktu — token gate + 404 dla nieznanego id.
        s, _ = _delete(base, "/artifacts/nope")
        checks.append(("DELETE /artifacts/{id} (no token) == 401", s == 401))
        s, _ = _delete(base, "/artifacts/does-not-exist", token)
        checks.append(("DELETE /artifacts/{id} (unknown id) == 404", s == 404))

        # M9-B5: projekty huba — 200 + kształt; bramka tokenu.
        s, body = _get(base, "/projects", token)
        checks.append(("/projects == 200 + shape",
                       s == 200 and body is not None and isinstance(body.get("projects"), list)
                       and "current_project_id" in body))
        s, _ = _get(base, "/projects")
        checks.append(("/projects (no token) == 401", s == 401))
        s, _ = _post(base, "/projects/current", {"project_id": None})
        checks.append(("/projects/current (no token) == 401", s == 401))

        # M10-B5: collections (project knowledge / file_search) — 200 + shape; token gate.
        s, body = _get(base, "/collections", token)
        checks.append(("/collections == 200 + shape",
                       s == 200 and body is not None and isinstance(body.get("files"), list)
                       and "has_collection" in body))
        s, _ = _get(base, "/collections")
        checks.append(("/collections (no token) == 401", s == 401))

        # M13-B5: agent checkpoints/undo/grok-md — 200 + kształt; bramka tokenu.
        s, body = _get(base, "/agent/checkpoints", token)
        checks.append(("/agent/checkpoints == 200 + shape",
                       s == 200 and body is not None and isinstance(body.get("checkpoints"), list)))
        s, _ = _get(base, "/agent/checkpoints")
        checks.append(("/agent/checkpoints (no token) == 401", s == 401))
        s, _ = _post(base, "/agent/undo", {})
        checks.append(("/agent/undo (no token) == 401", s == 401))
        s, _ = _post(base, "/agent/undo", {}, "wrong")
        checks.append(("/agent/undo (bad token) == 403", s == 403))

        s, _ = _get(base, "/models")
        checks.append(("/models (no token) == 401", s == 401))
        s, _ = _get(base, "/models", "wrong")
        checks.append(("/models (bad token) == 403", s == 403))

        # P1-9: CORS zawężony — dev loopback dozwolony, obcy origin odcięty.
        checks.append(("CORS allows dev loopback origin",
                       _cors_acao(base, "/health", "http://localhost:5173") == "http://localhost:5173"))
        checks.append(("CORS allows file:// (null) origin",  # spakowany Electron
                       _cors_acao(base, "/health", "null") == "null"))
        checks.append(("CORS blocks foreign origin",
                       _cors_acao(base, "/health", "https://evil.example") is None))

        # P3-1: żywe trasy media/voice — auth (401/403) + kształt wejścia (422),
        # bez dotykania xAI.
        _live_media_voice_routes(base, token, checks)

        # M11: żywe trasy /genjobs — auth + walidacja (422) + list shape + 404.
        _live_genjobs_routes(base, token, checks)

        # P3-1: żywe testy WS wymagają biblioteki `websockets` (z uvicorn[standard]).
        # Wcześniej brak biblioteki dawał CICHY „pass" (fałszywie zielone). Teraz
        # dostępność to osobna asercja, a żywe testy WS pomijamy jawnie, gdy jej brak.
        try:
            import websockets  # type: ignore  # noqa: F401
            has_ws = True
        except Exception:
            has_ws = False
        checks.append(("websockets installed (uvicorn[standard]) for WS tests", has_ws))
        if has_ws:
            ok_acc, bad_rej = asyncio.run(_ws_check(port, token))
            checks.append(("WS /chat/stream (token) accepted", ok_acc))
            checks.append(("WS /chat/stream (bad token) rejected", bad_rej))

            # P0-8: dangerous WS endpoints must reject a bad token too.
            for path in ("/agent/stream", "/terminal", "/voice/realtime"):
                rej = asyncio.run(_ws_bad_token_rejected(port, path))
                checks.append((f"WS {path} (bad token) rejected", rej))
        else:
            print("  [SKIP] live WS checks — `websockets` not importable (broken venv?)")

        # P0-8: deterministic unit check of the WS auth logic (fail-closed/origin).
        _unit_ws_auth(checks)

        # P1-4: every APIManager HTTP call must pass an explicit timeout.
        _unit_api_timeouts(checks)

        # M10-B1/B2/B3: Responses API client — UTF-8, live-search events, citations.
        _unit_responses_client(checks)

        # M10-B5: collections (file_search) — vector-store client + Backend + routes.
        _unit_collections(checks)

        # P1-3/M10: chat streaming bridge on Responses — deltas, tool_call, citations,
        # legacy fallback, vision gating, file_search attach, single-flight.
        _unit_chat_bridge(checks)

        # P1-8: route input validation (Pydantic constraints / data-URI checks).
        _unit_input_validation(checks)

        # P3-1: SSE dekodowane jako UTF-8 (strażnik mojibake).
        _unit_sse_utf8(checks)

        # P3-1: zapis ustawień nie rusza grok_config.json (własność plików JSON).
        _unit_settings_ownership(checks)

        # M6 — stabilność/dane:
        _unit_rest_token_auth(checks)        # P1-10: REST fail-closed bez tokenu
        _unit_json_corrupt_backup(checks)    # P1-11: loader z backupem .corrupt
        _unit_error_sanitization(checks)     # P1-13: git nie wycieka stderr/ścieżek
        _unit_media_download_guard(checks)   # P1-14: https-only + limit rozmiaru

        # M8 — testy tras (P3-8): fs/git in-process (sandbox, round-trip, commit).
        _unit_fs_routes(checks)
        _unit_git_routes(checks)

        # M9-B3: trasy historii/artefaktów (lista + filtry FTS + content + anty-traversal).
        _unit_history_routes(checks)

        # M9-B5: trasy projektów (list/create/select) + stemplowanie aktywnym projektem.
        _unit_projects_routes(checks)

        # M13-B5: trasy agenta (checkpoints/undo/grok-md) — in-process.
        _unit_agent_routes(checks)

        ok = True
        for name, passed in checks:
            print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
            ok = ok and passed
        print("RESULT:", "OK" if ok else "FAILED")
        return 0 if ok else 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
