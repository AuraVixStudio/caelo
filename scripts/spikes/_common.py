"""Wspólna warstwa transportowa dla spike'ów Google (Faza 0, ADR-1).

CELOWO używa wyłącznie `requests` — bez `google-genai`, bez żadnego SDK. Uruchomienie
tych skryptów JEST weryfikacją ADR-1: jeśli działają, teza „Google da się obsłużyć
surowym REST-em w stylu, w którym Caelo obsługuje xAI" jest potwierdzona empirycznie.

Ścieżki REST wydobyto ze źródeł `@google/genai@2.17.1` (dist/index.cjs) leżących
w node_modules `gemini-desktop-studio` — patrz scripts/spikes/README.md.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import requests

# Windows PowerShell 5.1 ma konsolę w cp852/cp1250 — bez tego polskie znaki
# w komunikatach wychodzą jako krzaki. Nieszkodliwe na innych platformach.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:
        pass

BASE = "https://generativelanguage.googleapis.com"
API_VERSION = "v1beta"
VERTEX_API_VERSION = "v1beta1"

OUT_DIR = Path(__file__).resolve().parent / "out"

# Modele testowe do sprawdzenia klucza — od najtańszych. Lista z CONNECTION_TEST_MODELS
# w GeminiClient.ts; wycofany model nie mówi nic o kluczu, więc próbujemy po kolei.
CONNECTION_TEST_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3-flash-lite",
    "gemini-flash-lite-latest",
]


class SpikeError(RuntimeError):
    """Błąd spike'u. `status`/`reason` pozwalają ODRÓŻNIĆ problem z kluczem od
    problemu z kształtem żądania — to rozróżnienie jest istotne, bo tylko to
    drugie mówi cokolwiek o ADR-1."""

    def __init__(self, message: str, *, status: Optional[int] = None,
                 reason: Optional[str] = None) -> None:
        super().__init__(message)
        self.status = status
        self.reason = reason

    @property
    def is_auth_problem(self) -> bool:
        """True dla błędów klucza/uprawnień — NIE świadczą o kształcie API."""
        if self.status in (401, 403):
            return True
        return (self.reason or "") in {
            "API_KEY_INVALID", "API_KEY_SERVICE_BLOCKED", "PERMISSION_DENIED",
            "API_KEY_HTTP_REFERRER_BLOCKED", "API_KEY_IP_ADDRESS_BLOCKED",
        }


def _error_reason(payload: Any) -> Optional[str]:
    """Wyciągnij `details[].reason` z błędu Google (kształt google.rpc.ErrorInfo).

    USTALENIE ZE SPIKE-1: `/v1beta/interactions` zwraca błąd opakowany w TABLICĘ
    (`[{"error": …}]`), podczas gdy `:generateContent` zwraca goły obiekt. Taksonomia
    błędów w Fazie 2 musi obsłużyć oba kształty.
    """
    if isinstance(payload, list):
        payload = next((x for x in payload if isinstance(x, dict) and "error" in x), {})
    if not isinstance(payload, dict):
        return None
    err = payload.get("error") or {}
    if not isinstance(err, dict):
        return None
    for det in err.get("details") or []:
        if isinstance(det, dict) and det.get("reason"):
            return str(det["reason"])
    return err.get("status") if isinstance(err.get("status"), str) else None


def _warn_if_not_ai_studio_key(val: str) -> None:
    """Ostrzeż, gdy to nie wygląda na klucz AI Studio.

    Klucz z aistudio.google.com to `AIzaSy…`, 39 znaków. Token z prefiksem `AQ.`
    to poświadczenie w stylu OAuth (Gemini CLI / Code Assist) — NIE zadziała jako
    `x-goog-api-key`, a Google odpowie mylącym `API_KEY_INVALID`. Bez tego
    ostrzeżenia diagnostyka schodzi na manowce (sprawdzone na żywo).
    """
    if val.startswith("AQ."):
        print("  [UWAGA] To wygląda na token OAuth (prefiks 'AQ.'), nie na klucz AI Studio.")
        print("          Klucz z aistudio.google.com/apikey ma postać 'AIzaSy…' (39 znaków).")
        print("          Google odrzuci to jako API_KEY_INVALID.")
    elif not val.startswith("AIza"):
        print(f"  [UWAGA] Nietypowy format klucza (nie zaczyna się od 'AIza', {len(val)} znaków).")
    elif len(val) != 39:
        print(f"  [UWAGA] Klucz 'AIza…' ma nietypową długość: {len(val)} zamiast 39.")


def api_key() -> str:
    """Klucz WYŁĄCZNIE ze środowiska — nigdy z argumentu (wyciekłby do listy procesów)."""
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        val = os.environ.get(var, "").strip()
        if val:
            _warn_if_not_ai_studio_key(val)
            return val
    raise SpikeError(
        "Brak klucza. Ustaw GEMINI_API_KEY (albo GOOGLE_API_KEY) w środowisku:\n"
        '  PowerShell:  $env:GEMINI_API_KEY = "..."\n'
        '  bash:        export GEMINI_API_KEY="..."'
    )


def headers(key: str, *, json_body: bool = True) -> dict:
    h = {"x-goog-api-key": key}
    if json_body:
        h["Content-Type"] = "application/json"
    return h


def gcloud_access_token() -> str:
    """Pobierz krótko żyjący token ADC bez logowania go ani zapisywania w projekcie.

    Spike celowo używa istniejącej sesji `gcloud auth application-default login`.
    Docelowa aplikacja użyje biblioteki `google-auth` do odświeżania ADC i nie będzie
    wymagała uruchomionego Google Cloud SDK.
    """
    executable = shutil.which("gcloud.cmd") or shutil.which("gcloud")
    if not executable:
        raise SpikeError(
            "Nie znaleziono Google Cloud SDK (`gcloud`). Otwórz Google Cloud SDK Shell "
            "albo dodaj jego katalog `bin` do PATH."
        )
    try:
        result = subprocess.run(
            [executable, "auth", "application-default", "print-access-token"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise SpikeError("Pobieranie tokenu ADC przekroczyło 60 sekund.") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "nieznany błąd gcloud").strip()
        raise SpikeError(
            "Nie udało się pobrać tokenu ADC. Uruchom `gcloud auth application-default "
            f"login` i spróbuj ponownie.\n{detail[:800]}"
        )
    token = result.stdout.strip()
    if not token:
        raise SpikeError("Google Cloud SDK zwrócił pusty token ADC.")
    return token


def _validate_vertex_target(project: str, location: str) -> tuple[str, str]:
    project = project.strip()
    location = location.strip().lower()
    if not re.fullmatch(r"[a-z][a-z0-9-]{4,61}[a-z0-9]", project):
        raise SpikeError(f"Nieprawidłowy identyfikator projektu Google Cloud: {project!r}")
    if location != "global" and not re.fullmatch(r"[a-z]+-[a-z]+[0-9]", location):
        raise SpikeError(f"Nieprawidłowy region Vertex AI: {location!r}")
    return project, location


def vertex_url(
    project: str,
    location: str,
    path: str,
    *,
    api_version: str = VERTEX_API_VERSION,
) -> str:
    """Zbuduj i zwaliduj URL Vertex AI / Agent Platform."""
    project, location = _validate_vertex_target(project, location)
    if api_version not in {"v1", "v1beta1"}:
        raise SpikeError(f"Nieobsługiwana wersja Vertex AI API: {api_version!r}")
    base = (
        "https://aiplatform.googleapis.com"
        if location == "global"
        else f"https://{location}-aiplatform.googleapis.com"
    )
    resource = (
        f"projects/{quote(project, safe='')}/locations/{quote(location, safe='')}/"
        f"{path.lstrip('/')}"
    )
    return f"{base}/{api_version}/{resource}"


def vertex_request(
    method: str,
    project: str,
    location: str,
    path: str,
    access_token: str,
    *,
    body: Optional[dict] = None,
    params: Optional[dict] = None,
    timeout: int = 180,
    api_version: str = VERTEX_API_VERSION,
) -> dict:
    """Wywołaj Vertex AI przez REST z tokenem ADC w nagłówku Bearer."""
    url = vertex_url(project, location, path, api_version=api_version)
    print(f"  {method} {url}")
    resp = requests.request(
        method,
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json=body,
        params=params,
        timeout=timeout,
    )
    text_preview = resp.text[:400] if resp.text else ""
    if resp.status_code >= 400:
        reason = None
        try:
            reason = _error_reason(resp.json())
        except ValueError:
            pass
        raise SpikeError(
            f"HTTP {resp.status_code} dla {method} {url}\n{text_preview}",
            status=resp.status_code,
            reason=reason,
        )
    try:
        return resp.json()
    except ValueError as exc:
        raise SpikeError(f"Odpowiedź nie jest JSON-em: {text_preview}") from exc


def dump(name: str, payload: Any) -> Path:
    """Zapisz surową odpowiedź — to jest właściwy produkt spike'u.

    Kształt drutu spisany z realnej odpowiedzi jest tym, na czym oprzemy port do
    Pythona w Fazie 2; nie zgadujemy go z dokumentacji.
    """
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{name}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"    → zapisano {path.relative_to(Path(__file__).resolve().parent)}")
    return path


def redact(obj: Any, max_b64: int = 80) -> Any:
    """Przytnij pola base64, żeby dumpy dały się czytać (klip Veo to dziesiątki MB)."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(v, str) and len(v) > max_b64 and k.lower() in (
                "data", "bytesbase64encoded", "bytes_base64_encoded",
                "videobytes", "imagebytes", "inlinedata", "thoughtsignature", "signature",
            ):
                out[k] = f"<dane binarne {len(v)} znaków, przycięte>"
            else:
                out[k] = redact(v, max_b64)
        return out
    if isinstance(obj, list):
        return [redact(v, max_b64) for v in obj]
    return obj


def request(
    method: str,
    path: str,
    key: str,
    *,
    body: Optional[dict] = None,
    params: Optional[dict] = None,
    timeout: int = 180,
) -> dict:
    """Jedno wywołanie REST. `path` bez wiodącego slasha, bez wersji API."""
    url = f"{BASE}/{API_VERSION}/{path.lstrip('/')}"
    print(f"  {method} {url}")
    resp = requests.request(
        method, url, headers=headers(key), json=body, params=params, timeout=timeout
    )
    text_preview = resp.text[:400] if resp.text else ""
    if resp.status_code >= 400:
        reason = None
        try:
            reason = _error_reason(resp.json())
        except ValueError:
            pass
        raise SpikeError(
            f"HTTP {resp.status_code} dla {method} {url}\n{text_preview}",
            status=resp.status_code,
            reason=reason,
        )
    try:
        return resp.json()
    except ValueError:
        raise SpikeError(f"Odpowiedź nie jest JSON-em: {text_preview}")


def request_raw_url(method: str, url: str, key: str, *, timeout: int = 180) -> dict:
    """Wywołanie po pełnym URL-u (operacje LRO zwracają gotową ścieżkę zasobu)."""
    print(f"  {method} {url}")
    resp = requests.request(method, url, headers=headers(key), timeout=timeout)
    if resp.status_code >= 400:
        raise SpikeError(f"HTTP {resp.status_code}: {resp.text[:400]}")
    return resp.json()


def poll(fn, *, label: str, interval: float = 10.0, timeout: float = 600.0):
    """Prosty polling z twardym deadlinem. Zwraca (wynik, sekundy)."""
    started = time.time()
    attempt = 0
    while True:
        attempt += 1
        elapsed = time.time() - started
        if elapsed > timeout:
            raise SpikeError(f"{label}: przekroczono {timeout:.0f}s bez zakończenia")
        done, value = fn()
        print(f"    [{elapsed:6.1f}s] próba {attempt}: {'GOTOWE' if done else 'w toku…'}")
        if done:
            return value, elapsed
        time.sleep(interval)


def confirm_cost(what: str, accepted: bool) -> None:
    """Bramka na operacje kosztujące realne pieniądze."""
    if accepted:
        return
    raise SpikeError(
        f"{what} kosztuje realne pieniądze na Twoim koncie Google.\n"
        "Uruchom ponownie z flagą --yes-i-accept-cost, jeśli akceptujesz."
    )


def banner(title: str) -> None:
    print()
    print("=" * 72)
    print(f"  {title}")
    print("=" * 72)


def ok(msg: str) -> None:
    print(f"  [OK] {msg}")


def fail(msg: str) -> None:
    print(f"  [BŁĄD] {msg}", file=sys.stderr)
