"""SPIKE-1 (blokujący dla ADR-1 i całej Fazy 2) — kształt drutu Google przez surowy REST.

Weryfikuje, że Nano Banana / Omni / Veo da się obsłużyć bez SDK `google-genai`,
i SPISUJE realne kształty odpowiedzi do scripts/spikes/out/*.json.

Uruchomienie:
    gcloud auth application-default login
    caelo_core/.venv/Scripts/python.exe scripts/spikes/spike1_google_wire.py \
        --gcp-project TWOJ_PROJEKT --check
    ... --gcp-project TWOJ_PROJEKT --image --yes-i-accept-cost

Alternatywnie przez AI Studio:
    $env:GEMINI_API_KEY = "..."                          # PowerShell
    caelo_core/.venv/Scripts/python.exe scripts/spikes/spike1_google_wire.py --check
    ... --image
    ... --omni --yes-i-accept-cost
    ... --veo   --yes-i-accept-cost

`--check` jest praktycznie darmowy (1 token). Generacje obrazu i wideo wymagają
jawnej flagi `--yes-i-accept-cost`.

UWAGA (limit weryfikacji): w środowisku z przechwytywaniem TLS ten skrypt nie
przejdzie — dokładnie jak reszta ruchu do api.x.ai. To musi uruchomić użytkownik
na swojej maszynie, z ważnym kluczem.
"""

from __future__ import annotations

import argparse
import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (  # noqa: E402
    CONNECTION_TEST_MODELS,
    SpikeError,
    api_key,
    banner,
    confirm_cost,
    dump,
    fail,
    gcloud_access_token,
    ok,
    poll,
    redact,
    request,
    request_raw_url,
    vertex_request,
)

# Identyfikatory z src/shared/models/{imageModels,videoModels}.ts
# Ustawiane, gdy któryś krok padł na uwierzytelnieniu — wtedy podsumowanie NIE
# obwinia ADR-1, bo błąd klucza nie mówi nic o kształcie API.
AUTH_PROBLEM: list[bool] = []

NANO_BANANA_2 = "gemini-3.1-flash-image"
OMNI_FLASH = "gemini-omni-flash-preview"
VEO_31_FAST = "veo-3.1-fast-generate-preview"  # najtańszy wariant Veo do spike'u
VEO_31_FAST_VERTEX = "veo-3.1-fast-generate-001"


# --- 1. Klucz działa -------------------------------------------------------------

def check_connection(key: str) -> bool:
    banner("1/4 · Test klucza (generateContent, 1 token — praktycznie darmowy)")
    last = None
    for model in CONNECTION_TEST_MODELS:
        try:
            data = request(
                "POST",
                f"models/{model}:generateContent",
                key,
                body={
                    "contents": [{"role": "user", "parts": [{"text": "ping"}]}],
                    "generationConfig": {"maxOutputTokens": 1},
                },
                timeout=60,
            )
            ok(f"klucz działa (model testowy: {model})")
            dump("01_connection", redact(data))
            return True
        except SpikeError as exc:
            last = exc
            print(f"    {model}: nie wyszło, próbuję następny…")
    fail(f"żaden model testowy nie odpowiedział. Ostatni błąd:\n{last}")
    return False


def check_connection_gcp(access_token: str, project: str, location: str) -> bool:
    banner("1/4 · Test Vertex AI / ADC (generateContent, 1 token)")
    last = None
    for model in CONNECTION_TEST_MODELS:
        try:
            data = vertex_request(
                "POST",
                project,
                location,
                f"publishers/google/models/{model}:generateContent",
                access_token,
                body={
                    "contents": [{"role": "user", "parts": [{"text": "ping"}]}],
                    "generationConfig": {"maxOutputTokens": 1},
                },
                timeout=60,
            )
            ok(f"Vertex AI i ADC działają (model testowy: {model})")
            dump("01_connection_gcp", redact(data))
            return True
        except SpikeError as exc:
            last = exc
            print(f"    {model}: nie wyszło, próbuję następny…")
    fail(f"żaden model testowy nie odpowiedział. Ostatni błąd:\n{last}")
    return False


# --- 2. Nano Banana przez Interactions API ---------------------------------------

def check_image(key: str) -> bool:
    banner("2/4 · Nano Banana 2 — Interactions API (POST /v1beta/interactions)")
    # Payload 1:1 z buildImageInteractionRequest() w ImageRequestBuilder.ts
    body = {
        "model": NANO_BANANA_2,
        "input": [{"type": "text", "text": "A single ripe banana on a plain white background, studio lighting"}],
        "response_format": {
            "type": "image",
            "delivery": "inline",
            "aspect_ratio": "1:1",
            "image_size": "1K",
        },
        "store": True,
    }
    try:
        data = request("POST", "interactions", key, body=body, timeout=300)
    except SpikeError as exc:
        fail(str(exc))
        if exc.is_auth_problem:
            AUTH_PROBLEM.append(True)
            print("\n  >>> To jest problem KLUCZA, nie kształtu API — nie mówi nic o ADR-1.")
            print("      Najczęstsza przyczyna: klucz został wymieniony/unieważniony, a w tym")
            print("      oknie nadal siedzi stary. Sprawdź darmowym `--check`; jeśli on też")
            print("      pada, ustaw nowy klucz i powtórz.")
            print("      Jeśli `--check` PRZECHODZI, a to nie — klucz ma ograniczenie API")
            print("      i Interactions nie jest dla niego odblokowane (to już jest ustalenie).")
        else:
            print("\n  >>> Błąd KSZTAŁTU żądania — to jest realny sygnał dla ADR-1.")
            print("      Zapisz treść błędu; wskaże, czym różni się payload od tego z SDK.")
        return False

    dump("02_image_interaction", redact(data))
    interaction_id = data.get("id")
    ok(f"interaction utworzony, id={interaction_id}, status={data.get('status')}")

    # Wyciągnij obrazek tym samym algorytmem co extractImages() — szukamy węzłów type=image.
    images = _collect_images(data)
    if not images:
        fail("brak obrazu w odpowiedzi (możliwe zablokowanie przez politykę bezpieczeństwa)")
        print("  Klucze najwyższego poziomu:", list(data.keys()))
        return False

    out = Path(__file__).resolve().parent / "out" / "02_image_sample.png"
    out.write_bytes(images[0])
    ok(f"zdekodowano {len(images)} obraz(y); pierwszy zapisany: {out.name} ({len(images[0])} B)")

    # Sprzątanie stanu serwerowego (spec 75) — potwierdza też ścieżkę DELETE.
    if interaction_id:
        try:
            request("DELETE", f"interactions/{interaction_id}", key, timeout=60)
            ok("DELETE /interactions/{id} działa (sprzątanie stanu serwerowego)")
        except SpikeError as exc:
            print(f"    (DELETE nie powiódł się, nieblokujące: {exc})")
    return True


def check_image_gcp(
    access_token: str,
    project: str,
    location: str,
    accepted: bool,
) -> bool:
    banner("2/4 · Nano Banana 2 — Vertex AI generateContent")
    confirm_cost("Generacja obrazu Nano Banana 2", accepted)
    body = {
        "contents": [{
            "role": "user",
            "parts": [{
                "text": "A single ripe banana on a plain white background, studio lighting"
            }],
        }],
        "generationConfig": {
            "responseModalities": ["TEXT", "IMAGE"],
            "imageConfig": {"aspectRatio": "1:1", "imageSize": "1K"},
        },
    }
    try:
        data = vertex_request(
            "POST",
            project,
            location,
            f"publishers/google/models/{NANO_BANANA_2}:generateContent",
            access_token,
            body=body,
            timeout=300,
        )
    except SpikeError as exc:
        fail(str(exc))
        if exc.is_auth_problem:
            AUTH_PROBLEM.append(True)
            print("\n  >>> Problem dotyczy ADC/uprawnień Vertex AI, nie kształtu żądania.")
        else:
            print("\n  >>> Błąd kształtu żądania — realny sygnał dla ADR-1.")
        return False

    dump("02_image_gcp_generate_content", redact(data))
    images = _collect_content_images(data)
    if not images:
        fail("Vertex AI odpowiedział bez obrazu")
        print("  Sprawdź out/02_image_gcp_generate_content.json.")
        return False
    out = Path(__file__).resolve().parent / "out" / "02_image_gcp_sample.png"
    out.write_bytes(images[0])
    ok(f"zdekodowano {len(images)} obraz(y); pierwszy zapisany: {out.name} ({len(images[0])} B)")
    return True


def _collect_images(node, acc=None) -> list[bytes]:
    """Odpowiednik extractImages() z ImageRequestBuilder.ts — rekurencyjny walk."""
    if acc is None:
        acc = []
    if isinstance(node, dict):
        if node.get("type") == "image":
            data = node.get("data") or node.get("inline_data") or node.get("inlineData")
            if isinstance(data, str) and data:
                try:
                    acc.append(base64.b64decode(data))
                except Exception:
                    pass
        for v in node.values():
            _collect_images(v, acc)
    elif isinstance(node, list):
        for v in node:
            _collect_images(v, acc)
    return acc


def _collect_content_images(node, acc=None) -> list[bytes]:
    """Wyciągnij `inlineData.data` z odpowiedzi Vertex generateContent."""
    if acc is None:
        acc = []
    if isinstance(node, dict):
        inline = node.get("inlineData") or node.get("inline_data")
        if isinstance(inline, dict):
            mime = str(inline.get("mimeType") or inline.get("mime_type") or "")
            data = inline.get("data")
            if mime.startswith("image/") and isinstance(data, str) and data:
                try:
                    acc.append(base64.b64decode(data, validate=True))
                except Exception:
                    pass
        for value in node.values():
            _collect_content_images(value, acc)
    elif isinstance(node, list):
        for value in node:
            _collect_content_images(value, acc)
    return acc


# --- 3. Omni Flash — Interactions + polling + URI ---------------------------------

def check_omni(key: str, accepted: bool) -> bool:
    banner("3/4 · Gemini Omni Flash — wideo przez Interactions (dostarczanie po URI)")
    confirm_cost("Generacja wideo Omni", accepted)

    # Payload 1:1 z OmniVideoProvider.submitVideo()
    body = {
        "model": OMNI_FLASH,
        "input": [{"type": "text", "text": "A calm ocean wave rolling onto a sandy beach at sunset"}],
        "response_format": {
            "type": "video",
            "delivery": "uri",
            "aspect_ratio": "16:9",
            "duration": "4s",
        },
        "generation_config": {"video_config": {"task": "text_to_video"}},
        "store": True,
        "background": True,
    }
    try:
        submitted = request("POST", "interactions", key, body=body, timeout=300)
    except SpikeError as exc:
        fail(str(exc))
        return False

    dump("03_omni_submit", redact(submitted))
    iid = submitted.get("id")
    if not iid:
        fail("brak id interakcji — to jest dokładnie stan UNKNOWN_REMOTE_STATE z ADR-2")
        return False
    ok(f"zgłoszone, interaction_id={iid} (TO jest uchwyt do utrwalenia PRZED czymkolwiek innym)")

    terminal = {"failed", "cancelled", "incomplete", "budget_exceeded"}

    def tick():
        cur = request("GET", f"interactions/{iid}", key, timeout=60)
        status = cur.get("status")
        if status in terminal:
            return True, cur
        return status == "completed", cur

    try:
        final, secs = poll(tick, label="Omni", interval=10.0, timeout=900.0)
    except SpikeError as exc:
        fail(str(exc))
        return False

    dump("03_omni_final", redact(final))
    ok(f"zakończone po {secs:.0f}s, status={final.get('status')}")
    media = _find_video(final)
    if media:
        ok(f"URI wideo: {str(media.get('uri'))[:90]}…  name={media.get('name')}")
        print("    (pobranie: GET <uri> z nagłówkiem x-goog-api-key, strumieniowo do .part)")
    else:
        fail("zakończone bez URI wideo")
    return bool(media)


def check_omni_gcp(
    access_token: str,
    project: str,
    location: str,
    accepted: bool,
) -> bool:
    banner("3/4 · Gemini Omni Flash — Vertex AI Interactions API")
    confirm_cost("Generacja wideo Gemini Omni Flash", accepted)

    # Aktualny Agent Platform API (2026-08) przyjmuje response_format jako listę.
    # `background` jest polem interakcji; zapisujemy id przed rozpoczęciem pollingu.
    body = {
        "model": OMNI_FLASH,
        "input": [{
            "type": "text",
            "text": "A calm ocean wave rolling onto a sandy beach at sunset",
        }],
        "response_format": [{
            "type": "video",
            # Live finding: `uri` without gcs_uri is accepted initially, then the
            # background interaction fails. Inline returns `type=video,data=...`.
            "delivery": "inline",
            "aspect_ratio": "16:9",
            "resolution": "720p",
            "duration": "4s",
        }],
        "generation_config": {"video_config": {"task": "text_to_video"}},
        "store": True,
        "background": True,
    }
    try:
        submitted = vertex_request(
            "POST",
            project,
            location,
            "interactions",
            access_token,
            body=body,
            timeout=300,
            api_version="v1beta1",
        )
    except SpikeError as exc:
        fail(str(exc))
        return False

    dump("03_omni_gcp_submit", redact(submitted))
    interaction_id = submitted.get("id")
    if not isinstance(interaction_id, str) or not interaction_id:
        fail("Agent Platform przyjął żądanie bez id interakcji — UNKNOWN_REMOTE_STATE")
        return False
    ok(f"interakcja zgłoszona i utrwalona: {interaction_id}")

    terminal = {"failed", "cancelled", "incomplete", "budget_exceeded"}

    def tick():
        current = vertex_request(
            "GET",
            project,
            location,
            f"interactions/{interaction_id}",
            access_token,
            timeout=60,
            api_version="v1beta1",
        )
        status = str(current.get("status") or "unknown")
        return status == "completed" or status in terminal, current

    try:
        if submitted.get("status") == "completed":
            final, secs = submitted, 0.0
        else:
            final, secs = poll(tick, label="Omni / Agent Platform", interval=10.0, timeout=900.0)
    except SpikeError as exc:
        fail(str(exc))
        print(f"  Interakcję można wznowić po id: {interaction_id}")
        return False

    dump("03_omni_gcp_final", redact(final))
    status = str(final.get("status") or "unknown")
    if status != "completed":
        fail(f"Omni zakończyło się statusem {status!r}: {final.get('errors')}")
        return False

    video = _extract_interaction_video(final)
    if not video:
        fail("Omni zakończyło interakcję bez danych lub URI wideo")
        return False
    if video.get("base64"):
        try:
            payload = base64.b64decode(str(video["base64"]), validate=True)
        except Exception as exc:
            fail(f"Nie można zdekodować wideo base64: {exc}")
            return False
        out = Path(__file__).resolve().parent / "out" / "03_omni_gcp_sample.mp4"
        out.write_bytes(payload)
        ok(f"wideo gotowe po {secs:.0f}s: {out.name} ({len(payload)} B)")
        return True

    ok(f"wideo gotowe po {secs:.0f}s; URI: {video.get('uri')}")
    print("  Odpowiedź zwróciła URI zamiast danych inline; zapisano je w dumpie.")
    return True


def _extract_interaction_video(node) -> dict | None:
    """Znajdź wideo `type=video` w odpowiedzi Interactions API."""
    if isinstance(node, dict):
        mime = str(node.get("mime_type") or node.get("mimeType") or "")
        if node.get("type") == "video" or mime.startswith("video/"):
            data = node.get("data") or node.get("bytesBase64Encoded")
            uri = node.get("uri") or node.get("file_uri") or node.get("fileUri")
            if data or uri:
                return {"base64": data, "uri": uri, "mimeType": mime or "video/mp4"}
        for value in node.values():
            found = _extract_interaction_video(value)
            if found:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _extract_interaction_video(value)
            if found:
                return found
    return None


def _find_video(node, found=None):
    """Odpowiednik findVideoMedia() z OmniVideoProvider.ts."""
    if found is None:
        found = {}
    if found:
        return found
    if isinstance(node, dict):
        mime = str(node.get("mime_type") or node.get("mimeType") or "")
        if node.get("type") == "video" or mime.startswith("video/"):
            uri = node.get("uri") or node.get("file_uri") or node.get("fileUri")
            name = node.get("name") or node.get("file_name") or node.get("fileName")
            if uri or name:
                found.update({"uri": uri, "name": name, "mimeType": mime or None})
                return found
        for v in node.values():
            _find_video(v, found)
            if found:
                return found
    elif isinstance(node, list):
        for v in node:
            _find_video(v, found)
            if found:
                return found
    return found


# --- 4. Veo 3.1 — predictLongRunning + operacja LRO -------------------------------

def check_veo(key: str, accepted: bool) -> bool:
    banner("4/4 · Veo 3.1 Fast — predictLongRunning + polling operacji LRO")
    confirm_cost("Generacja wideo Veo", accepted)

    # Payload odpowiadający VeoVideoProvider.submitVideo() (tryb text_to_video).
    body = {
        "instances": [{"prompt": "A paper boat drifting down a rain puddle, macro shot"}],
        "parameters": {
            "aspectRatio": "16:9",
            "resolution": "720p",
            "durationSeconds": 4,
            "sampleCount": 1,
            "generateAudio": True,
        },
    }
    try:
        op = request(
            "POST", f"models/{VEO_31_FAST}:predictLongRunning", key, body=body, timeout=300
        )
    except SpikeError as exc:
        fail(str(exc))
        print("\n  >>> Uwaga: kształt `instances`/`parameters` to najbardziej niepewny element")
        print("      całego spike'u. Zapisz treść błędu — ona wskaże właściwy kształt.")
        return False

    dump("04_veo_submit", redact(op))
    name = op.get("name")
    if not name:
        fail("operacja bez `name` — UNKNOWN_REMOTE_STATE (ADR-2: NIE ponawiamy automatycznie)")
        return False
    ok(f"operacja zgłoszona: {name}")
    print("    (TO jest uchwyt, który Caelo 1.x gubi przy restarcie — patrz ADR-2)")

    def tick():
        cur = request_raw_url(
            "GET", f"https://generativelanguage.googleapis.com/v1beta/{name}", key, timeout=60
        )
        return bool(cur.get("done")), cur

    try:
        final, secs = poll(tick, label="Veo", interval=15.0, timeout=1200.0)
    except SpikeError as exc:
        fail(str(exc))
        return False

    dump("04_veo_final", redact(final))
    if final.get("error"):
        fail(f"Veo zgłosiło błąd: {final['error']}")
        return False
    ok(f"operacja zakończona po {secs:.0f}s")
    video = _find_video(final)
    if video and video.get("uri"):
        ok(f"URI wideo: {str(video['uri'])[:90]}…")
    else:
        print("    Odpowiedź nie zawiera URI — sprawdź 04_veo_final.json")
        print("    (Agent Platform zwraca bytesBase64Encoded zamiast URI)")
    return True


def check_veo_gcp(
    access_token: str,
    project: str,
    location: str,
    accepted: bool,
) -> bool:
    banner("4/4 · Veo 3.1 Fast — Vertex AI predictLongRunning")
    confirm_cost("Generacja wideo Veo 3.1 Fast", accepted)

    # Najtańszy reprezentatywny wariant: 4 s, 720p, bez audio. Kształt jest
    # dokładnie tym, co @google/genai mapuje z source/config na Vertex REST.
    body = {
        "instances": [{
            "prompt": "A paper boat drifting slowly across a small rain puddle, macro shot"
        }],
        "parameters": {
            "sampleCount": 1,
            "fps": 24,
            "durationSeconds": 4,
            "aspectRatio": "16:9",
            "resolution": "720p",
            "generateAudio": False,
        },
    }
    resource = f"publishers/google/models/{VEO_31_FAST_VERTEX}"
    try:
        operation = vertex_request(
            "POST",
            project,
            location,
            f"{resource}:predictLongRunning",
            access_token,
            body=body,
            timeout=300,
            api_version="v1",
        )
    except SpikeError as exc:
        fail(str(exc))
        return False

    dump("04_veo_gcp_submit", redact(operation))
    operation_name = operation.get("name")
    if not isinstance(operation_name, str) or not operation_name:
        fail("Vertex AI przyjął żądanie bez nazwy operacji — UNKNOWN_REMOTE_STATE")
        return False
    ok(f"operacja zgłoszona i utrwalona: {operation_name}")

    def tick():
        current = vertex_request(
            "POST",
            project,
            location,
            f"{resource}:fetchPredictOperation",
            access_token,
            body={"operationName": operation_name},
            timeout=60,
            api_version="v1",
        )
        return bool(current.get("done")), current

    try:
        final, secs = poll(tick, label="Veo / Vertex AI", interval=15.0, timeout=1200.0)
    except SpikeError as exc:
        fail(str(exc))
        print(f"  Operację można wznowić po nazwie: {operation_name}")
        return False

    dump("04_veo_gcp_final", redact(final))
    if final.get("error"):
        fail(f"Veo zgłosiło błąd: {final['error']}")
        return False

    video = _extract_vertex_video(final)
    if not video:
        fail("Veo zakończyło operację bez danych lub URI wideo")
        return False
    if video.get("base64"):
        try:
            payload = base64.b64decode(str(video["base64"]), validate=True)
        except Exception as exc:
            fail(f"Nie można zdekodować wideo base64: {exc}")
            return False
        out = Path(__file__).resolve().parent / "out" / "04_veo_gcp_sample.mp4"
        out.write_bytes(payload)
        ok(f"wideo gotowe po {secs:.0f}s: {out.name} ({len(payload)} B)")
        return True

    ok(f"wideo gotowe po {secs:.0f}s; URI: {video.get('uri')}")
    print("  Odpowiedź zwróciła URI zamiast danych inline; zapisano je w dumpie.")
    return True


def check_veo_extend_gcp(
    access_token: str,
    project: str,
    location: str,
    source_path: Path,
    accepted: bool,
) -> bool:
    banner("4b/4 · Veo 3.1 Fast — rozszerzenie istniejącego wideo")
    confirm_cost("Rozszerzenie wideo Veo 3.1 Fast", accepted)
    if not source_path.is_file():
        raise SpikeError(f"Nie znaleziono źródłowego MP4: {source_path}")

    source_data = base64.b64encode(source_path.read_bytes()).decode("ascii")
    body = {
        "instances": [{
            "prompt": "Continue the paper boat drifting gently across the rain puddle",
            "video": {
                "bytesBase64Encoded": source_data,
                "mimeType": "video/mp4",
            },
        }],
        "parameters": {
            "sampleCount": 1,
            "fps": 24,
            "durationSeconds": 7,
            "aspectRatio": "16:9",
            "resolution": "720p",
            "generateAudio": False,
        },
    }
    resource = f"publishers/google/models/{VEO_31_FAST_VERTEX}"
    try:
        operation = vertex_request(
            "POST",
            project,
            location,
            f"{resource}:predictLongRunning",
            access_token,
            body=body,
            timeout=300,
            api_version="v1",
        )
    except SpikeError as exc:
        fail(str(exc))
        return False

    dump("05_veo_gcp_extend_submit", redact(operation))
    operation_name = operation.get("name")
    if not isinstance(operation_name, str) or not operation_name:
        fail("Vertex AI przyjął rozszerzenie bez nazwy operacji — UNKNOWN_REMOTE_STATE")
        return False
    ok(f"operacja rozszerzenia zgłoszona i utrwalona: {operation_name}")

    def tick():
        current = vertex_request(
            "POST",
            project,
            location,
            f"{resource}:fetchPredictOperation",
            access_token,
            body={"operationName": operation_name},
            timeout=60,
            api_version="v1",
        )
        return bool(current.get("done")), current

    try:
        final, secs = poll(
            tick, label="Veo extend / Vertex AI", interval=15.0, timeout=1200.0
        )
    except SpikeError as exc:
        fail(str(exc))
        print(f"  Operację można wznowić po nazwie: {operation_name}")
        return False

    dump("05_veo_gcp_extend_final", redact(final))
    if final.get("error"):
        fail(f"Veo extend zgłosiło błąd: {final['error']}")
        return False
    video = _extract_vertex_video(final)
    if not video or not video.get("base64"):
        if video and video.get("uri"):
            ok(f"rozszerzenie gotowe po {secs:.0f}s; URI: {video['uri']}")
            return True
        fail("Veo extend zakończyło operację bez danych lub URI wideo")
        return False
    try:
        payload = base64.b64decode(str(video["base64"]), validate=True)
    except Exception as exc:
        fail(f"Nie można zdekodować rozszerzonego wideo: {exc}")
        return False
    out = Path(__file__).resolve().parent / "out" / "05_veo_gcp_extend_sample.mp4"
    out.write_bytes(payload)
    ok(f"rozszerzenie gotowe po {secs:.0f}s: {out.name} ({len(payload)} B)")
    return True


def _extract_vertex_video(node) -> dict | None:
    """Znajdź pierwszy film w surowej odpowiedzi fetchPredictOperation."""
    if isinstance(node, dict):
        mime = str(node.get("mimeType") or node.get("mime_type") or "")
        base64_data = (
            node.get("bytesBase64Encoded")
            or node.get("bytes_base64_encoded")
            or node.get("videoBytes")
        )
        uri = node.get("gcsUri") or node.get("uri") or node.get("videoUri")
        if mime.startswith("video/") and (base64_data or uri):
            return {"base64": base64_data, "uri": uri, "mimeType": mime}
        for value in node.values():
            found = _extract_vertex_video(value)
            if found:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _extract_vertex_video(value)
            if found:
                return found
    return None


# --- główna ----------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description="SPIKE-1 — kształt drutu Google przez surowy REST")
    p.add_argument("--check", action="store_true", help="tylko test klucza (darmowy)")
    p.add_argument("--image", action="store_true", help="Nano Banana (KOSZT)")
    p.add_argument("--omni", action="store_true", help="Omni Flash wideo (KOSZT)")
    p.add_argument("--veo", action="store_true", help="Veo 3.1 Fast (KOSZT)")
    p.add_argument(
        "--veo-extend",
        metavar="MP4",
        help="rozszerz wskazany film Veo przez Vertex AI (KOSZT)",
    )
    p.add_argument("--all", action="store_true", help="wszystko (KOSZT)")
    p.add_argument("--yes-i-accept-cost", action="store_true", dest="accept",
                   help="zgoda na operacje kosztujące pieniądze")
    p.add_argument("--gcp-project", help="projekt Google Cloud; włącza Vertex AI + ADC")
    p.add_argument("--gcp-location", default="global", help="region Vertex AI (domyślnie: global)")
    p.add_argument(
        "--gcp-video-location",
        default="us-central1",
        help="regionalny endpoint Veo (domyślnie: us-central1)",
    )
    args = p.parse_args()

    if not any([args.check, args.image, args.omni, args.veo, args.veo_extend, args.all]):
        p.print_help()
        print("\nZacznij od:  --check")
        return 2

    use_gcp = bool(args.gcp_project)
    try:
        credential = gcloud_access_token() if use_gcp else api_key()
    except SpikeError as exc:
        fail(str(exc))
        return 2

    if use_gcp:
        print(
            f"Tryb Google Cloud: projekt={args.gcp_project}, region={args.gcp_location}; "
            "token ADC pobrany (nie jest logowany)."
        )
    else:
        print(f"Klucz wczytany ze środowiska ({len(credential)} znaków, nie jest logowany).")

    results: dict[str, bool] = {}
    try:
        if args.check or args.all:
            if use_gcp:
                auth_ok = check_connection_gcp(
                    credential, args.gcp_project, args.gcp_location
                )
                results["Vertex AI / ADC"] = auth_ok
            else:
                auth_ok = check_connection(credential)
                results["klucz"] = auth_ok
            if not auth_ok:
                print("\nBez działającego uwierzytelnienia reszta nie ma sensu — przerywam.")
                return 1
        if args.image or args.all:
            if use_gcp:
                results["obraz (Vertex generateContent)"] = check_image_gcp(
                    credential, args.gcp_project, args.gcp_location, args.accept
                )
            else:
                confirm_cost("Generacja obrazu Nano Banana 2", args.accept)
                results["obraz (Interactions)"] = check_image(credential)
        if args.omni or args.all:
            if use_gcp:
                results["wideo Omni (Agent Platform)"] = check_omni_gcp(
                    credential, args.gcp_project, args.gcp_location, args.accept
                )
            else:
                results["wideo Omni"] = check_omni(credential, args.accept)
        if args.veo or args.all:
            if use_gcp:
                results["wideo Veo (Vertex AI)"] = check_veo_gcp(
                    credential, args.gcp_project, args.gcp_video_location, args.accept
                )
            else:
                results["wideo Veo"] = check_veo(credential, args.accept)
        if args.veo_extend:
            if not use_gcp:
                raise SpikeError("--veo-extend w tym spike'u wymaga --gcp-project.")
            results["rozszerzenie Veo (Vertex AI)"] = check_veo_extend_gcp(
                credential,
                args.gcp_project,
                args.gcp_video_location,
                Path(args.veo_extend).resolve(),
                args.accept,
            )
    except SpikeError as exc:
        fail(str(exc))
        return 1
    except KeyboardInterrupt:
        print("\nPrzerwane przez użytkownika.")
        print("UWAGA: zdalna generacja mogła już ruszyć i zostać naliczona (ADR-2).")
        return 130

    banner("PODSUMOWANIE")
    for name, passed in results.items():
        print(f"  {'PASS' if passed else 'FAIL'}  {name}")
    print()
    if all(results.values()):
        if args.check and not any([args.image, args.omni, args.veo, args.veo_extend, args.all]):
            print("  Połączenie POTWIERDZONE — uwierzytelnienie i surowy REST działają.")
            print("  To nie zamyka jeszcze płatnych testów mediów.")
        else:
            print("  ADR-1 POTWIERDZONE empirycznie dla wybranej ścieżki — bez SDK.")
            print("  Kształt odpowiedzi leży w scripts/spikes/out/.")
    elif AUTH_PROBLEM:
        print("  NIEROZSTRZYGNIĘTE — coś padło na KLUCZU, nie na kształcie API.")
        print("  To nie podważa ADR-1. Napraw klucz i powtórz; dopiero wtedy wynik coś znaczy.")
    else:
        print("  Któryś element zawiódł na KSZTAŁCIE żądania — ADR-1 wymaga rewizji PRZED Fazą 2.")
        print("  Dołącz zawartość out/*.json i treść błędu do notatki z decyzji.")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
