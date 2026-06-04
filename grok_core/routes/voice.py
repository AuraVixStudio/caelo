"""Trasy głosowe: TTS, STT (REST) oraz most realtime (WebSocket).

REST (`router`, chronione tokenem Bearer):
  POST /voice/tts  {text, voice_id, language}      -> {audio_b64, mime, path}
  POST /voice/stt  multipart(file, [language])      -> {text, ...}

Realtime (`ws_router`, token w query — jak /chat/stream):
  WS /voice/realtime?token=…&model=…
  Most dwukierunkowy renderer <-> sidecar <-> wss://api.x.ai/v1/realtime.
  Sidecar dokłada nagłówek Authorization: Bearer <klucz> (przeglądarka nie może
  ustawić nagłówków WS). Ramki JSON są przekazywane bez zmian w obie strony.
"""

from __future__ import annotations

import asyncio
import base64
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

import config  # type: ignore

from grok_core import validation as V
from grok_core.errors import upstream_error
from grok_core.state import Backend, get_backend, ws_authorized

router = APIRouter(tags=["voice"])
ws_router = APIRouter()


class TTSReq(BaseModel):
    text: str = Field(..., min_length=1, max_length=V.MAX_TTS_TEXT)
    voice_id: str = Field("eve", max_length=32)
    language: str = Field("en", max_length=16)


class STTReq(BaseModel):
    audio_b64: str = Field(..., min_length=1, max_length=V.MAX_STT_B64)  # base64 (bez data:)
    filename: str = Field("speech.webm", max_length=255)
    language: Optional[str] = Field(None, max_length=16)


@router.post("/voice/tts")
def voice_tts(req: TTSReq, b: Backend = Depends(get_backend)) -> dict:
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Empty text")
    try:
        audio, mime = b.api.text_to_speech(req.text, req.voice_id, req.language)
    except Exception as exc:
        raise upstream_error(exc, "Text-to-speech request to xAI failed")
    saved = b.save_media_bytes(audio, req.text[:80], "tts", ".mp3")
    return {
        "audio_b64": base64.b64encode(audio).decode("ascii"),
        "mime": mime or "audio/mpeg",
        "path": saved.get("path"),
    }


@router.post("/voice/stt")
def voice_stt(req: STTReq, b: Backend = Depends(get_backend)) -> dict:
    # Audio przychodzi jako base64 w JSON (bez python-multipart po stronie sidecara);
    # do xAI wysyłamy je jako multipart przez `requests` w speech_to_text.
    try:
        data = base64.b64decode(req.audio_b64)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 audio")
    if not data:
        raise HTTPException(status_code=400, detail="Empty audio")
    try:
        return b.api.speech_to_text(data, filename=req.filename or "speech.webm", language=req.language)
    except Exception as exc:
        raise upstream_error(exc, "Speech-to-text request to xAI failed")


@ws_router.websocket("/voice/realtime")
async def voice_realtime(ws: WebSocket) -> None:
    if not ws_authorized(ws):  # P0-8: fail-closed token + Origin
        await ws.close(code=1008)
        return
    await ws.accept()

    backend = getattr(ws.app.state, "backend", None)
    if backend is None:
        await ws.send_json({"type": "error", "error": "Backend not initialized"})
        await ws.close()
        return
    api_key = backend.get_api_key()
    if not api_key:
        await ws.send_json({"type": "error", "error": "Not authenticated (no API key / OAuth)."})
        await ws.close()
        return

    import websockets  # dostarczane przez uvicorn[standard]

    model = ws.query_params.get("model") or config.VOICE_REALTIME_MODEL
    url = f"{config.REALTIME_URL}?model={model}"
    headers = {"Authorization": f"Bearer {api_key}"}

    # Zgodność: websockets>=14 używa `additional_headers`, starsze `extra_headers`.
    try:
        connect_cm = websockets.connect(url, additional_headers=headers, max_size=None)
    except TypeError:
        connect_cm = websockets.connect(url, extra_headers=headers, max_size=None)

    try:
        async with connect_cm as upstream:
            async def client_to_upstream() -> None:
                try:
                    while True:
                        msg = await ws.receive_text()
                        await upstream.send(msg)
                except WebSocketDisconnect:
                    pass
                except Exception:
                    pass

            async def upstream_to_client() -> None:
                try:
                    async for msg in upstream:
                        if isinstance(msg, (bytes, bytearray)):
                            msg = msg.decode("utf-8", "replace")
                        await ws.send_text(msg)
                except Exception:
                    pass

            await asyncio.gather(client_to_upstream(), upstream_to_client())
    except Exception as exc:  # noqa: BLE001
        try:
            await ws.send_json({"type": "error", "error": str(exc)})
        except Exception:
            pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass
