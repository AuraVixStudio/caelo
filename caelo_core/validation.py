"""Walidatory i limity wejścia tras (P1-8).

Bez nich model/klient mógł przesłać np. n=10000 obrazów, gigantyczny prompt albo
ogromny/niewłaściwy data-URI. Limity są hojne (nie psują normalnego użycia), ale
chronią przed nadużyciem/OOM. Naruszenie w polu Pydantic → automatyczne 422.
"""

from __future__ import annotations

import re
from typing import Optional

# M19-B9: dozwolone poziomy reasoning_effort (CLI: low/medium/high). Wspólny słownik
# dla obu ścieżek inferencji (Responses/chat), ról subagentów i tras — leaf, bez cykli.
REASONING_EFFORTS = ("low", "medium", "high")


def normalize_effort(value) -> Optional[str]:
    """Znormalizuj reasoning_effort do `low`/`medium`/`high` albo None (M19-B9).
    Cokolwiek poza dozwolonymi (None/""/śmieć) → None, by NIE dokładać pola do
    payloadu xAI (modele nie-rozumujące mogłyby zwrócić 4xx)."""
    if not value:
        return None
    v = str(value).strip().lower()
    return v if v in REASONING_EFFORTS else None


# Limity (sekundy/sztuki/znaki).
MAX_PROMPT = 8000           # długość promptu (obraz/wideo)
MAX_IMAGES = 8              # liczba obrazów referencyjnych w jednej edycji
MAX_N = 10                  # liczba generowanych obrazów na żądanie
MAX_VIDEO_DURATION = 30     # sekundy zadania wideo
MAX_EXTEND_DURATION = 10    # dodane sekundy przy przedłużeniu
MAX_IMAGE_URI = 12 * 1024 * 1024   # ~9 MB obrazu zakodowanego w base64 (znaki)
MAX_VIDEO_URI = 64 * 1024 * 1024   # data-URI wideo (znaki)
MAX_TTS_TEXT = 8000        # długość tekstu do TTS
MAX_STT_B64 = 30 * 1024 * 1024     # ~22 MB audio w base64 (znaki)
MAX_DOCUMENT_URI = 48 * 1024 * 1024  # data-URI dokumentu (PDF/arkusz) w base64 (znaki) — M10-B4
MAX_COLLECTION_FILE_BYTES = 32 * 1024 * 1024  # surowy upload dokumentu do kolekcji — M10-B5

# Historia/artefakty huba (M9-B3) — limity zapytań GET /history /artifacts.
MAX_HISTORY_QUERY = 256    # długość frazy szukania (q, FTS)
MAX_HISTORY_LIMIT = 200    # górny limit paginacji (rekordów na stronę)
MAX_ID_LEN = 64            # długość identyfikatorów (artifact_id / project_id / mode)

# Send-to bus (M9-B4) — cap pliku artefaktu serwowanego jako blok wejściowy LLM.
# Obrazy dodatkowo przez validate_image_uri (MAX_IMAGE_URI, ~9 MB) — stricter.
MAX_INPUT_FILE_BYTES = 32 * 1024 * 1024

_IMAGE_DATA_URI = re.compile(r"^data:image/[a-zA-Z0-9.+-]+;base64,", re.IGNORECASE)


def validate_image_uri(uri: str) -> str:
    """Wymaga `data:image/*;base64,…` w rozsądnym rozmiarze."""
    if not isinstance(uri, str) or not _IMAGE_DATA_URI.match(uri):
        raise ValueError("image must be a data:image/*;base64 URI")
    if len(uri) > MAX_IMAGE_URI:
        raise ValueError(f"image too large (> {MAX_IMAGE_URI // (1024 * 1024)} MB)")
    return uri


def validate_document_uri(uri: str) -> str:
    """Wymaga `data:<mime>;base64,…` dokumentu (np. PDF/arkusz) w rozsądnym rozmiarze
    (M10-B4). Zwraca URI albo rzuca ValueError (anti-OOM przy załączniku w czacie)."""
    if not isinstance(uri, str) or not uri.startswith("data:"):
        raise ValueError("document must be a data:<mime>;base64 URI")
    if ";base64," not in uri[:128]:
        raise ValueError("document must be base64-encoded")
    if len(uri) > MAX_DOCUMENT_URI:
        raise ValueError(f"document too large (> {MAX_DOCUMENT_URI // (1024 * 1024)} MB)")
    return uri


def validate_video_ref(ref: str) -> str:
    """Dopuszcza publiczny https URL albo `data:video/*;base64,…` (z limitem)."""
    if not isinstance(ref, str) or not ref:
        raise ValueError("video reference is required")
    head = ref[:64].lower()
    if head.startswith("https://"):
        return ref
    if head.startswith("data:video/"):
        if len(ref) > MAX_VIDEO_URI:
            raise ValueError(f"video too large (> {MAX_VIDEO_URI // (1024 * 1024)} MB)")
        return ref
    raise ValueError("video must be an https URL or a data:video/*;base64 URI")
