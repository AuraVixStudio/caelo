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
                elif ptype in ("input_text", "output_text", "input_image"):
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


def stream_response(
    messages: list,
    *,
    model: str,
    api_key_provider: Callable[[], str],
    temperature: Optional[float] = 0.7,
    tools: Optional[List[dict]] = None,
    tool_choice: Optional[str] = None,
    on_delta: Optional[Callable[[str, str], None]] = None,
    on_tool: Optional[Callable[[dict], None]] = None,
    stop_flag: Optional[Callable[[], bool]] = None,
    base: Optional[str] = None,
) -> dict:
    """Strumieniuj odpowiedź xAI Responses API.

    Args:
        messages: historia w formacie chat (role + content str|parts). Stateless —
            cała historia idzie w żądaniu (jak legacy).
        model: id modelu (np. 'grok-4.3'). Wizja/file_search wymagają rodziny grok-4.
        api_key_provider: zwraca Bearer (OAuth → klucz → XAI_API_KEY).
        tools: narzędzia serwerowe (z `build_search_tools`); None = czysty czat.
        on_delta(delta, full): callback przyrostu tekstu (jak `chat_completion_stream`).
        on_tool(ev): callback aktywności narzędzia, ev = {"tool","status","query"}.
        stop_flag(): True przerywa odbiór (Stop z UI).

    Returns:
        {"text": <pełna odpowiedź>, "citations": [{"url","title"}...],
         "usage": {...}, "tool_calls": <liczba wywołań narzędzi>}.
    """
    api_key = api_key_provider()
    payload: dict = {
        "model": model,
        "input": to_input(messages),
        "stream": True,
    }
    if temperature is not None:
        payload["temperature"] = temperature
    if tools:
        payload["tools"] = tools
        if tool_choice:
            payload["tool_choice"] = tool_choice

    parts: List[str] = []
    citations: dict = {}
    usage: dict = {}
    tool_call_count = 0
    seen_tool_keys: set = set()

    base = base or config.API_BASE
    with requests.post(
        f"{base}/responses", headers=_headers(api_key), json=payload,
        stream=True, timeout=TIMEOUT_RESPONSES,
    ) as r:
        r.raise_for_status()
        for raw in r.iter_lines(decode_unicode=False):
            if stop_flag and stop_flag():
                break
            if not raw:
                continue
            line = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else raw
            # SSE: linia `event: <typ>` jest redundantna (typ jest też w data.type) —
            # pomijamy ją; właściwy ładunek jest w `data: {...}`.
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
                # licz UNIKALNE wywołania (po id item-u) — strumień wysyła kilka
                # faz na jedno wywołanie (in_progress→searching→completed).
                base_key = obj.get("item_id") or obj.get("id") or tool
                if base_key not in seen_tool_keys:
                    seen_tool_keys.add(base_key)
                    tool_call_count += 1
                if on_tool:
                    on_tool({"tool": tool, "status": status, "query": _event_query(obj)})
                # wyniki narzędzia mogą nieść URL-e (cytowania)
                _collect_citations(obj, citations)
                continue

            # 4) zakończenie — pełna odpowiedź: usage + adnotacje (cytowania) + tekst
            if etype.endswith("completed") or etype.endswith("response.done") \
                    or etype == "response.completed":
                resp = obj.get("response") or obj
                u = resp.get("usage")
                if isinstance(u, dict):
                    usage = u
                _collect_citations(resp.get("output"), citations)
                # fallback: gdyby deltas nie przyszły, weź zebrany tekst z output
                if not parts:
                    txt = _text_from_output(resp.get("output"))
                    if txt:
                        parts.append(txt)
                        if on_delta:
                            on_delta(txt, txt)
                continue

            # 5) błąd zgłoszony w strumieniu
            if etype.endswith("error") or obj.get("error"):
                err = obj.get("error") or obj.get("message") or "stream error"
                raise RuntimeError(str(err)[:500])

    return {
        "text": "".join(parts),
        "citations": list(citations.values()),
        "usage": usage,
        "tool_calls": tool_call_count,
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
