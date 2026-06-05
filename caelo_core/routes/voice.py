"""Trasy głosowe: TTS, STT (REST batch + streaming WS) oraz pipeline rozmowy.

REST (`router`, chronione tokenem Bearer):
  POST /voice/tts  {text, voice_id, language}      -> {audio_b64, mime, path, chars, cost}
  POST /voice/stt  {audio_b64, filename, language}  -> {text, duration?, cost, ...}

Realtime / streaming (`ws_router`, token w query — jak /chat/stream):
  WS /voice/realtime?token=…&model=…
      Voice Agent xAI (M12-B4, stretch): most dwukierunkowy renderer <-> sidecar
      <-> wss://api.x.ai/v1/realtime.
  WS /voice/stt/stream?token=…&language=…
      Strumieniowe STT na żywo (M12-B1): renderer streamuje audio z mikrofonu,
      sidecar mostkuje do wss://api.x.ai/v1/stt; partiale + finalny transkrypt
      wracają tą samą ścieżką.
  WS /voice/converse?token=…
      Pipeline rozmowy głosowej (M12-B3): transkrypt (z B1/STT) -> Responses API
      (M10: live search + historia) -> TTS -> audio. Headline „Talk to Grok".

Sidecar dokłada nagłówek Authorization: Bearer <klucz> do połączeń upstream xAI
(przeglądarka nie może ustawiać nagłówków WS). Klucz NIGDY nie wychodzi do renderera.
Ramki JSON są przekazywane bez zmian w obie strony (UTF-8); pipeline rozmowy używa
wspólnego `WsStream` (ograniczona kolejka + backpressure + join workera).
"""

from __future__ import annotations

import asyncio
import base64
import json
import threading
from typing import Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

import config  # type: ignore

from caelo_core import responses_client
from caelo_core import validation as V
from caelo_core.errors import upstream_error
from caelo_core.routes._ws import WsStream
from caelo_core.state import Backend, get_backend, ws_authorized

router = APIRouter(tags=["voice"])
ws_router = APIRouter()


# --- M12-B5: koszt audio (BYO-key; czyste funkcje — testowalne w api_smoke) ---
def stt_cost(duration_s: float, *, streaming: bool = False) -> float:
    """Koszt STT z czasu nagrania. xAI: batch $0.10/h, stream na żywo $0.20/h."""
    rate = config.STT_COST_PER_HOUR_STREAM if streaming else config.STT_COST_PER_HOUR_BATCH
    return round(rate * (max(0.0, duration_s) / 3600.0), 6)


def tts_cost(n_chars: int) -> float:
    """Koszt TTS z liczby znaków (cena znakowa = strojalny szacunek; znaki dokładne)."""
    return round(config.TTS_COST_PER_1K_CHARS * (max(0, n_chars) / 1000.0), 6)


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
    chars = len(req.text)
    cost = tts_cost(chars)
    # M12-B5: koszt TTS do wspólnej historii (przeszukiwalny licznik BYO-key).
    b.record_event(mode="voice", text="", meta={"op": "tts", "chars": chars,
                                                 "cost": cost, "voice_id": req.voice_id})
    return {
        "audio_b64": base64.b64encode(audio).decode("ascii"),
        "mime": mime or "audio/mpeg",
        "path": saved.get("path"),
        "chars": chars,
        "cost": cost,
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
        result = b.api.speech_to_text(data, filename=req.filename or "speech.webm", language=req.language)
    except Exception as exc:
        raise upstream_error(exc, "Speech-to-text request to xAI failed")
    if not isinstance(result, dict):
        result = {"text": str(result)}
    # M12-B5: koszt STT z czasu (xAI zwraca `duration` w sekundach, gdy dostępne).
    try:
        duration = float(result.get("duration") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    cost = stt_cost(duration, streaming=False)
    result["cost"] = cost
    # M9-B2: transkrypt trafia do wspólnej historii huba (przeszukiwalny). Błędy połykane.
    transcript = result.get("text") if isinstance(result, dict) else None
    if transcript:
        b.record_event(mode="voice", text=transcript,
                       meta={"op": "stt", "duration": duration, "cost": cost})
    return result


# --- Wspólny most WS (transparentny proxy do upstream xAI) ---
async def _bridge_upstream(ws: WebSocket, build_url: Callable[[], str]) -> None:
    """Transparentny most renderer <-> sidecar <-> upstream xAI (M12-B1/B4).

    Wspólny szkielet dla /voice/realtime i /voice/stt/stream: po autoryzacji
    dokłada nagłówek Authorization, łączy się z xAI i przekazuje ramki JSON bez
    zmian w obie strony (UTF-8). Klucz nigdy nie wychodzi do renderera.
    """
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

    url = build_url()
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


@ws_router.websocket("/voice/realtime")
async def voice_realtime(ws: WebSocket) -> None:
    """M12-B4 (stretch): Voice Agent xAI (/v1/realtime) — pełna rozmowa dwukierunkowa."""
    def _url() -> str:
        model = ws.query_params.get("model") or config.VOICE_REALTIME_MODEL
        return f"{config.REALTIME_URL}?model={model}"

    await _bridge_upstream(ws, _url)


@ws_router.websocket("/voice/stt/stream")
async def voice_stt_stream(ws: WebSocket) -> None:
    """M12-B1: strumieniowe STT na żywo (wss://api.x.ai/v1/stt) — partiale + finał."""
    def _url() -> str:
        lang = ws.query_params.get("language")
        return f"{config.STT_STREAM_URL}?language={lang}" if lang else config.STT_STREAM_URL

    await _bridge_upstream(ws, _url)


# --- M12-B3: pipeline rozmowy głosowej (transkrypt -> Responses -> TTS) ---
#
# Dekompozycja: część STT(stream) realizuje most B1 PO STRONIE KLIENTA (renderer
# streamuje mikrofon do /voice/stt/stream, pokazuje partiale, składa finalny
# transkrypt). Ten pipeline bierze GOTOWY transkrypt i prowadzi go przez mózg huba:
# Responses API (M10: web_search/x_search + historia M9) -> TTS -> audio. Dzięki temu
# w jednej trasie nie żonglujemy dwoma socketami upstream (mniej kruche, testowalne),
# a głos jest „kolejnym frontem na ten sam mózg", nie wyspą. Barge-in = klient wysyła
# {"type":"stop"} (mowa w trakcie TTS) -> stop bieżącej tury (bez syntezowania audio).
#
# Protokół klient -> sidecar:
#   {"type":"converse","transcript":"...","model":"...","voice_id":"eve","language":"en",
#    "temperature":0.7,"search_mode":"auto|on|off","sources":["web","x"],
#    "messages":[ {role,content}, ... ],   # wcześniejsze tury (kontekst rozmowy)
#    "system_prompt":"...","speak":true}
#   {"type":"stop"}
# Sidecar -> klient: delta · tool_call · citations · usage · audio · cost · done · error
@ws_router.websocket("/voice/converse")
async def voice_converse(ws: WebSocket) -> None:
    if not ws_authorized(ws):  # P0-8: fail-closed token + Origin
        await ws.close(code=1008)
        return
    await ws.accept()
    backend = getattr(ws.app.state, "backend", None)
    if backend is None:
        await ws.send_json({"type": "error", "error": "Backend not initialized"})
        await ws.close()
        return

    current: dict = {"thread": None, "stop": None}  # single-flight (jak /chat/stream)

    async with WsStream(ws) as stream:

        def start_turn(req: dict) -> None:
            stop = threading.Event()
            current["stop"] = stop
            transcript = (req.get("transcript") or "").strip()
            model = req.get("model") or backend.read_settings().get(
                "chat_model") or config.DEFAULT_CHAT_MODEL
            voice_id = req.get("voice_id") or config.DEFAULT_VOICE
            language = req.get("language") or "en"
            speak = req.get("speak", True)
            try:
                temperature = float(req.get("temperature", 0.7))
            except (TypeError, ValueError):
                temperature = 0.7
            search_mode = (req.get("search_mode") or "off").lower()
            if search_mode not in ("auto", "on", "off"):
                search_mode = "off"
            sources = req.get("sources") or None

            messages = list(req.get("messages") or [])
            sys_prompt = (req.get("system_prompt") or "").strip()
            if sys_prompt:
                messages = [{"role": "system", "content": sys_prompt}] + messages
            messages = messages + [{"role": "user", "content": transcript}]
            tools = responses_client.build_search_tools(search_mode, sources)

            def on_delta(delta: str, _full: str) -> None:
                if not stream.emit({"type": "delta", "delta": delta}):
                    stop.set()

            def on_tool(ev: dict) -> None:
                if not stream.emit({"type": "tool_call", **ev}):
                    stop.set()

            def worker() -> None:
                try:
                    result = responses_client.stream_response(
                        messages, model=model,
                        api_key_provider=backend.get_api_key,
                        temperature=temperature, tools=tools,
                        tool_choice="required" if search_mode == "on" else None,
                        on_delta=on_delta, on_tool=on_tool, stop_flag=stop.is_set,
                    )
                    full = result.get("text") or ""
                    if result.get("citations"):
                        stream.emit({"type": "citations", "citations": result["citations"]})
                    if result.get("usage") or result.get("tool_calls"):
                        stream.emit({"type": "usage", "usage": result.get("usage") or {},
                                     "tool_calls": result.get("tool_calls", 0)})
                    # TTS odpowiedzi (chyba że przerwano barge-inem / wyłączono speak).
                    tts_chars = 0
                    tts_c = 0.0
                    if speak and full and not stop.is_set():
                        try:
                            audio, mime = backend.api.text_to_speech(full, voice_id, language)
                            tts_chars = len(full)
                            tts_c = tts_cost(tts_chars)
                            stream.emit({"type": "audio",
                                         "audio_b64": base64.b64encode(audio).decode("ascii"),
                                         "mime": mime or "audio/mpeg"})
                        except Exception as exc:  # noqa: BLE001
                            # Brak głosu nie wywraca tury — tekst już dostarczony.
                            stream.emit({"type": "warning", "warning": f"TTS failed: {exc}"})
                    stream.emit({"type": "cost", "tts_chars": tts_chars, "tts_cost": tts_c})
                    stream.emit({"type": "done", "full": full})
                    # M9-B2: cała rozmowa w jednej historii (prompt usera + koszt w meta).
                    if full or transcript:
                        backend.record_event(
                            mode="voice", text=full or "",
                            meta={"op": "converse", "prompt": transcript, "model": model,
                                  "search_mode": search_mode, "voice_id": voice_id,
                                  "tts_chars": tts_chars, "cost": tts_c,
                                  "citations": [c.get("url") for c in result.get("citations", [])]},
                        )
                except Exception as exc:  # noqa: BLE001
                    stream.emit({"type": "error", "error": str(exc)})

            t = threading.Thread(target=worker, daemon=True)
            current["thread"] = t
            stream.track(t)
            t.start()

        def _busy() -> bool:
            t = current["thread"]
            return t is not None and t.is_alive()

        try:
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                mtype = msg.get("type")
                if mtype == "stop":
                    if current["stop"] is not None:
                        current["stop"].set()  # barge-in / anuluj bieżącą turę
                elif mtype == "converse":
                    if not (msg.get("transcript") or "").strip():
                        continue
                    if _busy():
                        await stream.send({"type": "error",
                                           "error": "A turn is already in progress; send 'stop' first."})
                        continue
                    start_turn(msg)
        except WebSocketDisconnect:
            pass
        finally:
            if current["stop"] is not None:
                current["stop"].set()
