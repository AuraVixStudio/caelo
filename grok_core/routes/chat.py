"""WebSocket czatu ze streamingiem (SSE -> WS) — na **Responses API** (M10).

Protokół (JSON tekstowe ramki):
  klient -> serwer:
    {"type":"chat","messages":[...],"model":"...","temperature":0.7,
     "system_prompt":"...","search_mode":"auto|on|off","sources":["web","x"]}
    {"type":"stop"}                      # przerwij bieżące generowanie
  serwer -> klient:
    {"type":"delta","delta":"<przyrost treści>"}   # przyrostowo — klient skleja
    {"type":"tool_call","tool":"web_search|x_search","status":"...","query":"..."}
    {"type":"citations","citations":[{"url","title"}, ...]}   # źródła live-searcha
    {"type":"usage","usage":{...},"tool_calls":<n>}           # koszt (BYO-key, B6)
    {"type":"done","full":"<pełna odpowiedź>"}
    {"type":"error","error":"..."}

Rdzeń czatu idzie przez **`responses_client.stream_response`** (M10-B1): jeden
nowoczesny kanał gotowy na narzędzia serwerowe (live search — B2) i wizję (B3).
Stare `chat/completions` zostaje TYLKO jako fallback dla czystego czatu (bez
narzędzi), gdy Responses zawiedzie przed pierwszą deltą — `search_parameters` jest
i tak wycofane (410 Gone). Most streamingu jak dotąd: blokujące wywołanie biegnie
w wątku, delty/zdarzenia trafiają do `WsStream` (ograniczona kolejka + backpressure,
P1-3/P0-9), a {"type":"stop"} ustawia per-request stop_flag w trakcie streamu.
UTF-8 zachowane jawnie (responses_client + APIManager).

Autoryzacja: token w query (`?token=...`) — przeglądarkowy WebSocket nie pozwala
ustawić nagłówka Authorization.
"""

from __future__ import annotations

import json
import threading

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import config  # type: ignore

from grok_core import responses_client
from grok_core.routes._ws import WsStream
from grok_core.state import ws_authorized

router = APIRouter()


def _has_rich_input(messages) -> bool:
    """True, jeśli którakolwiek wiadomość niesie obraz (`image_url`) lub dokument
    (`document`) — oba wymagają rodziny grok-4 (wizja M10-B3 / dokument M10-B4)."""
    for m in messages or []:
        content = m.get("content") if isinstance(m, dict) else None
        if isinstance(content, list):
            for p in content:
                if isinstance(p, dict) and p.get("type") in ("image_url", "document"):
                    return True
    return False


def _is_grok4(model: str) -> bool:
    """Rodzina grok-4 (wizja + dokumenty + file_search wymagają jej — M10-B3/B4).
    grok-3 i grok-build-0.1 są text-only z perspektywy wizji/dokumentów."""
    return (model or "").lower().startswith("grok-4")


def _last_user_text(messages) -> str:
    """Ostatnia wiadomość użytkownika jako czysty tekst (string albo części
    multimodalne content[]). Do zindeksowania promptu w historii huba (M9-B2)."""
    for m in reversed(messages or []):
        if not isinstance(m, dict) or m.get("role") != "user":
            continue
        content = m.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return " ".join(
                p.get("text", "") for p in content
                if isinstance(p, dict) and p.get("type") == "text" and p.get("text")
            )
        return ""
    return ""


@router.websocket("/chat/stream")
async def chat_stream(ws: WebSocket) -> None:
    if not ws_authorized(ws):  # P0-8: fail-closed token + Origin
        await ws.close(code=1008)  # policy violation (przed accept -> odmowa handshake)
        return

    await ws.accept()
    backend = getattr(ws.app.state, "backend", None)
    if backend is None:
        await ws.send_json({"type": "error", "error": "Backend not initialized"})
        await ws.close()
        return

    current: dict = {"thread": None, "stop": None}  # P1-3: single-flight worker

    async with WsStream(ws) as stream:

        def start_worker(messages, model: str, temperature: float,
                         search_mode: str, sources) -> None:
            stop = threading.Event()        # P1-3: stop_event PER-REQUEST
            current["stop"] = stop
            got = {"any": False}
            # M10-B5: wiedza projektu NIE idzie przez serwerowy file_search (xAI go nie
            # ma — 404). Dokumenty projektu user dołącza do wiadomości na żądanie
            # („Attach all"), więc trafiają tu już jako bloki `document` w `messages`.
            tools = responses_client.build_search_tools(search_mode, sources)
            # M14-B2: narzędzia MCP (lokalne) jako function-calling + (B3) native remote
            # MCP. Czat NIE ma interaktywnego modala zatwierdzeń (to ma agent — F2), więc
            # polityka czatu: READONLY działa; MUTUJĄCE tylko gdy WCZEŚNIEJ dopuszczone na
            # współdzielonej allowliście („Always allow" z agenta), inaczej odmowa z
            # czytelnym komunikatem. Dane lokalne nie wychodzą poza sidecar.
            mcp_fn_tools = backend.mcp.tool_defs_for_responses()
            remote_tools = backend.mcp.remote_tool_blocks()
            has_tools = bool(tools or mcp_fn_tools or remote_tools)

            def mcp_tool_handler(name: str, args: dict) -> str:
                mgr = backend.mcp
                if not mgr.is_mcp_tool(name):
                    return f"Error: unknown tool {name}"
                if mgr.is_mutating(name) and backend.permissions.needs_approval_key(f"mcp:{name}"):
                    return (f"Error: '{name}' changes state and is not approved for chat. "
                            "Approve it in the Code agent (\"Always allow\") or MCP settings, then retry.")
                try:
                    return mgr.call_tool(name, args)
                except Exception as exc:  # noqa: BLE001
                    return f"Error: MCP tool failed: {exc}"

            def on_delta(delta: str, _full: str) -> None:
                got["any"] = True
                # P1-3: wysyłaj PRZYROST (delta), nie skumulowane full (było O(n²) pasma).
                if not stream.emit({"type": "delta", "delta": delta}):
                    stop.set()  # konsument zniknął → przerwij streaming z xAI

            def on_tool(ev: dict) -> None:
                # M10-F1: aktywność narzędzia serwerowego (live search) → wskaźnik UI.
                if not stream.emit({"type": "tool_call", **ev}):
                    stop.set()

            def worker() -> None:
                try:
                    try:
                        result = responses_client.stream_response(
                            messages, model=model,
                            api_key_provider=backend.get_api_key,
                            temperature=temperature, tools=tools,
                            # "on" wymusza search; "auto" zostawia decyzję modelowi.
                            tool_choice="required" if search_mode == "on" else None,
                            on_delta=on_delta, on_tool=on_tool, stop_flag=stop.is_set,
                            # M14-B2/B3: narzędzia MCP lokalne (function) + remote (xAI).
                            function_tools=mcp_fn_tools or None,
                            tool_handler=mcp_tool_handler if mcp_fn_tools else None,
                            remote_tools=remote_tools or None,
                        )
                        full = result["text"]
                    except Exception:
                        if got["any"] or has_tools:
                            # Już streamowaliśmy ALBO to tura z narzędziami (search/MCP
                            # nie istnieją w legacy chat/completions) → bez cichego
                            # fallbacku; zgłoś błąd.
                            raise
                        # Czysty czat: Responses zawiodło przed pierwszą deltą →
                        # spadnij na legacy chat/completions (wciąż działa).
                        full = backend.api.chat_completion_stream(
                            messages, model=model, temperature=temperature,
                            on_delta=on_delta, stop_flag=stop.is_set,
                        )
                        result = {"text": full, "citations": [], "usage": {}, "tool_calls": 0}
                    # M10-F2/F6: źródła + koszt po zakończeniu streamu (przed 'done').
                    if result.get("citations"):
                        stream.emit({"type": "citations", "citations": result["citations"]})
                    if result.get("usage") or result.get("tool_calls"):
                        stream.emit({"type": "usage", "usage": result.get("usage") or {},
                                     "tool_calls": result.get("tool_calls", 0)})
                    stream.emit({"type": "done", "full": full})
                    # M9-B2: zapisz turę do wspólnej historii huba (po zakończeniu
                    # strumienia, poza gorącą pętlą; błędy połykane w record_event).
                    # Tekst = odpowiedź; prompt usera + koszt/źródła w meta (FTS).
                    prompt = _last_user_text(messages)
                    if full or prompt:
                        backend.record_event(
                            mode="chat", text=full or "",
                            meta={"prompt": prompt, "model": model,
                                  "search_mode": search_mode,
                                  "tool_calls": result.get("tool_calls", 0),
                                  "usage": result.get("usage") or {},
                                  "citations": [c.get("url") for c in result.get("citations", [])]},
                        )
                except Exception as exc:  # noqa: BLE001
                    stream.emit({"type": "error", "error": str(exc)})

            t = threading.Thread(target=worker, daemon=True)
            current["thread"] = t
            stream.track(t)   # P0-9: dołączony przy zamykaniu (bez pracy po rozłączeniu)
            t.start()

        def _busy() -> bool:
            t = current["thread"]
            return t is not None and t.is_alive()

        try:
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                mtype = msg.get("type")
                if mtype == "stop":
                    if current["stop"] is not None:
                        current["stop"].set()   # P1-3: zatrzymaj bieżący request (nie czyść!)
                elif mtype == "chat":
                    if _busy():
                        # P1-3: single-flight — nie startuj drugiego workera na tej samej kolejce.
                        await stream.send({"type": "error",
                                           "error": "A response is already streaming; send 'stop' first."})
                        continue
                    messages = list(msg.get("messages") or [])
                    system_prompt = (msg.get("system_prompt") or "").strip()
                    if system_prompt:
                        messages = [{"role": "system", "content": system_prompt}] + messages
                    model = msg.get("model") or backend.read_settings().get(
                        "chat_model"
                    ) or config.DEFAULT_CHAT_MODEL
                    try:
                        temperature = float(msg.get("temperature", 0.7))
                    except (TypeError, ValueError):
                        temperature = 0.7  # złe temperature nie może wywrócić pętli odbioru (por. P1-8)
                    # M10-B2: tryb live-searcha (auto/on/off) + źródła; domyślnie OFF,
                    # by istniejący klient (bez tych pól) zachował się jak dotąd i nie
                    # ponosił kosztu narzędzi serwerowych bez zgody (BYO-key).
                    search_mode = (msg.get("search_mode") or "off").lower()
                    if search_mode not in ("auto", "on", "off"):
                        search_mode = "off"
                    sources = msg.get("sources") or None
                    # M10-B3/B4: wizja i dokumenty wymagają rodziny grok-4 — czytelny
                    # komunikat zamiast niejasnego błędu API na modelu text-only.
                    if _has_rich_input(messages) and not _is_grok4(model):
                        await stream.send({"type": "error", "error": (
                            f"Image and document input require a grok-4 model. The selected "
                            f"model '{model}' is text-only — switch models or remove the attachment.")})
                        continue
                    start_worker(messages, model, temperature, search_mode, sources)
        except WebSocketDisconnect:
            pass
        finally:
            # P1-3: zatrzymaj bieżący request; WsStream.aclose() dołączy workera
            # (≤5 s) i domknie sender — bez czytania z xAI po rozłączeniu.
            if current["stop"] is not None:
                current["stop"].set()
