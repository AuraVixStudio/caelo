"""Narzędzia generowania mediów dla czatu (M20).

Grok tworzy obrazy/wideo natywnie, ale xAI **Responses API nie wystawia** serwerowego
narzędzia image-gen (jak `web_search`). Dajemy więc WŁASNE function-tools do pętli
function-calling czatu (`responses_client`), reużywając prymitywy generacji z
`backend_media` (obraz) i `genjobs` (wideo) — zero nowej logiki generacji.

- `generate_image`: SYNCHRONICZNIE (`api.generate_image` → artefakty M9). Wynik renderuje
  się inline w czacie — handler emituje ramkę WS `artifact` per obraz.
- `generate_video`: render trwa minuty → ZAKOLEJKOWANIE w `GenJobManager` (jak panel
  Video); narzędzie zwraca id zadania, user śledzi je w zakładce Video/Gallery.

Bramkowanie: oba NIE dotykają workspace (to wywołania API + zapis do katalogu mediów),
więc — jak reszta czatu — nie przechodzą przez `PermissionGate`. Koszt = BYO-key usera;
model woła je tylko na żądanie. Włączane przez `config.CHAT_MEDIA_TOOLS` (domyślnie ON).
"""

from __future__ import annotations

import base64
import logging
import os
import time
from typing import Callable, Optional

import config  # type: ignore  # repo-root (sys.path z caelo_core/__init__.py)

log = logging.getLogger(__name__)

# Maks. rozmiar obrazu uzywanego jako klatka poczatkowa image-to-video (jak vision).
_MAX_FRAME_BYTES = 12 * 1024 * 1024
# Okno "swiezosci": tylko obraz wygenerowany/dodany w ostatnich N sekund liczy sie
# jako "ten obraz" do animacji (unika animowania starego artefaktu z innej rozmowy).
_RECENT_IMAGE_WINDOW_S = 600


def _latest_project_image_data_uri(backend, project_id) -> Optional[str]:
    """Najswiezszy (ostatnie 10 min) obraz danego projektu jako data-URI, albo None.
    grok-imagine-video-1.5 to model IMAGE-TO-VIDEO, wiec "animuj to" wymaga klatki
    poczatkowej — bierzemy ostatnio wygenerowany obraz w tej rozmowie. Bledy -> None
    (fallback na text2video)."""
    try:
        store = getattr(backend, "history_store", None)
        if store is None:
            return None
        arts = store.list_artifacts(mode="image", project_id=project_id,
                                    since=time.time() - _RECENT_IMAGE_WINDOW_S, limit=1)
        if not arts:
            return None
        a = arts[0]
        path = getattr(a, "path", "") or ""
        if not path or not os.path.exists(path) or os.path.getsize(path) > _MAX_FRAME_BYTES:
            return None
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        mime = getattr(a, "mime", "") or "image/png"
        return f"data:{mime};base64,{b64}"
    except Exception:  # noqa: BLE001
        log.warning("could not load latest project image for image-to-video", exc_info=True)
        return None

MEDIA_TOOL_DEFS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": (
                "Generate one or more images from a text prompt and show them to the user in "
                "the chat. Use when the user asks to create, draw, design, render or imagine an "
                "image. The images are displayed automatically — do not also paste them as links."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string",
                               "description": "Detailed description of the image to create."},
                    "n": {"type": "integer", "minimum": 1, "maximum": 4,
                          "description": "How many images to generate (1-4). Default 1."},
                    "aspect_ratio": {"type": "string",
                                     "description": "e.g. '1:1', '16:9', '9:16'. Default 'auto'."},
                },
                "required": ["prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_video",
            "description": (
                "Generate a short video. Rendering takes a while, so the job is queued — tell the "
                "user to watch the Video or Gallery tab for the result. Use when the user asks to "
                "create or animate a video. If the user just generated or attached an image and "
                "wants to animate it, the most recent image is used as the first frame "
                "(image-to-video)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string",
                               "description": "What should happen in the video."},
                    "duration": {"type": "integer", "minimum": 1, "maximum": 12,
                                 "description": "Length in seconds (default 6)."},
                    "aspect_ratio": {"type": "string",
                                     "description": "e.g. '16:9', '9:16'. Default 'Original'."},
                },
                "required": ["prompt"],
            },
        },
    },
]

MEDIA_TOOL_NAMES: set[str] = {d["function"]["name"] for d in MEDIA_TOOL_DEFS}


def handle_media_tool(backend, name: str, args: dict,
                      emit_artifact: Callable[[dict], None]) -> str:
    """Wykonaj narzędzie mediów czatu. Zwraca KRÓTKI tekst dla modelu; wygenerowane
    obrazy emituje przez `emit_artifact` (ramka WS `artifact`, renderer pokaże inline).
    Błędy łapane → 'Error: ...' (model je widzi i może zareagować)."""
    args = args or {}
    prompt = str(args.get("prompt") or "").strip()
    if not prompt:
        return "Error: a non-empty 'prompt' is required."
    project_id = getattr(backend, "current_project_id", None)
    try:
        if name == "generate_image":
            n = max(1, min(4, int(args.get("n", 1) or 1)))
            ratio = str(args.get("aspect_ratio") or "auto")
            urls = backend.api.generate_image(prompt, n, ratio, "1k", model=None)
            results = backend.save_media_urls(
                urls, prompt, "generate", ".png", project_id=project_id,
                meta_extra={"gen_op": "text2img", "source": "chat"})
            ids = [r["artifact_id"] for r in results if r.get("artifact_id")]
            for aid in ids:
                emit_artifact({"id": aid, "kind": "image", "mime": "image/png"})
            if not ids:
                return "The image was generated but could not be saved; ask the user to retry."
            return (f"Generated {len(ids)} image(s) from the prompt and displayed them to the "
                    "user in the chat. They are already visible — briefly describe them, do not "
                    "repeat them as links.")
        if name == "generate_video":
            duration = max(1, min(12, int(args.get("duration", 6) or 6)))
            ratio = str(args.get("aspect_ratio") or "Original")
            params = {"prompt": prompt, "duration": duration,
                      "resolution": "480p", "aspect_ratio": ratio,
                      # Czat uzywa BAZOWEGO modelu (wiecej mozliwosci niz 1.5-preview).
                      "model": getattr(config, "CHAT_VIDEO_MODEL", "grok-imagine-video")}
            # grok-imagine-video-1.5 to model IMAGE-TO-VIDEO: jesli user wlasnie
            # wygenerowal/dodal obraz, uzyj go jako klatki poczatkowej (flow "animuj to");
            # inaczej text2video (moze byc nieobslugiwane -> czytelny blad z API).
            frame = _latest_project_image_data_uri(backend, project_id)
            op = "img2video" if frame else "text2video"
            if frame:
                params["image"] = frame
            job = backend.genjobs.submit(kind="video", op=op, params=params,
                                         project_id=project_id)
            extra = " using your most recent image as the first frame" if frame else ""
            return (f"Queued a video render (job {job.id[:8]}){extra}. Rendering takes a while; "
                    "tell the user to watch the Video or Gallery tab for the finished clip.")
    except Exception as exc:  # noqa: BLE001
        log.warning("chat media tool %s failed", name, exc_info=True)
        return f"Error: media generation failed: {exc}"
    return f"Error: unknown media tool {name}"
