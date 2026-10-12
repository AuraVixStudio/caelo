import requests
import base64
import io
import json
import time
from PIL import Image
from config import (API_BASE, DEFAULT_VIDEO_MODEL, DEFAULT_IMAGE_MODEL,
                    IMAGE_QUALITY_LEVELS, MAX_VIDEO_KEYFRAMES, MAX_VIDEO_REFERENCE_AUDIOS,
                    image_model_supports_quality, normalize_image_model,
                    video_max_reference_images, video_model_supports_pinned_frames,
                    video_model_supports_voices)

# Timeouty HTTP do xAI (P1-4) — sekundy. Bez nich zawieszone połączenie blokuje
# wątek z puli serwera (dużo takich = zamrożony sidecar). Wartości dobrane do typu
# operacji: generacja/edycja obrazu bywa wolna; POST zadania wideo zwraca request_id
# od razu (odpytywanie statusu osobno), więc krótszy.
TIMEOUT_IMAGE = 180        # generacja/edycja obrazu
TIMEOUT_VIDEO_JOB = 120    # POST tworzący/edytujący/przedłużający zadanie wideo (-> request_id)
TIMEOUT_POLL = 30          # GET statusu zadania wideo

def _apply_quality(payload, quality):
    """Dołóż `quality` (low|medium) TYLKO gdy model faktycznie go przyjmuje.
    xAI dokumentuje ten parametr wyłącznie dla `grok-imagine-image-2.0`; wysłanie go
    do innego modelu kończy się 4xx, więc po cichu go pomijamy zamiast psuć żądanie."""
    q = (quality or "").strip().lower()
    if q in IMAGE_QUALITY_LEVELS and image_model_supports_quality(payload.get("model", "")):
        payload["quality"] = q


def _reference_images_payload(reference_images, model=None):
    """Lista URI/URL → format `reference_images` xAI ([{"url": …}]), przycięta do limitu
    modelu (1.5: 14, bazowy: 7, lite: 0 — wtedy pole w ogóle nie idzie)."""
    refs = [r for r in (reference_images or []) if r]
    return [{"url": r} for r in refs[:video_max_reference_images(model or DEFAULT_VIDEO_MODEL)]]


def _resolve_image_model(model, quality):
    """Wycofany slug (`grok-imagine-image-quality`/`-pro`) → 2.0 + jakość `low`, jawnie
    zamiast polegać na cichym przekierowaniu xAI (to samo, co zrobi serwer po 2026-11-02)."""
    return normalize_image_model(model or DEFAULT_IMAGE_MODEL, quality)


def get_headers(api_key):
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

class APIManager:
    def __init__(self, api_key_provider):
        self.get_api_key = api_key_provider

    def generate_image(self, prompt, n, ratio, resolution, model=None, quality=None):
        api_key = self.get_api_key()
        model, quality = _resolve_image_model(model, quality)
        payload = {
            "model": model,
            "prompt": prompt,
            "n": n,
            "resolution": resolution
        }
        if ratio != "auto":
            payload["aspect_ratio"] = ratio
        _apply_quality(payload, quality)

        r = requests.post(f"{API_BASE}/images/generations", headers=get_headers(api_key), json=payload, timeout=TIMEOUT_IMAGE)
        r.raise_for_status()
        return [item["url"] for item in r.json()["data"]]

    def edit_image(self, prompt, n, reference_images, ratio, resolution, model=None):
        api_key = self.get_api_key()
        images_list = []
        for path in reference_images:
            img = Image.open(path)
            img.thumbnail((1536, 1536), Image.Resampling.LANCZOS)
            if img.mode != "RGB":
                img = img.convert("RGB")
            
            buffered = io.BytesIO()
            img.save(buffered, format="JPEG")
            b64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
            
            images_list.append({
                "url": f"data:image/jpeg;base64,{b64}",
                "type": "image_url"
            })

        model, _ = _resolve_image_model(model, None)
        payload = {
            "model": model,
            "prompt": prompt,
            "images": images_list,
            "n": n,
            "aspect_ratio": ratio,
            "resolution": resolution,
            "response_format": "url"
        }

        r = requests.post(f"{API_BASE}/images/edits", headers=get_headers(api_key), json=payload, timeout=TIMEOUT_IMAGE)
        if r.status_code in (400, 422):
            raise Exception(f"API Error: {r.text[:500]}")
        r.raise_for_status()
        return [item["url"] for item in r.json().get("data", [])]

    def create_video_job(self, prompt, duration, resolution, ratio, image_path=None,
                          model=None, image_data_uri=None, reference_images=None,
                          last_frame=None, keyframes=None, reference_audios=None,
                          generate_audio=None):
        """Zadanie wideo (/videos/generations). `image_data_uri`/`image_path` = kadr
        STARTOWY (image→video). `reference_images` (1.5: ≤14, bazowy: ≤7) to co innego:
        przenoszą postać/produkt/miejsce do klipu NIE blokując pierwszej klatki — w
        promptcie tagi od <IMAGE_0> (gdy jest kadr startowy, to on jest <IMAGE_0>).
        Tylko 1.5: `last_frame` (kadr końcowy), `keyframes` [{image, timestamp_s}] (≤4) i
        `reference_audios` (id głosów presetowych, ≤3, w promptcie <AUDIO_0>…).
        `generate_audio=False` = klip bez dźwięku (domyślnie API generuje audio).
        Pola nieznane danemu modelowi są pomijane — xAI odrzuca całe żądanie (4xx)."""
        api_key = self.get_api_key()
        model = model or DEFAULT_VIDEO_MODEL
        payload = {
            "model": model,
            "prompt": prompt,
            "duration": duration,
            "resolution": resolution
        }
        if ratio != "Original":
            payload["aspect_ratio"] = ratio

        # Image-to-video: gotowy data-URI z rendererra (jak załączniki czatu) ma
        # pierwszeństwo; ścieżka pliku (legacy) jest skalowana przez PIL.
        if image_data_uri:
            payload["image"] = {"url": image_data_uri}
        elif image_path:
            img = Image.open(image_path)
            img.thumbnail((1280, 720), Image.Resampling.LANCZOS)
            if img.mode != "RGB":
                img = img.convert("RGB")
            buffered = io.BytesIO()
            img.save(buffered, format="JPEG")
            b64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
            payload["image"] = {"url": f"data:image/jpeg;base64,{b64}"}

        refs = _reference_images_payload(reference_images, model)
        if refs:
            payload["reference_images"] = refs
        if video_model_supports_pinned_frames(model):
            if last_frame:
                payload["last_frame"] = {"url": last_frame}
            frames = [
                {"image": {"url": kf["image"]}, "timestamp_s": float(kf["timestamp_s"])}
                for kf in (keyframes or [])
                if isinstance(kf, dict) and kf.get("image") and kf.get("timestamp_s") is not None
            ][:MAX_VIDEO_KEYFRAMES]
            if frames:
                payload["keyframes"] = frames
        if video_model_supports_voices(model):
            voices = [{"voice_id": v} for v in (reference_audios or []) if v]
            if voices:
                payload["reference_audios"] = voices[:MAX_VIDEO_REFERENCE_AUDIOS]
        if generate_audio is False:
            payload["generate_audio"] = False

        r = requests.post(f"{API_BASE}/videos/generations", headers=get_headers(api_key), json=payload, timeout=TIMEOUT_VIDEO_JOB)
        # Pokaz tresc bledu 4xx (jak edit_image) — generyczne "400 Bad Request" nie
        # mowilo, CO odrzucil xAI (np. brak wymaganego obrazu dla image-to-video).
        if r.status_code in (400, 422):
            raise Exception(f"API Error: {r.text[:500]}")
        r.raise_for_status()
        return r.json()["request_id"]

    def edit_video_job(self, prompt, video, model=None):
        """Edycja istniejącego wideo (/videos/edits). `video` to publiczny URL (https)
        lub data-URI (base64). API zachowuje długość źródła — brak duration/resolution/
        aspect_ratio. Zwraca request_id (odpytywany jak generacja)."""
        api_key = self.get_api_key()
        payload = {
            "model": model or DEFAULT_VIDEO_MODEL,
            "prompt": prompt,
            "video": {"url": video},
        }
        r = requests.post(f"{API_BASE}/videos/edits", headers=get_headers(api_key), json=payload, timeout=TIMEOUT_VIDEO_JOB)
        if r.status_code in (400, 422):
            raise Exception(f"API Error: {r.text[:500]}")
        r.raise_for_status()
        return r.json()["request_id"]

    def extend_video_job(self, prompt, video, duration=None, model=None):
        """Przedłużenie istniejącego wideo od ostatniej klatki (/videos/extensions).
        `video` jak w edit; `duration` to liczba dodanych sekund (1-10). Zwraca request_id."""
        api_key = self.get_api_key()
        payload = {
            "model": model or DEFAULT_VIDEO_MODEL,
            "prompt": prompt,
            "video": {"url": video},
        }
        if duration:
            payload["duration"] = duration
        r = requests.post(f"{API_BASE}/videos/extensions", headers=get_headers(api_key), json=payload, timeout=TIMEOUT_VIDEO_JOB)
        if r.status_code in (400, 422):
            raise Exception(f"API Error: {r.text[:500]}")
        r.raise_for_status()
        return r.json()["request_id"]

    def poll_video_status(self, job_id):
        api_key = self.get_api_key()
        r = requests.get(f"{API_BASE}/videos/{job_id}", headers=get_headers(api_key), timeout=TIMEOUT_POLL)
        r.raise_for_status()
        return r.json()

    def text_to_speech(self, text, voice_id="eve", language="en"):
        """Tekst -> mowa (/tts). Zwraca (bajty_audio, mime). Domyślnie MP3 24 kHz.
        Głosy: eve / ara / rex / sal / leo."""
        api_key = self.get_api_key()
        payload = {"text": text, "voice_id": voice_id, "language": language}
        r = requests.post(f"{API_BASE}/tts", headers=get_headers(api_key), json=payload, timeout=180)
        if r.status_code in (400, 401, 403, 422):
            raise Exception(f"API Error: {r.text[:500]}")
        r.raise_for_status()
        return r.content, r.headers.get("Content-Type", "audio/mpeg")

    def speech_to_text(self, audio_bytes, filename="speech.webm", language=None):
        """Mowa -> tekst (/stt, multipart). Zwraca dict z polem `text` (+ ew. words/duration).
        Nagłówek Content-Type ustawia `requests` sam (boundary multipart) — NIE używamy
        get_headers, które wymusza application/json."""
        api_key = self.get_api_key()
        headers = {"Authorization": f"Bearer {api_key}"}
        data = {}
        if language:
            data["language"] = language
        # Pole `file` musi iść po pozostałych polach formularza (wymóg API).
        files = {"file": (filename, audio_bytes)}
        r = requests.post(f"{API_BASE}/stt", headers=headers, data=data, files=files, timeout=180)
        if r.status_code in (400, 401, 403, 422):
            raise Exception(f"API Error: {r.text[:500]}")
        r.raise_for_status()
        r.encoding = "utf-8"
        return r.json()

    def chat_completion(self, messages, model="grok-4", temperature=0.7):
        api_key = self.get_api_key()
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "temperature": temperature
        }
        r = requests.post(f"{API_BASE}/chat/completions", headers=get_headers(api_key), json=payload, timeout=300)
        r.raise_for_status()
        r.encoding = "utf-8"  # wymuś UTF-8, by nie psuć polskich znaków
        return r.json()["choices"][0]["message"]["content"]

    def chat_completion_stream(self, messages, model="grok-4", temperature=0.7,
                               on_delta=None, stop_flag=None):
        """Streaming czatu (SSE). Wywołuje on_delta(delta, full) dla każdego fragmentu.
        stop_flag() == True przerywa odbiór. Zwraca pełną zebraną odpowiedź (string).
        Obsługuje treść multimodalną (content jako lista part-ów: text + image_url)."""
        api_key = self.get_api_key()
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "temperature": temperature
        }
        full = ""
        with requests.post(f"{API_BASE}/chat/completions", headers=get_headers(api_key),
                           json=payload, stream=True, timeout=300) as r:
            r.raise_for_status()
            # Dekodujemy bajty JAWNIE jako UTF-8 — requests dla text/event-stream
            # potrafi zgadnąć ISO-8859-1, co psuło polskie znaki (mojibake).
            for raw in r.iter_lines(decode_unicode=False):
                if stop_flag and stop_flag():
                    break
                if not raw:
                    continue
                line = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else raw
                if line.startswith("data:"):
                    line = line[5:].strip()
                if line == "[DONE]":
                    break
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                choices = obj.get("choices") or [{}]
                delta = (choices[0].get("delta") or {}).get("content")
                if delta:
                    full += delta
                    if on_delta:
                        on_delta(delta, full)
        return full

    def chat_with_tools(self, messages, model="grok-4", temperature=0.7, tools=None, tool_choice="auto"):
        """Czat z obsługą narzędzi (function calling). Zwraca pełną wiadomość asystenta
        (dict): może zawierać 'content' i/lub 'tool_calls'."""
        api_key = self.get_api_key()
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice
        r = requests.post(f"{API_BASE}/chat/completions", headers=get_headers(api_key), json=payload, timeout=300)
        r.raise_for_status()
        r.encoding = "utf-8"
        return r.json()["choices"][0]["message"]

    def edit_image_b64(self, prompt, data_uris, n=1, ratio="auto", resolution="1k",
                       model=None, quality=None):
        """Edycja obrazu z gotowych data-URI (np. z załączników czatu), bez ścieżek plików."""
        api_key = self.get_api_key()
        images_list = [{"url": uri, "type": "image_url"} for uri in data_uris]
        model, quality = _resolve_image_model(model, quality)
        payload = {
            "model": model,
            "prompt": prompt,
            "images": images_list,
            "n": n,
            "aspect_ratio": ratio,
            "resolution": resolution,
            "response_format": "url",
        }
        _apply_quality(payload, quality)
        r = requests.post(f"{API_BASE}/images/edits", headers=get_headers(api_key), json=payload, timeout=TIMEOUT_IMAGE)
        if r.status_code in (400, 422):
            raise Exception(f"API Error: {r.text[:500]}")
        r.raise_for_status()
        return [item["url"] for item in r.json().get("data", [])]

    def list_models(self):
        """Zwraca listę id modeli dostępnych dla bieżącego logowania (OAuth lub klucz).
        Endpoint zgodny z OpenAI: GET /v1/models -> {"data": [{"id": ...}, ...]}.
        Przy błędzie zwraca pustą listę (wywołujący użyje listy zapasowej)."""
        api_key = self.get_api_key()
        if not api_key:
            return []
        try:
            r = requests.get(f"{API_BASE}/models", headers=get_headers(api_key), timeout=20)
            r.raise_for_status()
            return [m.get("id") for m in r.json().get("data", []) if m.get("id")]
        except Exception:
            return []
