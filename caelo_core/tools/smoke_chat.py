"""api_smoke — grupa self-checków: smoke_chat (P3-13 split). Funkcje `_unit_*`/`_live_*(checks)` wołane przez `api_smoke.main()`."""
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


def _unit_responses_client(checks: list) -> None:
    """M10-B1/B2/B3: klient Responses API — bez sieci podmieniamy
    `responses_client.requests.post` na atrapę zwracającą udokumentowany strumień
    SSE (zdarzenia typowane). Sprawdzamy: dekodowanie UTF-8 (mojibake-guard), balans
    historii (role w `input`), aktywność narzędzi (live search), dedup cytowań,
    usage, licznik wywołań, off→bez narzędzi, oraz że klucz idzie z providera."""
    import types

    sys.path.insert(0, REPO_DIR)
    from caelo_core import responses_client as rc  # noqa: E402

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
            reasoning_effort="high",  # M19-B9
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
    # M19-B9: reasoning_effort → `reasoning.effort` w payloadzie (tylko gdy poprawny).
    checks.append(("responses: reasoning_effort -> reasoning.effort in payload (B9)",
                   captured["json"].get("reasoning") == {"effort": "high"}))

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
    import caelo_core.validation as Vmod  # noqa: E402
    cap = Vmod.MAX_DOCUMENT_URI
    Vmod.MAX_DOCUMENT_URI = 64
    try:
        over = rc.to_input([{"role": "user", "content": [
            {"type": "document", "document": {
                "data": "data:application/pdf;base64," + "A" * 200, "name": "big.pdf"}}]}])
    finally:
        Vmod.MAX_DOCUMENT_URI = cap
    checks.append(("responses: oversize document skipped (cap, no crash)", over == []))


def _unit_responses_mcp_loop(checks: list) -> None:
    """M14-B2: klient-side function calling w Responses — model woła narzędzie MCP,
    `tool_handler` je wykonuje, wynik wraca jako `function_call_output` w kolejnej
    turze, finalny tekst jest zwracany. Bez sieci (atrapa SSE per-tura)."""
    import types

    sys.path.insert(0, REPO_DIR)
    from caelo_core import responses_client as rc  # noqa: E402

    def _frame(d) -> bytes:
        return b"data: " + json.dumps(d, ensure_ascii=False).encode("utf-8")

    turn1 = [
        _frame({"type": "response.completed", "response": {
            "usage": {"input_tokens": 5, "output_tokens": 5},
            "output": [{"type": "function_call", "call_id": "c1",
                        "name": "mcp__t__lookup", "arguments": "{\"q\": \"hi\"}"}]}}),
        b"data: [DONE]",
    ]
    turn2 = [
        _frame({"type": "response.output_text.delta", "delta": "final answer"}),
        _frame({"type": "response.completed", "response": {
            "usage": {"output_tokens": 3}, "output": [{"type": "message", "content": [
                {"type": "output_text", "text": "final answer"}]}]}}),
        b"data: [DONE]",
    ]
    captured: dict = {"payloads": []}

    class _Resp:
        def __init__(self, frames):
            self._frames = frames

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def raise_for_status(self):
            pass

        def iter_lines(self, decode_unicode=False):
            for f in self._frames:
                yield f

    def _post(url, **kw):
        i = len(captured["payloads"])
        captured["payloads"].append(kw.get("json"))
        return _Resp(turn1 if i == 0 else turn2)

    handled: list = []

    def handler(name, args):
        handled.append((name, args))
        return "RESULT:" + name

    original = rc.requests
    rc.requests = types.SimpleNamespace(post=_post, get=getattr(original, "get", None))
    try:
        res = rc.stream_response(
            [{"role": "user", "content": "do it"}],
            model="grok-4.3", api_key_provider=lambda: "K",
            function_tools=[{"type": "function", "function": {
                "name": "mcp__t__lookup", "description": "lookup",
                "parameters": {"type": "object", "properties": {"q": {"type": "string"}}}}}],
            tool_handler=handler,
            on_delta=lambda d, f: None,
        )
    finally:
        rc.requests = original

    checks.append(("mcp-loop: tool handler invoked once",
                   handled == [("mcp__t__lookup", {"q": "hi"})]))
    checks.append(("mcp-loop: final text returned after tool", res["text"] == "final answer"))
    checks.append(("mcp-loop: function_tool_calls counted", res.get("function_tool_calls") == 1))
    checks.append(("mcp-loop: two requests made (loop)", len(captured["payloads"]) == 2))
    # 1. żądanie: narzędzie function w FLAT formacie Responses (name na górze, nie pod 'function')
    t0 = (captured["payloads"][0] or {}).get("tools") or []
    checks.append(("mcp-loop: function tool flattened to Responses format",
                   any(t.get("type") == "function" and t.get("name") == "mcp__t__lookup"
                       and "function" not in t for t in t0)))
    # 2. żądanie: wejście niesie function_call_output z wynikiem handlera
    in2 = (captured["payloads"][1] or {}).get("input") or []
    checks.append(("mcp-loop: function_call_output fed back",
                   any(isinstance(it, dict) and it.get("type") == "function_call_output"
                       and it.get("call_id") == "c1" and it.get("output") == "RESULT:mcp__t__lookup"
                       for it in in2)))

    # Bez function_tools/handler zachowanie = JEDNA tura (brak regresji czystego czatu).
    # Przy okazji B3: native remote MCP — blok {type:'mcp',...} ma trafić do payload.tools.
    captured["payloads"].clear()
    rc.requests = types.SimpleNamespace(post=_post, get=getattr(original, "get", None))
    try:
        res2 = rc.stream_response([{"role": "user", "content": "hi"}], model="grok-4.3",
                                  api_key_provider=lambda: "K", on_delta=lambda d, f: None,
                                  remote_tools=[{"type": "mcp", "server_label": "rmt",
                                                 "server_url": "https://ex.com/mcp"}])
    finally:
        rc.requests = original
    checks.append(("mcp-loop: no function tools -> single turn (no regression)",
                   len(captured["payloads"]) == 1 and res2.get("function_tool_calls") == 0))
    rt_tools = (captured["payloads"][0] or {}).get("tools") or []
    checks.append(("mcp-loop: native remote MCP block in Responses payload (B3)",
                   any(t.get("type") == "mcp" and t.get("server_url") == "https://ex.com/mcp"
                       for t in rt_tools)))


def _unit_chat_bridge(checks: list) -> None:
    """M10/P1-3: most czatu na **Responses API** — delty przyrostowe, done z full,
    tool_call + citations (live search), single-flight, fallback na legacy, gating
    wizji. Bez xAI: podmieniamy `responses_client.stream_response` (i legacy
    `api.chat_completion_stream` dla fallbacku) atrapami; handler z atrapą WS."""
    import threading as _th
    import types as _types

    sys.path.insert(0, REPO_DIR)
    from fastapi import WebSocketDisconnect  # noqa: E402
    from caelo_core import responses_client as rc  # noqa: E402
    from caelo_core.routes import chat as chat_route  # noqa: E402

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
        # M14-B2: czat czyta backend.mcp (narzędzia) i backend.permissions (gate). Tu
        # bez serwerów MCP — atrapy zwracają puste listy (zachowanie jak przed M14).
        mcp = _types.SimpleNamespace(
            tool_defs_for_responses=lambda: [], remote_tool_blocks=lambda: [],
            is_mcp_tool=lambda n: False, is_mutating=lambda n: True,
            call_tool=lambda n, a: "")
        permissions = _types.SimpleNamespace(needs_approval_key=lambda k: True)
        return _types.SimpleNamespace(
            api=api, read_settings=lambda: {},
            get_api_key=lambda: "k", record_event=lambda **k: None,
            mcp=mcp, permissions=permissions)

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

    # --- scenariusz 6: reasoning_effort z ramki dociera do stream_response (B9) ---
    seen_eff: dict = {}

    def stub_eff(messages, **kw):
        seen_eff["effort"] = kw.get("reasoning_effort")
        kw["on_delta"]("ok", "ok")
        return {"text": "ok", "citations": [], "usage": {}, "tool_calls": 0}

    try:
        rc.stream_response = stub_eff
        asyncio.run(_run(
            [json.dumps({"type": "chat", "messages": [{"role": "user", "content": "hi"}],
                         "model": "grok-4.3", "reasoning_effort": "high"})],
            _backend()))
        checks.append(("chat bridge: reasoning_effort from frame reaches stream_response (B9)",
                       seen_eff.get("effort") == "high"))
    except Exception as exc:  # noqa: BLE001
        checks.append((f"chat bridge: effort scenario ran ({exc})", False))
    finally:
        rc.stream_response = orig_stream


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
