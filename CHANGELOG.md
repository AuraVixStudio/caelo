# Changelog

All notable changes to **Caelo** are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- `agent_selfcheck` podstawiał atrapę HTTP w `caelo_core/agent/llm.py`, który jest dziś
  cienkim delegatem — `requests` żyje w adapterze `providers/xai/tools.py`. Test wywalał
  się na `AttributeError` i przerywał cały self-check.
- `headless_check` i zależny od niego `acp_check` używały stubu backendu bez
  `get_openai_api_key`, którego `AgentRunner._credential` wymaga od czasu dodania OpenAI.
  Tura padała, a asercja raportowała mylący brak pliku zamiast prawdziwej przyczyny.
- Testy używające `tmp_path` przewracały się na `PermissionError`, gdy systemowy
  `pytest-of-<user>` zostanie z uszkodzonym ACL-em (naprawa wymaga podniesionych
  uprawnień). `conftest.py` wykrywa nieczytelną bazę i kieruje pytest na własną.
- `requirements-dev.txt` prosił o `httpx`, podczas gdy `starlette.testclient` w tej wersji
  wymaga `httpx2`. Bez niego testy tras (`test_phase3_queue_storage`, `test_phase7_hardening`)
  nie zbierały się w ogóle.
- Spec PyInstallera wyklucza `starlette.testclient`/`fastapi.testclient` oraz `httpx2`,
  `httpcore2` i `truststore`. Sama obecność klienta testowego w venv dokładała ~3 MiB
  martwego kodu do instalatora — sidecar rozmawia z siecią wyłącznie przez `requests`.

## [2.0.8] — 2026-09-01

### Added
- Ustawienia mają podkarty dostawców (xAI / Grok, Google, OpenAI, General), więc
  logowanie i klucze każdego dostawcy są osobno zamiast jednej długiej listy kart.
- Domyślne modele czatu i agenta wybiera się w zakładce General z katalogu **wszystkich**
  dostawców, pogrupowanego per dostawca; nowa preferencja `chat_provider` zapamiętuje,
  do kogo należy wybrany model czatu (dotąd wiedział to tylko moduł Code).
- Obrazy w bibliotece referencji można usunąć — kafelek prosi o potwierdzenie, bo plik
  znika z dysku bezpowrotnie.

- Generowanie, edycja wieloma obrazami referencyjnymi i wariacje OpenAI przez
  `gpt-image-2`, z wyborem dokładnego rozmiaru, jakości, PNG/JPEG/WebP, tła oraz
  poziomu moderacji `low`/`auto`.
- Wyniki OpenAI Images API są dekodowane i zapisywane przez istniejącą kolejkę,
  historię oraz Galerię, bez tworzenia osobnego magazynu mediów.
- OpenAI jako trzeci dostawca w modułach Chat i Code/Agent, z szyfrowanym kluczem API,
  migracją sejfu do schematu v2 oraz wyborem modeli GPT-5.6 Terra, Sol i Luna.
- Adapter OpenAI Responses API ze streamingiem UTF-8, reasoning, cytowaniami, opcjonalnym
  wyszukiwaniem WWW i wymuszonym `store: false`.
- Function calling OpenAI w agencie zachowuje natywne `call_id`, równoległe wywołania,
  zaszyfrowany stan reasoning oraz wszystkie istniejące bramki uprawnień Caelo.
- Wersjonowany cennik modeli OpenAI i koszt wyliczany z rzeczywistych liczników tokenów,
  z rozdzieleniem tokenów cache; nieznany model nie jest przedstawiany jako koszt zerowy.
- Estymacja kosztu `gpt-image-2` odwzorowująca oficjalny kalkulator rozmiaru i jakości;
  po wykonaniu zadania estymacja jest zastępowana kosztem policzonym z `usage` Images API.
- Test kontraktu rzeczywistych błędów OpenAI obejmujący auth, nieznany model, rate limit,
  wyczerpaną kwotę, moderację i timeout, bez zapisywania klucza lub surowej odpowiedzi.
- Szyfrowany sejf poświadczeń w procesie głównym Electron (`safeStorage`) dla kluczy
  xAI/Google/OpenAI i tokenów OAuth oraz osobny, uwierzytelniony kanał pamięciowy do sidecara.
- Migracja schematu historii do wersji 4 z opcjonalnym `generation_output_id`, kopią
  bezpieczeństwa SQLite przed zmianą oraz skryptem weryfikującym migrację na kopii bazy.
- Testy hardeningu obejmujące migrację plaintextu, rozdzielenie tokenów sesji i sekretów,
  trwałość sejfu oraz brak zapisu poświadczeń przez backend Python.
- Moduł Chat obsługuje Google Gemini / Vertex AI obok xAI: odpowiedź jest
  strumieniowana przez SSE, a historia rozmowy może zawierać obrazy oraz dokumenty PDF.
- Dostawca i model czatu są wybierane i zapamiętywane osobno dla każdej rozmowy.
- Rejestr możliwości obejmuje modele czatowe Gemini 2.5 i 3.x wraz z obsługiwanymi
  poziomami rozumowania oraz parametrami generowania.
- Moduł Code może używać xAI albo Google Gemini. Wspólny kontrakt wywołań narzędzi
  zachowuje bramkę zatwierdzania, checkpointy, cofanie zmian, limit pętli i subagentów.
- Sesje agenta zapisują dostawcę razem z modelem, a panel Code pozwala przełączyć
  provider i pokazuje wyłącznie modele obsługujące function calling.

### Changed
- Katalog modeli zweryfikowany 2026-09-01 wobec dokumentacji dostawców oraz żywej listy
  publisher models Vertex AI: usunięto `grok-4` wycofany 2026-05-15 (slug milcząco
  przekierowuje na `grok-4.3` i jest po jego cenach), model głosowy przypięto do wersji
  `grok-voice-think-fast-2.0` zamiast aliasu `-latest`, a `gemini-2.5-flash-image`
  oznaczono jako `deprecated` przed wyłączeniem zapowiedzianym na 2026-10-02.
- Okna kontekstu w mierniku agenta odpowiadają katalogom dostawców: `grok-4.3` i
  `grok-4.20-*` mają 1M, modele `gemini-*` 1 048 576 (wcześniej wpadały w domyślne 256k).
- Modele wymagające osobnej zgody (`gpt-5.6-cyber`, `gpt-daybreak-*` z programu Daybreak)
  celowo nie trafiają do katalogu — dla zwykłego klucza byłyby pozycją zawsze kończącą
  się błędem.
- Panel Image trzyma ustawienia modelu w jednym rzędzie; „Reference library" i „From disk"
  przeniesiono na koniec listy kontrolek.

- Katalog modeli został zsynchronizowany z dokumentacją dostawców: Gemini 3.7 Flash
  jest domyślnym modelem Google, zachowano 3.6/3.5 i modele Lite; usunięto emulowany
  wpis `grok-3`, a możliwości reasoning i limity referencji xAI są opisane per model.
- Cennik obrazów Google używa stawek per model i rozdzielczość, a xAI uwzględnia
  jakość, rozdzielczość i koszt każdego obrazu referencyjnego.
- `caelo_settings.json` nie przechowuje już kluczy API, a `caelo_auth.json` jest po
  udanej migracji usuwany. Backend używa poświadczeń wyłącznie z pamięci procesu.
- Dokumentacja prywatności i ekran Settings wskazują jawnie, że dane trafiają bezpośrednio
  do wybranego dostawcy xAI albo Google; Caelo nie używa własnego proxy ani telemetrii.
- Paczka PyInstaller deklaruje moduły fazy 7 i pomija testy runtime; sidecar Windows
  zmniejszył się z 75,62 MiB do 70,85 MiB.
- Kontrolki właściwe tylko dla xAI, w szczególności wyszukiwanie w X, są ukrywane po
  wybraniu Google zamiast sugerować nieistniejącą zgodność funkcji.
- Cztery konfigurowalne filtry bezpieczeństwa Gemini są jawnie wysyłane jako `OFF`,
  zgodnie z ustawieniem przyjętym wcześniej dla generowania obrazów.
- xAI-owe narzędzie live `web_search` nie jest udostępniane agentowi Gemini; wspólne
  narzędzia plikowe, powłoka, MCP, plan i delegacja pozostają dostępne.

### Fixed
- Obrazy z modeli Google wychodziły zawsze w 1K niezależnie od wybranej rozdzielczości.
  Nano Banana z włączonym `thinkingConfig` zwraca w tej samej odpowiedzi robocze podglądy
  oznaczone `thought: true` — zawsze w 1K — a adapter brał pierwszy obraz. Części myślowe
  są teraz pomijane, a wynikiem jest ostatni render.
- Miniatury świeżo wygenerowanych obrazów i wideo pojawiały się dopiero po restarcie
  aplikacji. Wymuszone odświeżenie listy dołączało do żądania wysłanego przed końcem
  zadania i stemplowało starą listę jako świeżą, a kafelek ładował się leniwie i dla nowo
  dołożonej karty potrafił nie wystartować. Podgląd pobiera się teraz od razu i ponawia
  próbę po błędzie protokołu.
- Generowanie wideo Gemini Omni na Vertex AI kończyło się błędem 400 „Unsupported model
  interaction": ta powierzchnia wymaga id `gemini-omni-1.1-flash-preview`, podczas gdy
  AI Studio używa nazwy bez sufiksu. Mapowanie działa wyłącznie na drucie (jak przy Veo),
  więc katalog, cennik i artefakty zachowują jedno id.
- Do metadanych artefaktu obrazu trafia żądana rozdzielczość i proporcje, bez czego nie
  dało się sprawdzić po fakcie, czy dostawca uszanował ustawienie.

- Zwykły egzekutor kolejki otrzymuje zmaterializowane dane obrazów i wideo, podczas gdy
  SQLite oraz odpowiedzi REST nadal przechowują wyłącznie lekkie wskaźniki plikowe.
- Błąd synchronizacji odświeżonego tokenu OAuth nie jest już traktowany jako awaria
  zdrowego sidecara i nie może uruchomić pętli restartów procesu.
- Selektor dostawcy w nagłówku modułu Code nie zajmuje już całej dostępnej szerokości,
  dzięki czemu wybór modelu jest widoczny, a strzałki obu list nie nakładają się.
- Lista modeli agenta toleruje starszą pamięć podręczną katalogu modeli, w której modele
  Gemini nie miały jeszcze oznaczenia obsługi narzędzi.

## [2.0.7] — 2026-08-29

### Fixed
- Karty obrazów w Galerii i „Recent images” pobierają miniatury WEBP zamiast dekodować
  dziesiątki pełnowymiarowych PNG. Miniatury powstają na żądanie w wewnętrznym cache
  Caelo, więc folder wynikowy nadal zawiera wyłącznie właściwe obrazy i filmy.

## [2.0.6] — 2026-08-29

### Fixed
- Galeria, kolejka i polecenia generowania korzystają teraz ze stabilnego kanału procesu
  głównego aplikacji zamiast bezpośrednich połączeń HTTP z interfejsu Chromium.
- Techniczny monitor lokalnego Caelo Core korzysta z uwierzytelnionego testu procesu;
  nie zmienia znaczenia wskaźnika „Connected”, który nadal wynika z aktywnych
  poświadczeń xAI (OAuth, API key albo `.env`).
- Plik z natywnej biblioteki referencji nie jest już błędnie traktowany jak artefakt galerii,
  co usuwało nieprawidłowe powiązania i błąd podczas finalizacji wygenerowanego wyniku.
- Wysłanie płatnego zadania generowania nie jest automatycznie ponawiane po timeoutcie,
  dzięki czemu pojedyncze kliknięcie tworzy najwyżej jedno zadanie.

## [2.0.5] — 2026-08-29

### Fixed
- Import obrazów referencyjnych jest teraz natywną operacją plikową aplikacji desktopowej:
  wybrane obrazy są kopiowane bezpośrednio do folderu biblioteki, bez HTTP, kolejki i SQLite.
- Lista, miniatury, pełny podgląd i ponowne użycie referencji są odczytywane bezpośrednio
  z folderu biblioteki, więc nie zależą od szybkości ani stanu Caelo Core.
- Anulowanie systemowego okna wyboru natychmiast przywraca przyciski i nie pozostawia
  biblioteki w stanie „Working…”.

## [2.0.4] — 2026-08-29

### Fixed
- Import do biblioteki obrazów referencyjnych wysyła teraz surowe bajty obrazu zamiast
  rozbudowanego JSON/base64, dzięki czemu duże pliki nie kończą się timeoutem.
- Równoległe pierwsze wczytywanie biblioteki nie może już nadpisać właśnie zaimportowanego
  obrazu; każdy udany plik pojawia się od razu, także gdy kolejny import się nie powiedzie.
- Odczyt biblioteki ma osobny, dłuższy limit czasu oraz przycisk ponowienia po błędzie.

## [2.0.3] — 2026-08-29

### Added
- Trwała biblioteka obrazów referencyjnych wspólna dla formularzy Obraz i Wideo.
  Obrazy można zaimportować raz, zaznaczać wielokrotnie i dodawać zgodnie z limitem
  aktywnego modelu.
- Pełnoekranowy podgląd obrazów referencyjnych z przełączaniem między dopasowaniem
  do okna i rzeczywistym rozmiarem 1:1.

### Changed
- Gotowe obrazy i filmy są ponownie zapisywane bezpośrednio w wybranym folderze
  wynikowym, bez automatycznych podfolderów, plików JSON i osobnych miniaturek.
- Duże obrazy wejściowe kolejki są przechowywane jako zarządzane pliki danych aplikacji,
  poza bazą historii i poza folderem wynikowym. Worker odtwarza je dopiero na czas
  wywołania modelu, a ponawianie zadania nadal działa.

### Fixed
- Nowe zadania z obrazami referencyjnymi nie powiększają już bazy SQLite o zakodowane
  kopie plików, które wcześniej mogły blokować zapytania Galerii i kolejki.

## [2.0.2] — 2026-08-29

### Fixed
- Zakładki Obraz i Wideo po pierwszym otwarciu pozostają gotowe w pamięci interfejsu,
  dzięki czemu szybkie przełączanie nie tworzy ponownie całych widoków.
- Lista zadań, katalog modeli i ostatnie wyniki współdzielą krótkotrwałe migawki oraz
  jedno trwające zapytanie zamiast nakładać kolejne odczyty backendu.
- Formularze obrazu i wideo od razu korzystają z wbudowanego katalogu modeli, więc podczas
  odświeżania połączenia nie pokazują pustych pól dostawcy i modelu.

## [2.0.1] — 2026-08-29

### Fixed
- Usunięto blokowanie interfejsu przez listę zadań, która wczytywała i kopiowała do pamięci
  wielomegabajtowe dane obrazów referencyjnych przy każdym odświeżeniu kolejki.
- Historia zachowuje pełne wejścia potrzebne do audytu i Retry, ale odpowiedzi listy kolejki
  zawierają tylko lekki prompt, model oraz metadane.
- Migracja starszej kolejki przetwarza rekordy pojedynczo i nie tworzy drugiej kopii dużych
  danych wejściowych dla zakończonych zadań.

## [2.0.0] — 2026-08-29

### Added
- Zintegrowane generowanie obrazów i wideo przez Google Gemini / Vertex AI z logowaniem
  Google Cloud ADC, obok istniejącej obsługi xAI.
- Wspólna kolejka generowania, galeria, projekty i historia pochodzenia materiałów dla obu
  dostawców.
- Adaptacyjne formularze obrazu i wideo, które pokazują wyłącznie możliwości aktywnego modelu
  i zapamiętują ostatnie ustawienia użytkownika.

### Changed
- Nazwa produktu, aplikacji Windows, skrótu i deinstalatora została ujednolicona jako
  **Caelo 2.0**.
- Ustawienia dostawców uporządkowano w osobnych sekcjach xAI i Google, zachowując wspólne
  ustawienia aplikacji.
- Obsługa referencji obrazu korzysta z ról wspieranych przez wybrany model Google lub xAI.

## [0.1.5] — 2026-08-12

Picks up xAI's August model wave — **Grok 4.6**, **reference-to-video**, and
**Grok Imagine Image 2.0** — and adds a third way to connect an MCP server:
a **local HTTP** one, with DAZ Studio 6 (SceneAgent MCP) in the catalogue.

### Added
- **Grok 4.6** (`grok-4.6`) is in the chat model list and is the new default. 500k context,
  vision, function calling, live web/X search, and a new **`xHigh`** reasoning level on top of
  low / medium / high. The context meter estimates 500k for it.
- **xHigh reasoning effort.** The effort selector offers it **only on models that document it**
  (today: `grok-4.6`) — picking a level a model doesn't know would silently fall back to its
  default, so the menu hides it instead, and warns if a previously chosen xHigh no longer applies
  after a model switch.
- **Reference images for video** (reference-to-video, `grok-imagine-video-1.5`). Attach up to
  **3** images in the Video panel to carry a character, outfit, or object into the clip and refer
  to them in the prompt as `<IMAGE_1>`…`<IMAGE_3>`. Unlike a first frame, they do **not** fix the
  opening shot — both can be used together. The tray only appears on models that accept them,
  and the references survive a tab switch like the other staged media.
- **Grok Imagine Image 2.0** (`grok-imagine-image-2.0`) in the image model list, with its
  **Quality** control (low / medium, xAI's default is medium). The control is shown only for 2.0 —
  it is the only model that accepts the parameter, and other models reject the whole request.
- **Local HTTP MCP servers** (`transport: "http"`). Beside stdio (a local process) and remote
  (executed on xAI's side), Caelo can now call a Streamable-HTTP MCP server **running on this
  machine**, with its tools going through the same permission gate as a local process. Server
  tokens are stored like other MCP secrets — the renderer only ever sees whether one is set, never
  its value — and a token is refused over plain `http://` to a non-loopback host.
- **DAZ Studio 6 in the MCP catalogue**, as two entries because the two editions differ in
  transport: **SceneAgent MCP (Pro)** over stdio — its bridge path is read from the installer's
  registry key and verified on disk, so the entry stays one-click — and **SceneAgent MCP
  (Plugin Edition)** over loopback HTTP, which takes the access token from the plugin's pane.

### Changed
- **Default chat model is now `grok-4.6`** (was `grok-4.5`). Saved per-session and per-setting
  choices are untouched, and the live model list from the API still wins over the built-in fallback.
- **Image cost estimates know 2.0** ($0.04 per image — twice the standard model, half of quality).
  The **default image model stays `grok-imagine-image`**: 2.0 is a deliberate choice, not a silent
  price increase.
- Servers imported from `~/.claude.json` with a **loopback** URL now arrive as local `http`
  servers instead of remote ones — xAI's cloud cannot reach this machine, so the old mapping
  produced a server that looked configured but could never run.

## [0.1.4] — 2026-07-13

Adds xAI's new flagship model, **Grok 4.5**.

### Added
- **Grok 4.5** (`grok-4.5`) is now in the chat model list and is the new default. Per xAI it is
  the most intelligent and fastest model, trained for coding, agentic tasks, and knowledge work
  (knowledge cutoff February 1, 2026). It supports adjustable `reasoning_effort` (low / medium /
  high, default high) — the effort selector works with it out of the box.

### Changed
- **Default chat model is now `grok-4.5`** (was `grok-4.3`). Existing per-session and saved model
  choices are unaffected; the live model list from the API still takes precedence over this
  built-in fallback list.
- The context-window meter now estimates **500k tokens** for `grok-4.5`.

## [0.1.3] — 2026-07-08

A creative-mode pricing/quality update, plus sturdier image inputs — and the first
macOS build produced and signed on Apple Silicon.

### Added
- **1080p video** on **`grok-imagine-video-1.5`**. The Video mode now offers 480p / 720p /
  1080p when the 1.5 model is selected (the base `grok-imagine-video` still tops out at 720p).

### Changed
- **Accurate video cost estimates.** Video is now priced **per resolution** to match xAI's
  tariff — 1.5: $0.08 / $0.14 / $0.25 per second at 480p / 720p / 1080p; base: $0.05 / $0.07 —
  instead of a single flat per-model rate.

### Fixed
- **Oversized image inputs no longer fail.** Reference images (Image mode) and the video first
  frame are now automatically compressed to WebP at the highest quality that still fits the API
  limit, instead of being rejected.
- **Readable errors.** Validation errors from the backend are shown as plain text instead of
  the unhelpful "[object Object]".

## [0.1.2] — 2026-07-03

A small usability update for the creative modes: reuse the prompt behind any
generated image or video without retyping it.

### Added
- **Reuse a saved prompt.** Every generated image and video already stores the prompt
  that made it; each artifact card (Gallery, and the "Recent" strips in the Image/Video
  modes) now surfaces it with a **Reuse prompt** button — one click drops the prompt
  into the matching mode (Image → Image, Video → Video) and takes you there — plus a
  **Copy** button. Long prompts are shown truncated with a **Show more** toggle to
  expand the full text.

### Fixed
- **Copy prompt** now works reliably in the packaged app: it falls back to a manual copy
  when the browser Clipboard API is unavailable or blocked.

## [0.1.1] — 2026-06-23

First update after the initial release — a stabilization pass driven by live
verification against the real xAI API, plus two model/cost improvements.

### Added
- **Real per-request cost.** Chat (Responses API) and batch speech-to-text now show
  the **actual** cost reported by xAI (`usage.cost_in_usd_ticks`) instead of a local
  estimate, when the API provides it. Estimates remain as a fallback. Image/video and
  text-to-speech still use estimates.

### Changed
- **Video model:** switched the default to the stable **`grok-imagine-video-1.5`**
  (xAI dropped the `-preview` suffix). Edit/extend still routes to the base
  `grok-imagine-video`, which supports those operations.
- **Voice — Talk mode** now drives its transcription via batch speech-to-text with a
  local voice-activity detector (auto-stop on silence). This is reliable today; live
  partial transcripts are deferred until the streaming-STT rewrite lands.

### Fixed
- **Voice:** the audio worklet (mic capture for Talk/Live/STT) failed to load under the
  Content-Security-Policy — `script-src` now allows `blob:`, so voice capture works.
- **Settings:** save confirmations now appear as a toast instead of a banner off-screen.
- **MCP:** enabled servers auto-start and warm-start with the sidecar; the agent keeps
  its MCP tools after a workspace rebuild; stdio servers start in the workspace root so
  relative paths resolve.
- **Coding agent:** a session now survives switching tabs (auto-resume); a loop guard
  ends a turn cleanly when the model repeats an identical failing edit; LSP diagnostics
  now match on Windows (canonical-path keying) so squiggles show up.
- **Subagents / Team:** the merge-review diff opens in a modal (buttons always reachable)
  and the Team panel scrolls instead of compressing its cards.

## [0.1.0] — 2026-06-17

Initial public release.

- **Five modes under one hub:** Chat (Responses API with live web/X search, vision,
  document Q&A, citations), Image & Video generation/editing (unified job queue + gallery),
  Voice (TTS / STT / realtime "Live" / "Talk" pipeline), an agentic **Code** module
  (sandboxed file tools, diff approval, 4 trust modes, checkpoints/undo, `CAELO.md` rules,
  subagents/teams), and History/Gallery.
- **Bring-your-own-key**, loopback-only backend, no telemetry. OAuth (xAI account) or API key.
- **Extensibility:** MCP client (stdio + native remote), slash commands, hooks, skills,
  a community package marketplace, headless CLI, ACP and LSP integration.
- Electron (frontend) + Python FastAPI sidecar (backend); Windows installer, signed.

[2.0.4]: https://github.com/AuraVixStudio/caelo/compare/v2.0.3...v2.0.4
[2.0.3]: https://github.com/AuraVixStudio/caelo/compare/v2.0.2...v2.0.3
[2.0.2]: https://github.com/AuraVixStudio/caelo/compare/v2.0.1...v2.0.2
[2.0.1]: https://github.com/AuraVixStudio/caelo/compare/v2.0.0...v2.0.1
[2.0.0]: https://github.com/AuraVixStudio/caelo/releases/tag/v2.0.0
[0.1.5]: https://github.com/AuraVixStudio/caelo/compare/v0.1.4...v0.1.5
[0.1.4]: https://github.com/AuraVixStudio/caelo/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/AuraVixStudio/caelo/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/AuraVixStudio/caelo/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/AuraVixStudio/caelo/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/AuraVixStudio/caelo/releases/tag/v0.1.0
