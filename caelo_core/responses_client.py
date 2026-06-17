"""Klient xAI **Responses API** (`POST /v1/responses`) — M10-B1/B2/B3.

Nowoczesny, jeden kanał czatu gotowy na **narzędzia serwerowe** (live search:
`web_search` / `x_search`), **wizję** i Q&A nad dokumentami. Zastępuje legacy
`chat/completions` (`api_manager.chat_completion_stream`), które NIE udźwignie
searcha: stare Live Search przez `search_parameters` zwraca od 12.01.2026
**410 Gone**, a samo `chat/completions` jest legacy.

ZASADY (CLAUDE.md / docs/PLAN_M10_CZAT.md — przeczytaj przed zmianą):
- Klient ŻYJE TU, NIE w root `api_manager.py` (nie restrukturyzujemy rdzenia repo).
  To jedyna „cienka warstwa endpoint/auth" — hedge na zmiany xAI, nie multi-provider.
- **SSE dekodowane JAWNIE jako UTF-8** (jak `chat_completion_stream`):
  `iter_lines(decode_unicode=False)` + `.decode("utf-8")`. `requests` dla
  `text/event-stream` potrafi zgadnąć ISO-8859-1 → mojibake polskich znaków.
- **Precedencja auth bez zmian**: `api_key_provider()` (OAuth → klucz → XAI_API_KEY),
  wstrzykiwany przez wołającego (jak `state.get_api_key`). Bearer tylko do api.x.ai.
- Strumień **zdarzeń typowanych** (Responses API, zgodne z OpenAI):
  `response.output_text.delta` (delta tekstu), `response.*_search_call.*`
  (aktywność narzędzi → wskaźnik „Searching…"), `response.completed`
  (usage + annotations = **cytowania**). Parser jest TOLERANCYJNY na kształt
  (różne warianty pól), bo wire-format xAI weryfikuje użytkownik na swojej maszynie.

Limity weryfikacji: realny `/v1/responses` jest za przechwytywaniem TLS w sandboxie
(jak cała reszta xAI) — kształt drutu potwierdza użytkownik z ważnym kluczem.
`api_smoke.py` mockuje udokumentowane zdarzenia, więc konwersja/parser/UTF-8/auth
są sprawdzone bez sieci (zero regresji w CI).
"""

from __future__ import annotations

import json
import logging
from typing import Callable, List, Optional

import requests  # type: ignore

import config  # type: ignore
from caelo_core import validation as V

log = logging.getLogger(__name__)

# Timeout całej tury Responses (sekundy) — pętla narzędzi serwerowych (search →
# doczytaj → odpowiedz) bywa dłuższa niż zwykły czat, ale nie nieograniczona (P1-4).
TIMEOUT_RESPONSES = 300


def _headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


# --- narzędzia serwerowe (live search) — M10-B2 ----------------------------------

def build_search_tools(
    mode: str = "auto",
    sources: Optional[List[str]] = None,
) -> Optional[List[dict]]:
    """Zbuduj listę narzędzi live-search dla żądania Responses.

    - `mode == "off"` → `None` (zero narzędzi: czysty czat, bez płatnego searcha).
    - `mode in {"on","auto"}` → narzędzia dla wybranych źródeł.
    - `sources`: podzbiór {"web","x","news"} (None = web + x). „news" idzie przez
      `web_search` (xAI nie ma osobnego narzędzia news — to filtr web).

    Trzymamy definicje MINIMALNE (`{"type": ...}`) — bez spekulatywnych pól
    (max_results/daty), które mogłyby dać 422 na realnym API; rozbudowa po
    weryfikacji wire-formatu (TODO w PLAN_M10)."""
    if mode == "off":
        return None
    sources = sources or ["web", "x"]
    tools: List[dict] = []
    if "web" in sources or "news" in sources:
        tools.append({"type": "web_search"})
    if "x" in sources:
        tools.append({"type": "x_search"})
    return tools or None


# --- konwersja wiadomości → `input` Responses ------------------------------------

def _text_part(role: str, text: str) -> dict:
    # Responses rozróżnia part wejściowy (user/system) od wyjściowego (assistant).
    return {"type": "output_text" if role == "assistant" else "input_text", "text": text}


def _image_part(url: str) -> dict:
    # Wizja (M10-B3): data-URI obrazu jako part wejściowy. xAI/OpenAI Responses
    # przyjmuje `image_url` jako string (data:... lub https URL).
    return {"type": "input_image", "image_url": url}


def _document_part(doc: dict) -> Optional[dict]:
    """Q&A nad dokumentem inline (M10-B4): blok `document` z send-to bus / composera
    (`{data:<data-URI>, mime, name}`) → part `input_file` Responses (file_data +
    filename). Zwraca None, gdy brak danych lub przekroczony cap rozmiaru (skip-with-log,
    by jeden zły załącznik nie wywracał całej tury)."""
    data = doc.get("data") or doc.get("file_data")
    if not data:
        return None
    try:
        V.validate_document_uri(data)
    except ValueError as exc:
        log.warning("Skipping document attachment: %s", exc)
        return None
    return {"type": "input_file", "filename": doc.get("name") or "document", "file_data": data}


def _image_url_from_part(p: dict) -> Optional[str]:
    """Wyciągnij URL obrazu z partu w formacie chat/completions, gdzie `image_url`
    bywa stringiem ALBO obiektem {"url": ...} (oba warianty w ekosystemie)."""
    iu = p.get("image_url")
    if isinstance(iu, dict):
        return iu.get("url")
    if isinstance(iu, str):
        return iu
    return None


def to_input(messages: list) -> list:
    """Konwersja wiadomości czatu (role + content `str` lub lista part-ów w
    formacie chat/completions) na `input` Responses API.

    Zachowuje **balans historii** (każda wiadomość = jeden item, kolejność ról
    bez zmian — kontrakt xAI). Asystent → `output_text`; user/system → `input_text`;
    obraz (`image_url`) → `input_image` (wizja, B3). Puste wiadomości pomijane."""
    items: list = []
    for m in messages or []:
        if not isinstance(m, dict):
            continue
        role = m.get("role", "user")
        content = m.get("content", "")
        parts: list = []
        if isinstance(content, str):
            if content:
                parts.append(_text_part(role, content))
        elif isinstance(content, list):
            for p in content:
                if not isinstance(p, dict):
                    continue
                ptype = p.get("type")
                if ptype == "text" and p.get("text"):
                    parts.append(_text_part(role, p["text"]))
                elif ptype == "image_url":
                    url = _image_url_from_part(p)
                    if url:
                        parts.append(_image_part(url))
                elif ptype == "document":
                    dpart = _document_part(p.get("document") or {})
                    if dpart:
                        parts.append(dpart)
                elif ptype in ("input_text", "output_text", "input_image", "input_file"):
                    # Już w formacie Responses (np. przekazane wprost) — zachowaj.
                    parts.append(p)
        if parts:
            items.append({"role": role, "content": parts})
    return items


# --- parsowanie zdarzeń strumienia -----------------------------------------------

def _classify_tool(etype: str) -> Optional[str]:
    """Nazwa narzędzia serwerowego z typu zdarzenia (np.
    'response.web_search_call.searching' → 'web_search'). None = nie-narzędziowe."""
    if "web_search" in etype:
        return "web_search"
    if "x_search" in etype:
        return "x_search"
    if "file_search" in etype:
        return "file_search"
    return None


def _tool_status(etype: str) -> str:
    """Faza narzędzia z sufiksu typu zdarzenia: in_progress / searching / completed."""
    last = etype.rsplit(".", 1)[-1]
    return last or "active"


def _event_query(obj: dict) -> Optional[str]:
    """Zapytanie searcha ze zdarzenia narzędzia — bywa na górze (`query`) albo w
    zagnieżdżonym `action`/`web_search`/`search` (różne warianty wire-formatu)."""
    q = obj.get("query")
    if q:
        return q
    for key in ("action", "web_search", "search"):
        nested = obj.get(key)
        if isinstance(nested, dict) and nested.get("query"):
            return nested["query"]
    return None


def _add_citation(citations: dict, url: Optional[str], title: Optional[str] = None) -> None:
    """Dedup cytowań po URL (https). Pierwszy tytuł wygrywa; pusty URL pomijany."""
    if not url or not isinstance(url, str):
        return
    if not url.startswith("http"):
        return
    if url not in citations:
        citations[url] = {"url": url, "title": title or ""}
    elif title and not citations[url].get("title"):
        citations[url]["title"] = title


def _collect_citations(obj, citations: dict) -> None:
    """Rekurencyjnie zbierz adnotacje `url_citation` (cytowania) z dowolnego
    fragmentu odpowiedzi — adnotacje siedzą na part-ach `output_text`, ale ich
    dokładne zagnieżdżenie różni się między wariantami API, więc skanujemy szeroko."""
    if isinstance(obj, dict):
        if obj.get("type") in ("url_citation", "citation") and (obj.get("url") or obj.get("uri")):
            _add_citation(citations, obj.get("url") or obj.get("uri"), obj.get("title"))
        for v in obj.values():
            _collect_citations(v, citations)
    elif isinstance(obj, list):
        for v in obj:
            _collect_citations(v, citations)


# --- narzędzia function-calling (M14-B2: MCP w czacie) ---------------------------

def _to_responses_function(defn: dict) -> dict:
    """Znormalizuj definicję narzędzia function-calling do FLAT formatu Responses API
    (`{"type":"function","name","description","parameters"}`). Przyjmuje też format
    chat/completions (zagnieżdżony pod `function`) — różnica między /responses a
    /chat/completions, którą tu domykamy, by `McpManager.tool_defs_for_responses`
    (format chat) działał w obu ścieżkach."""
    fn = defn.get("function") if isinstance(defn.get("function"), dict) else defn
    return {
        "type": "function",
        "name": fn.get("name"),
        "description": fn.get("description") or "",
        "parameters": fn.get("parameters") or {"type": "object"},
    }


def _function_calls_from_output(output) -> List[dict]:
    """Wyłuskaj item-y `function_call` z `response.output` (klient-side function calling).
    Każdy: {call_id, name, arguments(JSON-string)}. Tolerancyjny na warianty pól."""
    calls: List[dict] = []
    if isinstance(output, list):
        for item in output:
            if isinstance(item, dict) and item.get("type") == "function_call":
                calls.append({
                    "call_id": item.get("call_id") or item.get("id") or "",
                    "name": item.get("name") or "",
                    "arguments": item.get("arguments") or "{}",
                })
    return calls


def stream_response(
    messages: list,
    *,
    model: str,
    api_key_provider: Callable[[], str],
    temperature: Optional[float] = 0.7,
    reasoning_effort: Optional[str] = None,
    tools: Optional[List[dict]] = None,
    tool_choice: Optional[str] = None,
    on_delta: Optional[Callable[[str, str], None]] = None,
    on_tool: Optional[Callable[[dict], None]] = None,
    stop_flag: Optional[Callable[[], bool]] = None,
    base: Optional[str] = None,
    function_tools: Optional[List[dict]] = None,
    tool_handler: Optional[Callable[[str, dict], str]] = None,
    remote_tools: Optional[List[dict]] = None,
    max_tool_iters: int = 8,
) -> dict:
    """Strumieniuj odpowiedź xAI Responses API (z opcjonalną pętlą narzędzi MCP).

    Args:
        messages: historia w formacie chat (role + content str|parts). Stateless —
            cała historia idzie w żądaniu (jak legacy).
        model: id modelu (np. 'grok-4.3'). Wizja/file_search wymagają rodziny grok-4.
        api_key_provider: zwraca Bearer (OAuth → klucz → XAI_API_KEY).
        reasoning_effort: M19-B9 — 'low'/'medium'/'high' dla modeli rozumujących
            (→ `reasoning.effort`); None/niepoprawne = pole pominięte (czyste żądanie).
        tools: narzędzia serwerowe (z `build_search_tools`); None = czysty czat.
        on_delta(delta, full): callback przyrostu tekstu (jak `chat_completion_stream`).
        on_tool(ev): callback aktywności narzędzia, ev = {"tool","status","query"}.
        stop_flag(): True przerywa odbiór (Stop z UI).
        function_tools: M14-B2 — definicje narzędzi MCP (function-calling). Gdy model
            je wywoła, wykonuje je `tool_handler` (klient-side), a wynik wraca jako
            `function_call_output` w kolejnej turze (pętla do `max_tool_iters`).
        tool_handler(name, args) -> str: egzekutor narzędzia MCP (z bramką po stronie
            wołającego). None → narzędzia function nieobsługiwane (pętla się nie kręci).
        remote_tools: M14-B3 — bloki native remote MCP (`{type:'mcp',...}`) doklejane
            do `tools` (wykonanie po stronie xAI, bez lokalnej bramki).

    Returns:
        {"text", "citations":[{"url","title"}...], "usage":{...},
         "tool_calls": <serwerowe wywołania>, "function_tool_calls": <MCP wywołania>}.
    """
    api_key = api_key_provider()
    base = base or config.API_BASE

    server_tools = list(tools or []) + list(remote_tools or [])
    flat_fns = [_to_responses_function(d) for d in (function_tools or [])]
    all_tools = server_tools + flat_fns

    input_items = to_input(messages)

    parts: List[str] = []
    citations: dict = {}
    usage: dict = {}
    tool_call_count = 0
    fn_call_count = 0
    seen_tool_keys: set = set()

    def _run_turn(turn_input: list, *, with_tool_choice: bool) -> List[dict]:
        """Jedna runda streamingu. Zwraca surowe `output` (do dołączenia w pętli
        narzędzi). Aktualizuje akumulatory tekstu/cytowań/usage/liczników (domknięcie)."""
        nonlocal tool_call_count, usage
        payload: dict = {"model": model, "input": turn_input, "stream": True}
        if temperature is not None:
            payload["temperature"] = temperature
        # M19-B9: reasoning_effort → `reasoning.effort`, ale jest ZALEŻNY OD MODELU
        # (grok-4.3 wspiera none/low/medium/high; grok-4 / grok-build-0.1 zwracają 4xx, gdy
        # pole jest obecne — docs.x.ai). Wyślij tylko gdy poprawny i — gdy serwer odrzuci
        # (400/422) — PONÓW raz bez niego (best-effort: tura nie pada na modelu bez wsparcia).
        eff = V.normalize_effort(reasoning_effort)
        if all_tools:
            payload["tools"] = all_tools
            if tool_choice and with_tool_choice:
                payload["tool_choice"] = tool_choice
        output_items: List[dict] = []

        def _open(send_effort: bool):
            body = dict(payload)
            if send_effort and eff:
                body["reasoning"] = {"effort": eff}
            return requests.post(f"{base}/responses", headers=_headers(api_key), json=body,
                                 stream=True, timeout=TIMEOUT_RESPONSES)

        r = _open(bool(eff))
        if eff and getattr(r, "status_code", 200) in (400, 422):
            log.info("model %s rejected reasoning.effort=%s (HTTP %s) — retrying without it",
                     model, eff, getattr(r, "status_code", "?"))
            r.close()
            r = _open(False)
        with r:
            r.raise_for_status()
            for raw in r.iter_lines(decode_unicode=False):
                if stop_flag and stop_flag():
                    break
                if not raw:
                    continue
                line = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else raw
                # SSE: linia `event: <typ>` jest redundantna (typ jest też w data.type).
                if line.startswith("event:"):
                    continue
                if line.startswith("data:"):
                    line = line[5:].strip()
                if not line:
                    continue
                if line == "[DONE]":
                    break
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if not isinstance(obj, dict):
                    continue

                etype = obj.get("type") or ""

                # 1) przyrost tekstu
                if etype.endswith("output_text.delta") or etype == "response.output_text.delta":
                    delta = obj.get("delta")
                    if isinstance(delta, dict):  # niektóre warianty pakują w {"text": ...}
                        delta = delta.get("text")
                    if delta:
                        parts.append(delta)
                        if on_delta:
                            on_delta(delta, "".join(parts))
                    continue

                # 2) adnotacja-cytowanie dorzucana w trakcie
                if "annotation" in etype:
                    _collect_citations(obj.get("annotation") or obj, citations)
                    continue

                # 3) aktywność narzędzia serwerowego (live search)
                tool = _classify_tool(etype)
                if tool is not None:
                    status = _tool_status(etype)
                    base_key = obj.get("item_id") or obj.get("id") or tool
                    if base_key not in seen_tool_keys:
                        seen_tool_keys.add(base_key)
                        tool_call_count += 1
                    if on_tool:
                        on_tool({"tool": tool, "status": status, "query": _event_query(obj)})
                    _collect_citations(obj, citations)
                    continue

                # 4) zakończenie — pełna odpowiedź: usage + cytowania + tekst + output
                if etype.endswith("completed") or etype.endswith("response.done") \
                        or etype == "response.completed":
                    resp = obj.get("response") or obj
                    u = resp.get("usage")
                    if isinstance(u, dict):
                        # S31-i: SUMUJ pola liczbowe przez tury pętli narzędzi — wcześniej
                        # `usage = u` nadpisywało, więc licznik tokenów przy tool-callach był
                        # zaniżony do ostatniej tury. Niezliczbowe (np. model id) = ostatnie.
                        for k, v in u.items():
                            usage[k] = (usage.get(k, 0) + v) if isinstance(v, (int, float)) else v
                    out = resp.get("output")
                    if isinstance(out, list):
                        output_items = out
                    _collect_citations(out, citations)
                    if not parts:
                        txt = _text_from_output(out)
                        if txt:
                            parts.append(txt)
                            if on_delta:
                                on_delta(txt, txt)
                    continue

                # 5) błąd zgłoszony w strumieniu
                if etype.endswith("error") or obj.get("error"):
                    err = obj.get("error") or obj.get("message") or "stream error"
                    raise RuntimeError(str(err)[:500])
        return output_items

    # Pętla narzędzi MCP (klient-side function calling). Bez `function_tools`/`tool_handler`
    # wykonuje się DOKŁADNIE raz — zachowanie identyczne jak przed M14 (czysty czat/search).
    n_iters = max(1, max_tool_iters)
    for _iter in range(n_iters):
        output_items = _run_turn(input_items, with_tool_choice=(_iter == 0))
        calls = _function_calls_from_output(output_items) if (function_tools and tool_handler) else []
        if not calls:
            break
        if stop_flag and stop_flag():
            break
        # S31-i: na OSTATNIEJ iteracji NIE wykonuj narzędzi — ich wyniki nie wróciłyby już
        # do modelu (brak kolejnego _run_turn), a tool_handler ma SKUTKI UBOCZNE (np.
        # wygenerowany obraz / mutujące MCP). Przerwij przed egzekucją „w próżnię".
        if _iter == n_iters - 1:
            break
        # Dołącz output modelu (item-y function_call) + nasze wyniki — kontrakt Responses
        # (stateless): kolejne żądanie niesie pełen kontekst tury narzędziowej.
        input_items = list(input_items) + list(output_items)
        for call in calls:
            name = call["name"]
            try:
                args = json.loads(call["arguments"]) if call["arguments"] else {}
                if not isinstance(args, dict):
                    args = {}
            except Exception:
                args = {}
            if on_tool:
                on_tool({"tool": name, "status": "calling", "query": None})
            try:
                result = tool_handler(name, args)
            except Exception as exc:  # noqa: BLE001
                result = f"Error: tool failed: {exc}"
            fn_call_count += 1
            if on_tool:
                on_tool({"tool": name, "status": "completed", "query": None})
            input_items.append({
                "type": "function_call_output",
                "call_id": call["call_id"],
                "output": str(result),
            })

    return {
        "text": "".join(parts),
        "citations": list(citations.values()),
        "usage": usage,
        "tool_calls": tool_call_count,
        "function_tool_calls": fn_call_count,
    }


def _text_from_output(output) -> str:
    """Złóż tekst z `response.output` (lista item-ów; part-y `output_text`).
    Używane jako fallback, gdy strumień nie dał deltas (np. tryb nie-przyrostowy)."""
    if not isinstance(output, list):
        return ""
    chunks: List[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") in ("output_text", "text"):
                    t = part.get("text")
                    if t:
                        chunks.append(t)
        elif isinstance(content, str):
            chunks.append(content)
    return "".join(chunks)
