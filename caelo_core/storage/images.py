"""Dopasowanie obrazu do budżetu data-URI (send-to bus, M9-B4).

Generatory 2K/4K (np. Nano Banana) zwracają PNG-i po kilkanaście MB. Zakodowane
w base64 przekraczają `validation.MAX_IMAGE_URI`, więc `/artifacts/{id}/input-block`
odrzucał je 413 i „Send to…" nie działał na własnych wynikach użytkownika.
Zamiast błędu przygotowujemy mniejszą kopię WEJŚCIOWĄ (oryginał na dysku zostaje
nietknięty) — dokładnie tak, jak renderer robi to dla plików z dysku
(`lib/imageCompress.ts`).

Kodujemy do JPEG, nie WebP: to najszerzej wspierany format wejściowy u dostawców
(xAI vision dokumentuje jpg/png), a blok trafia zarówno do czatu, jak i do
referencji obrazu/kadru wideo.
"""

from __future__ import annotations

import io

# Zjazd jakości przy danym rozmiarze, dopiero potem zmniejszamy wymiary
# (lustro QUALITY_LADDER/SCALE_STEP z lib/imageCompress.ts).
_QUALITY_LADDER = (88, 80, 70, 60, 50)
_SCALE_STEP = 0.8
_MIN_DIMENSION = 64
_MAX_STEPS = 12
# Margines na nagłówek data-URI i zaokrąglenia base64.
_BUDGET_RATIO = 0.95


def data_uri_len(nbytes: int, mime: str) -> int:
    """Długość `data:<mime>;base64,…` dla `nbytes` bajtów (base64: 4 znaki / 3 bajty)."""
    return len(f"data:{mime};base64,") + 4 * ((nbytes + 2) // 3)


def fit_image_to_uri_budget(raw: bytes, mime: str, max_uri_chars: int) -> tuple[bytes, str]:
    """Zwróć `(bajty, mime)` mieszczące się w `max_uri_chars` po zakodowaniu w data-URI.

    Obraz w limicie wraca BEZ ZMIAN (oryginalny format). Gdy Pillow jest niedostępny
    albo nie da się zejść pod budżet, zwracamy najlepszy uzyskany wariant — walidacja
    w warstwie wyżej i tak zdecyduje o 413.
    """
    if data_uri_len(len(raw), mime) <= max_uri_chars:
        return raw, mime
    try:
        from PIL import Image
    except Exception:
        return raw, mime

    budget = int(max_uri_chars * _BUDGET_RATIO)
    try:
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            # JPEG nie ma kanału alfa — PNG z przezroczystością spłaszczamy na biało.
            if image.mode in ("RGBA", "LA", "P"):
                rgba = image.convert("RGBA")
                flat = Image.new("RGB", rgba.size, (255, 255, 255))
                flat.paste(rgba, mask=rgba.split()[-1])
                source = flat
            else:
                source = image.convert("RGB")
    except Exception:
        return raw, mime

    width, height = source.size
    best: bytes | None = None
    for step in range(_MAX_STEPS):
        frame = source if step == 0 else source.resize(
            (max(1, int(width)), max(1, int(height))), Image.LANCZOS
        )
        for quality in _QUALITY_LADDER:
            buf = io.BytesIO()
            try:
                frame.save(buf, format="JPEG", quality=quality, optimize=True)
            except Exception:
                return raw, mime
            out = buf.getvalue()
            if data_uri_len(len(out), "image/jpeg") <= budget:
                return out, "image/jpeg"
            if best is None or len(out) < len(best):
                best = out
        width *= _SCALE_STEP
        height *= _SCALE_STEP
        if width < _MIN_DIMENSION or height < _MIN_DIMENSION:
            break

    if best is not None and len(best) < len(raw):
        return best, "image/jpeg"
    return raw, mime
