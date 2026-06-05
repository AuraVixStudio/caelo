# PLAN_M12_GLOS.md — Głos (rozpis zadań)

> **STATUS (2026-06-05): ✅ KOMPLETNY.** B1–B5 + F1–F5 zrobione. Backend: `routes/voice.py`
> (TTS + STT batch/stream + pipeline rozmowy + koszt) na `responses_client` (M10) + `WsStream`.
> Frontend: dyktowanie w czacie i agencie (`useDictation`), tryb **Talk** (`lib/converse.ts` +
> `lib/audioStream.ts`), read-aloud (`useTts`), ustawienia głosu/języka, licznik kosztu
> (`lib/audioCost.ts`). Selfchecki: `api_smoke.py` (pipeline rozmowy + barge-in + koszt + auth
> nowych tras WS), Vitest `audioCost.test.ts`/`voice.test.ts`. **Weryfikacja realnego xAI**
> (STT-stream/TTS/converse/realtime, mikrofon) — na maszynie usera (sandbox TLS blokuje
> `api.x.ai`; selfchecki mockują xAI — zgodnie z „Verification limits" w CLAUDE.md).
>
> Rozpis milestone'u **M12** z `PLAN_ROZBUDOWY.md`. Cel M12: głos jako pełnoprawny sposób
> sterowania hubem — **dyktowanie do dowolnego trybu**, **rozmowa głosowa z Grokiem** (z
> narzędziami/live search z M10) i **czytanie odpowiedzi na głos** (TTS). Wszystko natywnie
> na xAI Voice APIs.
>
> Tagi: **[P0]** krytyczne, **[P1]** ważne. Wysiłek: S≈dni, M≈1–2 tyg., L≈3–4 tyg.

---

## 0. Co wystawia xAI (zweryfikowane) i jak to spina się z hubem

- **STT:** `POST /v1/stt` (plik/URL, batch, $0.10/h) + `wss://api.x.ai/v1/stt` (strumień na żywo,
  $0.20/h); timestampy słów, diaryzacja, wielokanałowość.
- **TTS:** 5 głosów (Eve/Ara/Leo/Rex/Sal), 20+ języków z auto-detekcją (w tym polski), synteza
  bliska real-time.
- **Voice Agent:** `/v1/realtime` — pełna rozmowa dwukierunkowa (osobna powierzchnia).
- **„Tylko Grok" potwierdzone:** całość natywnie na xAI — żadnego browsera/OS speech ani third-party.

### Decyzje przekrojowe (przeczytaj przed kodowaniem)
- **Klucz zostaje w sidecarze.** Audio płynie **renderer → sidecar (bridge) → xAI**. Renderer nie
  dotyka klucza ani `wss` xAI. Mic capture w rendererze (Electron już zezwala na `media` w
  `main/index.ts`). Bridge na wzór `WsStream` (bounded queue, worker join, scrubbed env).
- **Dyktowanie = STT streaming** wstrzykiwane do *aktywnego* trybu (czat, agent, paleta komend,
  prompt edycji obrazu) — to realizacja obietnicy „steruj hubem głosem".
- **Rozmowa = pipeline** STT(stream) → **Responses (M10, z narzędziami/live search/historią)** → TTS.
  Domyślnie pipeline, bo wpina głos w mózg huba (kontekst, narzędzia, historia M9). **Voice Agent
  `/v1/realtime`** = opcjonalny tryb niskolatencyjny (stretch), nie domyślny.
- **Read-aloud (TTS)** dowolnej odpowiedzi/artefaktu tekstowego — tani UX + dostępność.
- **Koszt:** STT min (batch/stream), TTS znaki → licznik (BYO-key, jak M10-B6/M11-B5).
- **UTF-8 wszędzie** (polski w STT/TTS) — ta sama dyscyplina co w `chat_completion_stream`.
- **UI po angielsku** (konwencja repo): „Hold to talk", „Talk to Grok", „Read aloud", „Voice".

---

## 1. Backend (`grok_core`)

### ✅ M12-B1 [P0] Most STT (streaming + batch)  — M
- **Cel:** mowa użytkownika → tekst, na żywo i z plików.
- **Zakres:** bridge sidecar: realtime przez `wss://api.x.ai/v1/stt` (audio z renderera → xAI,
  partial+final transcripty z powrotem przez `WsStream`); batch `POST /v1/stt` dla wgranych plików.
  Wstrzyknięcie auth (precedencja klucza); UTF-8; scrubbed env. Klucz nigdy nie wychodzi do renderera.
- **DoD:** mówię → strumień partiali, na końcu finalny transkrypt; wgrany plik audio → transkrypt;
  polski poprawny.
- **Selfcheck:** rozszerz `api_smoke.py` — zamockowany STT WS/REST: transcripty UTF-8, enforcement
  tokenu, klucz nie wyciekający do odpowiedzi renderera.
- **✅ Zrobione:** `WS /voice/stt/stream` — **transparentny most** (wspólny `_bridge_upstream`
  z `/voice/realtime`) dokleja `Authorization` i przekazuje ramki w obie strony (UTF-8); batch
  `POST /voice/stt` (istniał) + koszt z `duration`. Most jest czystym proxy (nie `WsStream` —
  ten jest dla blokujących workerów; pasthrough async go nie potrzebuje). **Odchylenie/uwaga:**
  dokładny protokół `wss://…/stt` (nazwy zdarzeń partial/final, kodek, sample rate) to **otwarte
  pytanie planu §5** — most jest agnostyczny (przekazuje ramki), a renderer (`parseStt` w
  `lib/converse.ts`) parsuje warianty defensywnie; do potwierdzenia na żywo. Selfcheck:
  `api_smoke` — `WS /voice/stt/stream (bad token) rejected` (fail-closed).

### ✅ M12-B2 [P0] Most TTS  — S/M
- **Cel:** tekst → naturalna mowa do odtworzenia.
- **Zakres:** trasa `/tts`: tekst → audio; wybór głosu (5), język auto/jawnie; strumień audio do
  odtwarzania; konfiguracja near-real-time. Walidacja długości (`validation.py`), https/size cap.
- **DoD:** tekst → odtwarzalne audio w wybranym głosie; polski tekst → polska mowa.
- **Selfcheck:** `api_smoke` — trasa TTS, parametr głosu honorowany, bajty audio zwrócone, token.
- **✅ Zrobione:** `POST /voice/tts` (`api_manager.text_to_speech`, 5 głosów, język) — istniał;
  **dodano** licznik znaków + koszt (B5) w odpowiedzi (`chars`/`cost`) i meta historii. Walidacja
  `MAX_TTS_TEXT` w `TTSReq`. **Odchylenie:** TTS zwraca **pełny** MP3 (nie chunked stream) —
  odtwarza się natychmiast przez `<audio>`/`playBase64Audio`; near-real-time streaming chunków
  odłożony (niepotrzebny dla UX read-aloud/Talk). Selfcheck: `api_smoke` — token (401/403),
  pusty tekst (422), `TTSReq` accept.

### ✅ M12-B3 [P0] Pipeline rozmowy głosowej  — M
- **Cel:** mówisz → Grok myśli (z narzędziami) → odpowiada głosem.
- **Zakres:** orkiestracja STT(stream) → `responses_client` (M10, z `web_search`/`x_search`,
  historią M9) → TTS → odtwarzanie. Turn-taking + barge-in (mowa usera przerywa TTS). Zapis rozmowy
  do historii (M9). `{"type":"stop"}` przerywa cały pipeline.
- **DoD:** pytanie głosem → odpowiedź na głos, z dostępnymi cytowaniami live search w transkrypcie;
  rozmowa w jednej historii; mowa w trakcie TTS przerywa odtwarzanie.
- **Selfcheck:** mock pipeline — STT tekst → wywołanie responses → TTS; stop przerywa; event balans.
- **✅ Zrobione:** `WS /voice/converse` na `WsStream` + `responses_client.stream_response`
  (tools z `build_search_tools`) → `text_to_speech` → ramka `audio`; `tool_call`/`citations`/
  `usage`/`cost`/`done`; single-flight + `{"type":"stop"}` (barge-in) przerywa turę PRZED TTS;
  cała rozmowa do historii M9 (`mode="voice"`, op `converse`). **Decyzja architektury (odchylenie):**
  część **STT(stream) jest po stronie klienta** (`lib/converse.ts` używa mostu B1 do partiali +
  finalnego transkryptu), a pipeline bierze **gotowy transkrypt** → mózg → głos. Dzięki temu w
  jednej trasie nie żonglujemy dwoma socketami upstream (mniej kruche, w pełni mockowalne), a głos
  to „kolejny front na ten sam mózg" (M10/M9), nie wyspa. Selfcheck `api_smoke._unit_voice_converse`:
  delty→full, ramka `audio` = base64 zsyntetyzowanych bajtów, koszt liczy znaki TTS, `done` z full,
  cytowania przekazane, **barge-in pomija TTS** (brak ramki `audio`, zerowy koszt + `done`).

### ✅ M12-B4 [P1] Voice Agent `/v1/realtime` (opcjonalny, niskolatencyjny)  — L *(stretch)*
- **Cel:** najniższa latencja „rozmowy telefonicznej" z Grokiem.
- **Zakres:** bridge sesji `/v1/realtime`; osobna powierzchnia. Świadomie bez głębokiej integracji
  z narzędziami/historią (to ma pipeline B3).
- **DoD:** działa płynna rozmowa dwukierunkowa.
- **Selfcheck:** cykl życia sesji (mock). **Uwaga:** stretch — rób tylko jeśli pipeline za wolny.
- **✅ Zrobione (już istniał):** `WS /voice/realtime` (most do `wss://…/v1/realtime`) + tryb
  **Live** w UI (`RealtimeSession` w `lib/realtime.ts`). W M12 zrefaktoryzowany na wspólny
  `MicCapture` (`lib/audioStream.ts`) — jeden skeleton przechwytywania mikrofonu dla realtime i
  Talk (B3). Selfcheck: `WS /voice/realtime (bad token) rejected`.

### ✅ M12-B5 [P1] Licznik kosztów audio  — S
- **Cel:** transparentność BYO-key.
- **Zakres:** minuty STT (batch/stream) + znaki TTS → meta historii (M9) + `/usage`.
- **DoD:** użycie głosu zapisane i widoczne per sesja/projekt.
- **Selfcheck:** licznik rośnie po STT/TTS.
- **✅ Zrobione:** czyste funkcje `stt_cost`/`tts_cost` (stawki w `config.py`: STT batch $0.10/h,
  stream $0.20/h; TTS znaki — koszt znakowy to **strojalny szacunek**, znaki dokładne). Koszt w
  odpowiedziach `/voice/tts` (`chars`/`cost`) i `/voice/stt` (`cost` z `duration`) + ramka `cost`
  w `/voice/converse`; zapis do meta historii M9. **Odchylenie:** repo **nie ma trasy `/usage`**
  (jak zauważono w M11) — koszt zapisany w rekordach historii i zwracany w odpowiedziach; renderer
  akumuluje per sesja (`lib/audioCost.ts`). Selfcheck: `api_smoke` — stawki, monotoniczność,
  zerowanie ujemnych; ramka `cost` w pipeline.

---

## 2. Frontend (`desktop/src/renderer`)

### ✅ M12-F1 [P0] Dyktowanie do dowolnego trybu  — M
- **Cel:** „steruj hubem głosem" — najtańszy duży efekt.
- **Zakres:** push-to-talk / toggle mikrofonu w composerze czatu, prompcie agenta, palecie komend,
  prompcie edycji obrazu. Partiale STT na żywo; finalny tekst wstrzyknięty do pola. Buduj na `components/ui/`.
- **DoD:** przytrzymaj mic w czacie → mów → tekst pojawia się w polu; działa w ≥2 trybach.
- **Test:** Vitest — stan wstrzykiwania transkryptu.
- **✅ Zrobione:** `useDictation` (toggle STT) wpięty w **czat** (`ChatView`, istniał) i **agenta**
  (`code/AgentPanel`, dodane) — **2 tryby** (DoD spełniony). Wspólny helper `appendDictation`
  (czysty) wstrzykuje transkrypt do pola. Dyktowanie używa **batch STT** (nagraj→transkrybuj);
  partiale na żywo są w trybie **Talk** (F2). Test Vitest: `voice.test.ts` — `appendDictation`
  (puste pole, doklejanie po spacji, no-op dla pustego). **Uwaga:** paleta komend / prompt edycji
  obrazu pominięte (≥2 tryby = DoD) — łatwe do dołożenia tym samym hookiem.

### ✅ M12-F2 [P0] Tryb rozmowy głosowej  — M
- **Cel:** „Talk to Grok" — mów i słuchaj.
- **Zakres:** tryb „Talk": mic in, strumieniowana odpowiedź, odtwarzanie TTS z falą/wskaźnikiem;
  barge-in (mowa przerywa). Stany: listening / thinking / speaking.
- **DoD:** rozmawiam z Grokiem, słyszę odpowiedź, przerywam mową.
- **Test:** Vitest — maszyna stanów rozmowy.
- **✅ Zrobione:** tryb **Talk** w `Voice.tsx` na `ConversePipeline` (`lib/converse.ts`): mikrofon →
  STT-stream (B1) → `/voice/converse` (B3) → tekst na żywo + odtwarzanie TTS. Stany **idle →
  connecting → listening → thinking → speaking** (kolorowa kropka), partial bieżącej wypowiedzi,
  log tur, opcjonalny **Live search** (M10) + cytowania, barge-in (mowa przerywa odtwarzanie).
  Test Vitest `voice.test.ts`: `parseStt` (warianty partial/final/is_final, gołe `{text}`, błędy).
  **Uwaga:** echo (TTS↔mic) mitygowane `echoCancellation` — zob. otwarte pytanie §5.

### ✅ M12-F3 [P0] Read-aloud  — S
- **Cel:** odsłuchaj dowolną odpowiedź/tekst.
- **Zakres:** przycisk „Read aloud" na wiadomości czatu / artefakcie tekstowym → TTS; wybór głosu.
- **DoD:** klik „Read aloud" na odpowiedzi → słyszę ją.
- **Test:** Vitest — stan odtwarzania.
- **✅ Zrobione (już istniał):** `useTts` + przycisk Volume2/Square na wiadomości asystenta w
  `ChatView` (klik = czytaj / ponowny klik = stop, `speakingIdx`). W M12 **podpięty głos z ustawień**
  (F4): `defaultVoice` z `settings.voice` (fallback `/models`). Koszt TTS doliczany do licznika sesji.

### ✅ M12-F4 [P1] Wybór głosu / języka + ustawienia  — S
- **Cel:** personalizacja audio.
- **Zakres:** wybór głosu (Ara/Eve/Leo/Rex/Sal), język auto/jawnie, domyślne w ustawieniach.
- **DoD:** zmiana głosu zmienia wyjście; polski wybieralny.
- **Test:** Vitest — stan ustawień.
- **✅ Zrobione:** karta **Voice** w `Settings.tsx` (głos + język, zapis przez `/settings`);
  backend `settings.py` przyjmuje/zwraca `voice`/`voice_language` (zapis do `grok_settings.json`,
  walidacja głosu wobec `VOICE_VOICES`). Czytane przez read-aloud (czat) i Talk; per-tryb selecty
  w `Voice.tsx` też działają. Polski w `VOICE_LANGUAGES`. Selecty głosu/języka są wyłączane w
  trakcie aktywnej rozmowy.

### ✅ M12-F5 [P1] Wskaźnik kosztu audio  — S
- **Cel:** user widzi koszt głosu (BYO-key).
- **Zakres:** badge: minuty STT + znaki/koszt TTS per sesja.
- **DoD:** koszt widoczny.
- **Test:** Vitest — formatowanie.
- **✅ Zrobione:** badge w `Voice.tsx` (np. „STT 1m 20s · TTS 340 chars · ~$0.0123") nad trybami,
  akumulowany per sesja ze wszystkich trybów (Speak→TTS, Transcribe→STT batch, Talk→STT-stream +
  TTS). Czysty model + formater `lib/audioCost.ts` (`recordStt`/`recordTts`/`formatAudioUsage`,
  stawki mirror `config.py` w `AUDIO_COST`). Test Vitest `audioCost.test.ts`: stawki, akumulacja,
  preferencja kosztu z backendu, formatowanie, pusty dla zera.

---

## 3. Kolejność i zależności

```
B1 (STT)  ──►  F1 (dyktowanie)            ← najtańszy „wow"
B2 (TTS)  ──►  F3 (read-aloud)
B1+B2+M10 ──►  B3 (pipeline rozmowy)  ──►  F2 (tryb Talk)   ← headline
B4 (/v1/realtime)  ── stretch
B5 (koszt)  ──►  F5
F4 (głos/język) ── kiedykolwiek po B2
```

- **Fundament:** `B1` (STT) + `B2` (TTS) — bez nich nic.
- **Pierwszy „wow" (tani):** `B1→F1` — dyktowanie wstrzykiwane do dowolnego trybu. To dosłownie
  „steruj hubem głosem" i działa nawet bez pełnej rozmowy.
- **Headline:** `B1+B2+M10 → B3 → F2` — rozmowa z Grokiem, który w trakcie korzysta z live searcha
  (M10) i pamięta kontekst (M9). To pokazuje, że głos to *kolejny front na ten sam mózg*, nie wyspa.
- `B4` (`/v1/realtime`) tylko jeśli pipeline okaże się za wolny — nie rób przedwcześnie.

## 4. Definicja ukończenia M12 (całość)  — ✅ SPEŁNIONA

1. ✅ **Dyktowanie** działa w ≥2 trybach (czat + agent): mowa → tekst (batch STT; partiale na żywo
   w trybie Talk).
2. ✅ **Rozmowa głosowa** (Talk): pytanie głosem → odpowiedź na głos przez pipeline z M10
   (narzędzia/live search + cytowania), **barge-in** działa, rozmowa w jednej historii (M9).
3. ✅ **Read-aloud** dowolnej odpowiedzi w wybranym głosie (z ustawień); **polski** w `VOICE_LANGUAGES`.
4. ✅ Ustawienia głosu/języka (karta Voice); **licznik kosztu audio** (BYO-key, badge per sesja).
5. ✅ Klucz nigdy nie opuszcza sidecara (mosty dokładają `Authorization`); audio mostkowane
   renderer→sidecar→xAI; **fail-closed** (nowe trasy WS odrzucają zły token); UTF-8; selfchecki
   przechodzą (`api_smoke`/`handshake_check` + typecheck); hardening M1/M5–M6 bez regresji.

> **Weryfikacja na maszynie usera (CLAUDE.md „Verification limits"):** realne ścieżki xAI
> (STT-stream/TTS/converse/realtime) + mikrofon wymagają klucza/sieci i są weryfikowane u usera —
> sandbox TLS blokuje `api.x.ai`, a selfchecki mockują xAI. **Vitest** (`audioCost`/`voice`) jest
> napisany, ale wymaga `npm install -D vitest` (devDeps offline — patrz CLAUDE.md „Commands").
> **Otwarte do potwierdzenia na żywo (§5):** dokładny protokół/sample rate `wss://…/stt`.

## 5. Otwarte pytania techniczne

- **Pipeline vs `/v1/realtime` jako domyślny tryb rozmowy:** pipeline (integracja z narzędziami/
  historią, wyższa latencja) vs realtime (najniższa latencja, osobna powierzchnia). Rekomendacja:
  pipeline domyślnie; realtime później jako opcja „szybka rozmowa".
- **Format audio renderer→sidecar:** jaki kodek/próbkowanie wymaga STT xAI (PCM? opus? sample rate)?
  Zweryfikuj na docs — decyduje o tym, jak renderer pakuje chunki z mikrofonu.
- **Barge-in / echo:** przy jednoczesnym TTS i mikrofonie potrzebne wyciszanie/echo-cancellation
  (Web Audio/Chromium) — zaplanuj, bo inaczej Grok „usłyszy sam siebie".
- **Uprawnienia mikrofonu cross-platform:** masz `media` w `main/index.ts`; potwierdź uprawnienia
  systemowe na macOS, gdy dojdzie M15.
- **Diaryzacja/timestampy (transkrypcja nagrań):** STT to wspiera — osobny use-case (transkrybuj
  plik/nagranie do tekstu/artefaktu). W M12 (mały dodatek do B1) czy później?
