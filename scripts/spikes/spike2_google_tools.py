"""SPIKE-2 (blokujący dla ADR-8 i Fazy 6) — tool-calling Google vs kontrakt xAI.

Odpowiada na pytania, od których zależy adapter narzędzi agenta:

  P1. Czy `functionCall` wraca i w jakim kształcie?
  P2. Czy wywołanie ma identyfikator i czy `functionResponse` musi go powtórzyć?
  P3. Czy model zwraca wiele wywołań w jednej turze i jak zachowuje kolejność?
  P4. Czy pełna runda przez `functionResponse` domyka się poprawnie z zachowaniem
      oryginalnych części modelu i `thoughtSignature`?
  P5. Jak wywołania narzędzi przychodzą w streamingu, w tym przy włączonym
      `streamFunctionCallArguments`?

Koszt: kilka tanich wywołań tekstowych na modelu Flash. Bez generacji mediów.

Podstawowa ścieżka projektu — Google Cloud / ADC:
    gcloud auth application-default login
    caelo_core/.venv/Scripts/python.exe scripts/spikes/spike2_google_tools.py \
        --gcp-project TWOJ_PROJEKT --gcp-location global

Alternatywnie przez AI Studio:
    $env:GEMINI_API_KEY = "..."
    caelo_core/.venv/Scripts/python.exe scripts/spikes/spike2_google_tools.py
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (  # noqa: E402
    API_VERSION,
    BASE,
    SpikeError,
    api_key,
    banner,
    dump,
    fail,
    gcloud_access_token,
    headers,
    ok,
    redact,
    request,
    vertex_request,
    vertex_url,
)

AI_STUDIO_MODEL = "gemini-flash-latest"
GCP_MODEL = "gemini-3.5-flash"
PROMPT = "What is the weather AND the current time in Warsaw? Call both tools before answering."

# Dwa narzędzia bez skutków ubocznych. Dwa, bo P3 wymaga sprawdzenia równoległości.
TOOLS = [
    {
        "functionDeclarations": [
            {
                "name": "get_weather",
                "description": "Get the current weather for a city.",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string", "description": "City name"}},
                    "required": ["city"],
                },
            },
            {
                "name": "get_time",
                "description": "Get the current local time for a city.",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string", "description": "City name"}},
                    "required": ["city"],
                },
            },
        ]
    }
]


def _generate(
    credential: str,
    model: str,
    body: dict,
    *,
    gcp_project: str | None,
    gcp_location: str,
) -> dict:
    if gcp_project:
        return vertex_request(
            "POST",
            gcp_project,
            gcp_location,
            f"publishers/google/models/{model}:generateContent",
            credential,
            body=body,
            timeout=180,
            api_version="v1",
        )
    return request("POST", f"models/{model}:generateContent", credential, body=body, timeout=180)


def extract_calls(response: dict) -> tuple[list[dict], dict | None]:
    """Wyciągnij functionCall, zachowując kolejność i pełną turę modelu."""
    calls: list[dict] = []
    model_content = None
    for cand in response.get("candidates", []) or []:
        content = cand.get("content") or {}
        if model_content is None and content.get("parts"):
            model_content = content
        for idx, part in enumerate(content.get("parts") or []):
            fc = part.get("functionCall") or part.get("function_call")
            if not isinstance(fc, dict):
                continue
            signature = part.get("thoughtSignature") or part.get("thought_signature")
            calls.append({
                "part_index": idx,
                "name": fc.get("name"),
                "args": fc.get("args") or {},
                "id": fc.get("id"),
                "raw_keys": sorted(fc.keys()),
                "part_keys": sorted(part.keys()),
                "has_thought_signature": bool(signature),
            })
    return calls, model_content


def q1_q2_q3(
    credential: str,
    model: str,
    *,
    gcp_project: str | None,
    gcp_location: str,
) -> tuple[bool, list[dict], dict | None]:
    banner("P1–P3 · Kształt functionCall, identyfikatory, równoległość")
    body = {
        "contents": [{"role": "user", "parts": [{"text": PROMPT}]}],
        "tools": TOOLS,
        "toolConfig": {"functionCallingConfig": {"mode": "AUTO"}},
    }
    data = _generate(
        credential,
        model,
        body,
        gcp_project=gcp_project,
        gcp_location=gcp_location,
    )
    dump("05_tools_call_gcp" if gcp_project else "05_tools_call", redact(data))

    calls, model_content = extract_calls(data)
    if not calls or not model_content:
        fail("model nie wywołał żadnego narzędzia — sprawdź 05_tools_call*.json")
        return False, [], None

    ok(f"P1: otrzymano {len(calls)} wywołań")
    for call in calls:
        print(
            f"      [{call['part_index']}] {call['name']}"
            f"({json.dumps(call['args'], ensure_ascii=False)}) "
            f"id={call['id']!r} podpis={call['has_thought_signature']} "
            f"pola={call['raw_keys']}"
        )

    ids = [call["id"] for call in calls]
    identifiers_ok = True
    if all(isinstance(call_id, str) and call_id for call_id in ids):
        ok("P2: każde functionCall ma `id`; functionResponse musi je powtórzyć")
    elif any(ids):
        fail("P2: tylko część wywołań ma `id` — potrzebny tolerancyjny adapter")
        identifiers_ok = False
    else:
        ok("P2: brak `id` w tej wersji modelu — adapter musi umieć je syntezować")

    if len(calls) > 1:
        ok(f"P3: równoległe wywołania działają; kolejność części = {[c['part_index'] for c in calls]}")
    else:
        fail("P3: model zwrócił tylko jedno wywołanie mimo jawnej prośby o oba")
        return False, calls, model_content
    return identifiers_ok, calls, model_content


def q4(
    credential: str,
    model: str,
    calls: list[dict],
    model_content: dict | None,
    *,
    gcp_project: str | None,
    gcp_location: str,
) -> bool:
    banner("P4 · Runda powrotna przez functionResponse")
    if not calls or not model_content:
        return False

    # Wysyłamy pełną turę modelu dokładnie tak, jak ją zwróciło API. To zachowuje
    # pozycję `thoughtSignature`, której modele Gemini 3.x wymagają w kolejnej turze.
    response_parts = []
    for call in calls:
        payload: dict[str, Any] = {"city": (call["args"] or {}).get("city", "Warsaw")}
        payload.update(
            {"weather": "12C, light rain"}
            if call["name"] == "get_weather"
            else {"time": "14:30"}
        )
        function_response: dict[str, Any] = {
            "name": call["name"],
            "response": {"output": payload},
        }
        if call.get("id"):
            function_response["id"] = call["id"]
        response_parts.append({"functionResponse": function_response})

    body = {
        "contents": [
            {"role": "user", "parts": [{"text": PROMPT}]},
            model_content,
            {"role": "user", "parts": response_parts},
        ],
        "tools": TOOLS,
        "toolConfig": {"functionCallingConfig": {"mode": "AUTO"}},
    }
    data = _generate(
        credential,
        model,
        body,
        gcp_project=gcp_project,
        gcp_location=gcp_location,
    )
    dump("06_tools_roundtrip_gcp" if gcp_project else "06_tools_roundtrip", redact(data))

    text = ""
    for cand in data.get("candidates", []) or []:
        for part in (cand.get("content") or {}).get("parts") or []:
            text += part.get("text") or ""
    if text.strip():
        ok("P4: runda powrotna domyka się — model odpowiedział tekstem")
        print(f"      „{text.strip()[:240]}”")
        return True
    fail("P4: brak tekstu w odpowiedzi — sprawdź 06_tools_roundtrip*.json")
    return False


def _stream_target(
    credential: str,
    model: str,
    *,
    gcp_project: str | None,
    gcp_location: str,
) -> tuple[str, dict]:
    if gcp_project:
        url = vertex_url(
            gcp_project,
            gcp_location,
            f"publishers/google/models/{model}:streamGenerateContent",
            api_version="v1",
        )
        return url, {
            "Authorization": f"Bearer {credential}",
            "Content-Type": "application/json",
        }
    return f"{BASE}/{API_VERSION}/models/{model}:streamGenerateContent", headers(credential)


def assemble_streamed_call(call_chunks: list[dict]) -> dict:
    """Złóż prosty functionCall z przyrostowych `partialArgs`.

    Spike używa płaskiego schematu argumentów. Produkcyjny adapter musi rozszerzyć
    tę samą zasadę na pełne JSONPath, w tym zagnieżdżone obiekty i tablice.
    """
    assembled: dict[str, Any] = {"name": None, "id": None, "args": {}}
    for call in call_chunks:
        if call.get("name"):
            assembled["name"] = call["name"]
        if call.get("id"):
            assembled["id"] = call["id"]
        if isinstance(call.get("args"), dict):
            assembled["args"].update(call["args"])
        for partial in call.get("partialArgs") or call.get("partial_args") or []:
            path = str(partial.get("jsonPath") or partial.get("json_path") or "")
            match = re.fullmatch(r"\$\.([A-Za-z_][A-Za-z0-9_]*)", path)
            if not match:
                continue
            key = match.group(1)
            if "stringValue" in partial:
                assembled["args"][key] = str(assembled["args"].get(key, "")) + str(
                    partial["stringValue"]
                )
            elif "numberValue" in partial:
                assembled["args"][key] = partial["numberValue"]
            elif "boolValue" in partial:
                assembled["args"][key] = partial["boolValue"]
            elif "nullValue" in partial:
                assembled["args"][key] = None
    return assembled


def q5(
    credential: str,
    model: str,
    *,
    gcp_project: str | None,
    gcp_location: str,
) -> bool:
    banner("P5 · STREAMING functionCall i argumentów")
    url, request_headers = _stream_target(
        credential,
        model,
        gcp_project=gcp_project,
        gcp_location=gcp_location,
    )
    body = {
        "contents": [{
            "role": "user",
            "parts": [{"text": "What is the weather in Warsaw? Use the tool."}],
        }],
        "tools": TOOLS,
        "toolConfig": {
            "functionCallingConfig": {
                "mode": "AUTO",
                "streamFunctionCallArguments": True,
            }
        },
    }
    print(f"  POST {url}?alt=sse")
    events: list[dict] = []
    call_chunks: list[dict] = []
    saw_text = False
    try:
        with requests.post(
            url,
            headers=request_headers,
            json=body,
            params={"alt": "sse"},
            stream=True,
            timeout=180,
        ) as response:
            if response.status_code >= 400:
                fail(f"HTTP {response.status_code}: {response.text[:600]}")
                return False
            # Jawne UTF-8: `requests` potrafi błędnie wybrać ISO-8859-1 dla SSE.
            for raw in response.iter_lines(decode_unicode=False):
                if not raw:
                    continue
                line = raw.decode("utf-8")
                if not line.startswith("data:"):
                    continue
                chunk = line[5:].strip()
                if chunk in ("", "[DONE]"):
                    continue
                try:
                    obj = json.loads(chunk)
                except ValueError:
                    continue
                events.append(obj)
                for cand in obj.get("candidates", []) or []:
                    for part in (cand.get("content") or {}).get("parts") or []:
                        function_call = part.get("functionCall") or part.get("function_call")
                        if isinstance(function_call, dict):
                            call_chunks.append(function_call)
                        if part.get("text"):
                            saw_text = True
    except requests.RequestException as exc:
        fail(f"streaming padł: {exc}")
        return False

    dump("07_tools_stream_gcp" if gcp_project else "07_tools_stream", redact(events))
    partial_count = sum(bool(call.get("partialArgs") or call.get("partial_args")) for call in call_chunks)
    complete_count = sum(isinstance(call.get("args"), dict) for call in call_chunks)
    continuation_count = sum(bool(call.get("willContinue") or call.get("will_continue")) for call in call_chunks)
    if not call_chunks:
        fail(f"P5: odebrano {len(events)} zdarzeń SSE, ale bez functionCall")
        return False
    assembled = assemble_streamed_call(call_chunks)
    if not assembled.get("name") or not assembled.get("id") or not assembled.get("args"):
        fail(f"P5: nie udało się złożyć kompletnego wywołania z fragmentów: {assembled}")
        return False
    ok(
        f"P5: {len(events)} zdarzeń SSE, {len(call_chunks)} fragmentów functionCall; "
        f"partialArgs={partial_count}, args={complete_count}, willContinue={continuation_count}, "
        f"tekst={saw_text}"
    )
    ok(f"P5: złożono {assembled['name']}({json.dumps(assembled['args'], ensure_ascii=False)}) id={assembled['id']}")
    if partial_count:
        print("      Argumenty są przesyłane przyrostowo — adapter musi składać partialArgs po JSONPath.")
    else:
        print("      functionCall przyszedł jako gotowa część mimo włączonego streamingu argumentów.")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="SPIKE-2 — tool-calling Google (ADR-8)")
    parser.add_argument("--skip-stream", action="store_true", help="pomiń test streamingu")
    parser.add_argument("--gcp-project", help="projekt Google Cloud; włącza Vertex AI + ADC")
    parser.add_argument("--gcp-location", default="global", help="lokalizacja GCP (domyślnie: global)")
    parser.add_argument("--model", help="jawny identyfikator modelu testowego")
    args = parser.parse_args()

    use_gcp = bool(args.gcp_project)
    model = args.model or (GCP_MODEL if use_gcp else AI_STUDIO_MODEL)
    try:
        credential = gcloud_access_token() if use_gcp else api_key()
    except SpikeError as exc:
        fail(str(exc))
        return 2

    if use_gcp:
        print(
            f"Tryb Google Cloud: projekt={args.gcp_project}, lokalizacja={args.gcp_location}, "
            f"model={model}; token ADC pobrany (nie jest logowany)."
        )
    else:
        print(f"Tryb AI Studio: model={model}; klucz wczytany ze środowiska (nie jest logowany).")

    results: dict[str, bool] = {}
    try:
        passed, calls, model_content = q1_q2_q3(
            credential,
            model,
            gcp_project=args.gcp_project,
            gcp_location=args.gcp_location,
        )
        results["kształt + id + równoległość"] = passed
        if calls and model_content:
            results["runda powrotna"] = q4(
                credential,
                model,
                calls,
                model_content,
                gcp_project=args.gcp_project,
                gcp_location=args.gcp_location,
            )
        if not args.skip_stream:
            results["streaming"] = q5(
                credential,
                model,
                gcp_project=args.gcp_project,
                gcp_location=args.gcp_location,
            )
    except SpikeError as exc:
        fail(str(exc))
        return 1

    banner("PODSUMOWANIE")
    for name, passed in results.items():
        print(f"  {'PASS' if passed else 'FAIL'}  {name}")
    print()
    if results and all(results.values()):
        print("  ADR-8 wykonalne. Kształty z out/05..07 są podstawą adaptera w Fazie 6.")
    else:
        print("  Coś nie przeszło — ADR-8 wymaga rewizji przed Fazą 6.")
    return 0 if results and all(results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
