import requests
import base64
import io
import json
import time
from PIL import Image
from config import API_BASE, DEFAULT_VIDEO_MODEL, DEFAULT_IMAGE_MODEL

# Timeouty HTTP do xAI (P1-4) — sekundy. Bez nich zawieszone połączenie blokuje
# wątek z puli serwera (dużo takich = zamrożony sidecar). Wartości dobrane do typu
# operacji: generacja/edycja obrazu bywa wolna; POST zadania wideo zwraca request_id
# od razu (odpytywanie statusu osobno), więc krótszy.
TIMEOUT_IMAGE = 180        # generacja/edycja obrazu
TIMEOUT_VIDEO_JOB = 120    # POST tworzący/edytujący/przedłużający zadanie wideo (-> request_id)
TIMEOUT_POLL = 30          # GET statusu zadania wideo

def get_headers(api_key):
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

class APIManager:
    def __init__(self, api_key_provider):
        self.get_api_key = api_key_provider

    def generate_image(self, prompt, n, ratio, resolution, model=None):
        api_key = self.get_api_key()
        payload = {
            "model": model or DEFAULT_IMAGE_MODEL,
            "prompt": prompt,
            "n": n,
            "resolution": resolution
        }
        if ratio != "auto":
            payload["aspect_ratio"] = ratio
            
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

        payload = {
            "model": model or DEFAULT_IMAGE_MODEL,
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
                          model=None, image_data_uri=None):
        api_key = self.get_api_key()
        payload = {
            "model": model or DEFAULT_VIDEO_MODEL,
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

    def edit_image_b64(self, prompt, data_uris, n=1, ratio="auto", resolution="1k", model=None):
        """Edycja obrazu z gotowych data-URI (np. z załączników czatu), bez ścieżek plików."""
        api_key = self.get_api_key()
        images_list = [{"url": uri, "type": "image_url"} for uri in data_uris]
        payload = {
            "model": model or DEFAULT_IMAGE_MODEL,
            "prompt": prompt,
            "images": images_list,
            "n": n,
            "aspect_ratio": ratio,
            "resolution": resolution,
            "response_format": "url",
        }
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
