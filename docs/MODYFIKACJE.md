# Modyfikacje i rozszerzenia — Media, Voice, Załączniki, UI

> **Status:** WYKONANE (2026-06-03). Nadbudowa na Fazach 0–8 z [`REBUILD_PLAN.md`](REBUILD_PLAN.md).
> **Zakres:** dostosowanie paneli Image/Video do możliwości API Grok, dodanie modułu Voice
> (TTS/STT/realtime), załączanie plików w Czacie i Code, drobne poprawki UI.
> **Weryfikacja:** `npm run typecheck` (czysty) + import backendu + podgląd web. Realne wywołania
> xAI (treść, media, głos, vision) sprawdzane na maszynie użytkownika — sandbox blokuje `api.x.ai`.

Legenda: **[+]** dodane, **[~]** zmodyfikowane, **[-]** usunięte.

---

## 1. Zakładka **Image** — scalenie Generator+Edit + modele + warianty

Generowanie i edycja obrazu połączone w jeden panel: bez obrazów referencyjnych → generowanie
(`/images/generate`), po dodaniu (do 3) → edycja (`/images/edit`). Dodano wybór modelu i warianty do 10.

**Backend**
- `config.py` — **[+]** `IMAGE_MODELS = [grok-imagine-image, grok-imagine-image-quality]`, `DEFAULT_IMAGE_MODEL`.
- `api_manager.py` — **[~]** `generate_image(prompt, n, ratio, resolution, model=None)`, `edit_image(..., model=None)`, `edit_image_b64(..., model=None)` (model → `DEFAULT_IMAGE_MODEL`).
- `grok_core/routes/media.py` — **[~]** `GenerateImageReq.model`, `EditImageReq.model`; trasy `images_generate` / `images_edit` przekazują `model`.
- `grok_core/routes/models.py` — **[~]** `/models` zwraca `image[]` i `default_image`.

**Frontend**
- `components/Image.tsx` — **[+]** scalony panel (auto generate/edit, selektor modelu, warianty 1–10, aspect, resolution).
- `components/Generator.tsx`, `components/Edit.tsx` — **[-]** usunięte (zastąpione przez `Image.tsx`).
- `App.tsx` — **[~]** nav: pozycje „Generator" + „Edit" → jedna „Image".
- `lib/api.ts` — **[~]** `ModelsResp.image/default_image`, `GenerateImageBody.model`, `EditImageBody.model`.
- `lib/constants.ts` — **[+]** `IMAGE_MODELS`, `IMAGE_VARIANTS` (1–10), `EDIT_MAX_IMAGES`.
- `lib/files.ts` — **[+]** `fileToDataUri()` (współdzielony helper).

---

## 2. Zakładka **Video** — image→video, edit/extend, suwak czasu, tryby

Tryby **Generate / Edit / Extend**. Generacja: tekst→wideo lub obraz startowy (image-to-video),
suwak czasu 1–15 s. Edit/Extend: wideo źródłowe (upload data-URI lub ponowne użycie wyniku).

**Backend**
- `api_manager.py` — **[~]** `create_video_job(..., image_data_uri=None)` (kadr startowy z renderera); **[+]** `edit_video_job(prompt, video, model)` (`POST /videos/edits`), `extend_video_job(prompt, video, duration, model)` (`POST /videos/extensions`).
- `grok_core/routes/media.py` — **[~]** `VideoJobReq` (+`image`, domyślny `duration=8`); **[+]** `VideoEditReq`, `VideoExtendReq`, trasy `POST /video/edits`, `POST /video/extensions` (odpyt przez istniejące `GET /video/jobs/{id}`).

**Frontend**
- `components/Video.tsx` — **[~]** przebudowa: przełącznik trybów, suwak czasu (gen 1–15, extend 1–10), dropzone kadru/wideo, przyciski „Edit this video"/„Extend this video", auto-wybór modelu nie-`preview` dla edit/extend + podpowiedź.
- `components/ui/Slider.tsx` — **[+]** themable suwak (range, `accent-color`).
- `lib/api.ts` — **[~]** `VideoJobBody.image`; **[+]** `VideoEditBody`, `VideoExtendBody`, `editVideoJob()`, `extendVideoJob()`.
- `lib/constants.ts` — **[~]** `VIDEO_RESOLUTIONS`, `VIDEO_RATIOS`; **[+]** `VIDEO_DURATION_MIN/MAX/DEFAULT`, `EXTEND_DURATION_MIN/MAX/DEFAULT`; **[-]** `VIDEO_DURATIONS`.

---

## 3. Moduł **Voice** — TTS / STT / Realtime

Nowa zakładka **Voice** (Speak / Transcribe / Live) + integracja w Czacie (głośnik przy
odpowiedziach Grok, mikrofon w polu wpisywania).

**Backend**
- `config.py` — **[+]** `VOICE_VOICES` (eve/ara/rex/sal/leo), `DEFAULT_VOICE`, `VOICE_REALTIME_MODEL`, `REALTIME_URL`.
- `api_manager.py` — **[+]** `text_to_speech(text, voice_id, language)` (`POST /tts` → bajty), `speech_to_text(audio_bytes, filename, language)` (`POST /stt`, multipart).
- `grok_core/state.py` — **[+]** `save_media_bytes(data, prompt, mode, ext)` (zapis audio TTS + historia).
- `grok_core/routes/voice.py` — **[+]** nowy plik: `TTSReq`, `STTReq`, `POST /voice/tts`, `POST /voice/stt` (audio base64 → multipart do xAI), WS `/voice/realtime` (proxy do `wss://api.x.ai/v1/realtime`, dokłada Bearer).
- `grok_core/routes/models.py` — **[~]** `/models` zwraca `voices[]`, `default_voice`, `realtime_model`.
- `grok_core/server.py` — **[~]** rejestracja `voice.router` (token) + `voice.ws_router` (token w query).
- `grok_core/requirements.txt` — **[~]** dopisane `websockets>=12.0` (klient mostu realtime).

**Frontend**
- `lib/audio.ts` — **[+]** `MicRecorder`, `arrayBufferToBase64`/`base64ToArrayBuffer`/`blobToBase64`, `playBase64Audio`.
- `lib/realtime.ts` — **[+]** `RealtimeSession` (przechwyt mikrofonu PCM16 24 kHz, `input_audio_buffer.append`, odtwarzanie `*audio.delta`, transkrypcje, server VAD).
- `components/Voice.tsx` — **[+]** panel z trybami Speak/Transcribe/Live.
- `App.tsx` — **[~]** nav: pozycja „Voice" (ikona mikrofonu).
- `components/ChatView.tsx` — **[~]** `speakMessage()` (TTS odpowiedzi) + `toggleMic()` (dyktowanie STT) + przyciski.
- `lib/api.ts` — **[+]** `TTSBody`/`TTSResp`/`textToSpeech`, `STTBody`/`STTResp`/`speechToText`, `voiceRealtimeUrl`; **[~]** `ModelsResp` (voices/default_voice/realtime_model).
- `lib/constants.ts` — **[+]** `VOICES`, `DEFAULT_VOICE`, `VOICE_LANGUAGES`.

---

## 4. Załączanie plików — **Chat** i **Code**

Obrazy → multimodalne part-y `image_url` (vision); pliki tekstowe/kodu → wklejane do treści promptu.
Limity: obraz 12 MB, tekst 256 KB; pliki binarne pomijane.

**Backend (tylko agent Code — czat nie wymaga zmian)**
- `grok_core/routes/agent.py` — **[~]** odbiór `images` z ramki `message`, przekazanie do `run_turn`.
- `grok_core/agent/session.py` — **[~]** `run_turn(..., images=None)` buduje treść multimodalną wiadomości użytkownika.

**Frontend**
- `lib/attachments.ts` — **[+]** `fileToAttachment()`, `toApiMessages()` (czat), `imageUris()`, `inlineTextFiles()`.
- `components/Attachments.tsx` — **[+]** `AttachButton` (spinacz) + `AttachmentChips` (miniatura/nazwa + usuwanie).
- `lib/api.ts` — **[+]** `ChatAttachment`, `ContentPart`, `ApiChatMessage`; **[~]** `ChatMessage.attachments`, `ChatStreamPayload.messages: ApiChatMessage[]`.
- `components/ChatView.tsx` — **[~]** stan `attachments`, `addFiles`/`removeAttachment`, `send` → `toApiMessages`, miniatury w dymku, wysyłka samego obrazu bez tekstu.
- `components/code/AgentPanel.tsx` — **[~]** stan `attachments`, wysyłka `images` + inline tekstu, chipy w wpisie „You".
- `lib/agentClient.ts` — **[~]** `sendMessage(text, model, images = [])`.

---

## 5. Poprawki UI

- `components/ui/Tooltip.tsx` — **[~]** warianty `bottom-end` / `top-end` (tooltip wyrównany do prawej krawędzi — przeciw ucinaniu przy krawędzi okna).
- `components/ui/IconButton.tsx` — **[~]** rozszerzony typ `tooltipSide`.
- `components/ChatView.tsx` — **[~]** `tooltipSide="bottom-end"` dla „System & temperature"; **[+]** zwijanie listy rozmów (`usePanelRef` + przycisk „Hide/Show chats", synchronizacja przez `onResize`).
- `components/CodeView.tsx` — **[~]** `tooltipSide="bottom-end"` dla Git / Terminal / Agent permissions.

---

## Nowe pliki (skrót)

| Plik | Rola |
|---|---|
| `grok_core/routes/voice.py` | TTS/STT (REST) + most realtime (WS) |
| `desktop/src/renderer/src/components/Image.tsx` | scalony panel obrazu |
| `desktop/src/renderer/src/components/Voice.tsx` | panel głosu (Speak/Transcribe/Live) |
| `desktop/src/renderer/src/components/Attachments.tsx` | przycisk + chipy załączników |
| `desktop/src/renderer/src/components/ui/Slider.tsx` | suwak (range) |
| `desktop/src/renderer/src/lib/audio.ts` | nagrywanie mikrofonu + base64 + odtwarzanie |
| `desktop/src/renderer/src/lib/realtime.ts` | klient realtime voice |
| `desktop/src/renderer/src/lib/attachments.ts` | model i helpery załączników |
| `desktop/src/renderer/src/lib/files.ts` | `fileToDataUri` |

## Nowe endpointy / WebSockety

| Metoda | Ścieżka | Opis |
|---|---|---|
| POST | `/images/generate`, `/images/edit` | (istniejące) + parametr `model` |
| POST | `/video/edits` | edycja wideo |
| POST | `/video/extensions` | przedłużenie wideo |
| POST | `/voice/tts` | tekst→mowa (zwraca audio base64) |
| POST | `/voice/stt` | mowa→tekst (audio base64 → multipart do xAI) |
| WS | `/voice/realtime` | most do `wss://api.x.ai/v1/realtime` |
| GET | `/models` | dodatkowo: `image`, `voices`, `default_image`, `default_voice`, `realtime_model` |

---

## Do potwierdzenia na maszynie z poświadczeniami xAI

1. **Zależności backendu:** `grok_core\.venv\Scripts\pip install -r requirements.txt` (doszło `websockets`; STT celowo **nie** wymaga `python-multipart` — audio idzie jako base64 w JSON).
2. **`grok-imagine-image-quality`** — potwierdzić dokładne ID modelu na koncie (domyślny `grok-imagine-image` jest bezpieczny).
3. **Video Edit/Extend** — nie działa na modelu `…-1.5-preview` (zwraca 400); UI auto-wybiera `grok-imagine-video`. Pole `output.upload_url` celowo pominięte (działająca generacja go nie wysyła).
4. **Image→Video** — potwierdzić, że `/videos/generations` przyjmuje `image` jako data-URI.
5. **STT** — nagranie idzie jako WebM/Opus (MediaRecorder); jeśli API odrzuci ten format, przełączyć na WAV.
6. **Realtime** — nazwy zdarzeń (`session.update`, `input_audio_buffer.append`, `response.output_audio.delta`, `*audio_transcript.delta`) i format `pcm16` 24 kHz wg konwencji OpenAI Realtime, którą odwzorowuje xAI — potwierdzić na żywym połączeniu.
7. **Vision (załączniki obrazów)** — wymaga modelu multimodalnego (grok-4.x); obrazy w historii czatu zapisują się jako data-URI w `localStorage`.
