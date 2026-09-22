# Caelo 2.0 — plan integracji

**Źródła:** `G:\Projekty_oprogramowanie\grok_desktop_app` (Caelo 0.1.5) × `G:\Projekty_oprogramowanie\gemini-desktop-studio` (0.1.0)
**Cel:** `G:\Projekty_oprogramowanie\Caelo_2.0`
**Data:** 2026-08-22 · **Aktualizacja:** 2026-08-31 · **Status:** Fazy 0–7 integracji xAI/Google zaimplementowane. OpenAI Chat + Code/Agent ma zakończone fazy 0–4 bez sieci; test live i wydanie pozostają w [osobnym planie](PLAN_INTEGRACJI_OPENAI.md).

**Decyzje wejściowe (potwierdzone):**

1. Logika Gemini **portowana do sidecara Python** (`caelo_core`), nie utrzymywana jako drugi silnik TS.
2. **Pełna fuzja modułów** — provider (xAI / Google) jest wymiarem, nie osobną zakładką.
3. Zakres Gemini: **obraz+wideo · czat tekstowy · silnik agenta · infrastruktura (kolejka, registry, pliki)** — czyli pełny.
4. Start: **kopia Caelo jako fundament**, Gemini wciągany jako nowa warstwa.
5. Google: **GCP/Vertex AI przez ADC jest wymaganym trybem**; klucz AI Studio zostaje
   alternatywą. Projekt i region są ustawieniami aplikacji, nie sekretami.
6. Caelo 2.0 pozostaje **publicznym projektem Apache-2.0**; wewnętrzna specyfikacja dawcy
   nie wchodzi do publicznego zakresu wydania.
7. Akceptujemy zmianę deklaracji prywatności: aplikacja komunikuje się z wybranym przez
   użytkownika providerem xAI lub Google, przy zachowaniu local-first, BYO credentials i zerowej telemetrii.
8. Wydanie etapowe: **Caelo 2.0 = studio mediów xAI + Google**; czat i agent Google
   wchodzą później jako **Caelo 2.1**.
9. `grok_desktop_app` i `gemini-desktop-studio` pozostają **osobnymi, niezależnymi projektami**.
   Integracja nie może ich archiwizować, usuwać ani modyfikować.

---

## 0. Streszczenie

Najważniejsza rzecz do zrozumienia przed czytaniem reszty:

> **To nie jest scalenie dwóch kodów. To ponowna implementacja architektury `gemini-desktop-studio` wewnątrz Caelo, w Pythonie.**

Przy przyjętych decyzjach z `gemini-desktop-studio` **nie przetrwa praktycznie żaden plik**. Cały jego runtime (`@google/genai`, `better-sqlite3`, `sharp`, `zod`, `pino`, warstwa IPC, repozytoria, komponenty React) albo trafia na drugą stronę granicy procesu (do Pythona), albo jest już pokryty przez odpowiednik w Caelo (pydantic zamiast zod, `logging` zamiast pino, REST/WS zamiast IPC, Tailwind UI kit Caelo zamiast stron Gemini).

Co przetrwa i jest **jedyną prawdziwą wartością** tego projektu: **projekt architektoniczny**. Kontrakty providerów, maszyna stanów kolejki, model zdolności (capabilities), znormalizowany schemat mediów, dyscyplina „nigdy nie wyślij ponownie płatnego żądania". To jest to, czego Caelo nie ma, i to jest to, co przenosimy — jako decyzje, nie jako pliki.

Konsekwencja dla harmonogramu: nie licz, że „kod już działa, tylko go przekleimy". Licz jak przy pisaniu od nowa, z gotową i sprawdzoną specyfikacją w ręku. To nadal jest ogromna oszczędność — ale oszczędność projektowa, nie wykonawcza.

---

## 1. Inwentaryzacja — co faktycznie mamy

### 1.1. Caelo (`grok_desktop_app`) — dojrzała aplikacja

| Element | Stan |
|---|---|
| Stack | Electron 42 + React 19 + TS 6 + Tailwind 4 · sidecar Python (FastAPI/uvicorn) |
| Skala | ~96 route'ów REST + 6 WS, 61 plików renderera, 30 modułów `caelo_core`, 30 route'ów |
| Chat | Responses API, live search (web/X) z cytowaniami, wizja, Q&A nad dokumentami, TTS/STT |
| Code | Mini-IDE (CodeMirror, xterm), agent z sandboxem, approval gate, checkpointy/undo, `CAELO.md`, subagenty + worktree merge |
| Media | Obraz (generate/edit/variations), wideo (t2v/i2v/edit/extend) — cienka warstwa nad `api_manager.py` |
| Historia | SQLite + **FTS5** + embeddingi zdarzeń (`event_embeddings`), projekty, galeria |
| Ekosystem | MCP (local+remote), skills, hooks, slash commands, marketplace pakietów, LSP, ACP, headless CLI |
| Auth | **OAuth PKCE** do `auth.x.ai` + klucz API + `.env`, twarda precedencja z jawnym przełącznikiem |
| Bezpieczeństwo | bind 127.0.0.1, token sesji na REST+WS (fail-closed), CORS zawężony, klucz nigdy nie dociera do renderera, scrubbed env dla `run_command`, blokada metaznaków powłoki |
| Dojrzałość wydawnicza | Apache-2.0, podpisany NSIS (Authenticode), notaryzowany dmg, AppImage/deb w CI, CHANGELOG, CLA, SECURITY.md, ~10 dokumentów |

**Twarde ograniczenie z `CLAUDE.md`:** rdzeń xAI (`config.py`, `api_manager.py`, `oauth_manager.py`, `chats_manager.py`, `history_manager.py`) leży w **korzeniu repo**, nie w `caelo_core/`. Sidecar importuje je jako moduły top-level przez `sys.path` shim, a `caelo_core.spec` deklaruje je jako `hiddenimports` z `pathex='.'`. **Nie wolno ich przenosić ani restrukturyzować** — psuje to importy sidecara, build PyInstallera i (przez `config.py`) każdą ścieżkę do danych.

### 1.2. Gemini Desktop Studio — lepsza architektura mediów

| Element | Stan |
|---|---|
| Stack | Electron 38 + React 19 + TS 5.9, **wszystko w main process**, zero Pythona |
| Skala | 78 plików TS/TSX, ~330 KB kodu |
| Providerzy | Nano Banana (3.1 Flash / Pro / Lite / 2.5 legacy), Gemini Omni Flash, Veo 3.1 (+Fast/Lite), MockProvider |
| Kolejka | **Trwała, z odzyskiwaniem po restarcie** — 13 stanów, retry z jitterem, limity per typ kolejki, `UNKNOWN_REMOTE_STATE` |
| Modele | **ModelRegistry + CapabilityGuard** — deklaratywne zdolności sterujące całym UI i twardą walidacją przed wydaniem pieniędzy |
| Schemat | Znormalizowany: `generations` / `generation_inputs` / `generation_outputs` / `jobs` / `asset_references` / `presets` / `usage_records` / `remote_file_cache` / `tags` — z kolumną `provider` **już obecną** |
| Pliki | FileManager (drzewo workspace), sidecary metadanych JSON, miniatury, kosz z datowaniem, streaming do `.part` |
| Media w UI | Prywatny schemat `protocol.handle` — streaming z dysku, range requests, bez limitu rozmiaru |
| Sekrety | `safeStorage` (szyfrowanie systemowe), klucz wyłącznie w main process |
| Walidacja | Zod na **każdym** payloadzie IPC |
| Testy | 5 plików Vitest (capability guard, pipeline obrazu, recovery kolejki, request builder, utils) |

**Kluczowy cytat z `src/main/api/providers.ts`:** *„Workers only ever talk to these interfaces, so a second provider (Vertex, OpenAI, local ComfyUI) can be added without touching the queue."* — abstrakcja providerów **już tam jest** i była projektowana pod dokładnie ten scenariusz. Tylko po niewłaściwej stronie granicy procesu.

### 1.3. Cztery konkretne przewagi Gemini, których Caelo nie ma

Nie są to preferencje estetyczne — to zidentyfikowane braki w kodzie Caelo:

**A. Kolejka Caelo gubi płatną pracę przy restarcie.**
`caelo_core/genjobs.py` → `GenJobManager._reap_stale()` oznacza zadania zawieszone przy poprzednim uruchomieniu jako `failed("interrupted")`. Nie ma trwałego uchwytu zdalnego (`operation_name` / `interaction_id`), więc po restarcie zadanie Veo, za które użytkownik **już zapłacił**, jest po prostu porzucone. Nie ma też fazy pollingu, retry z backoffem ani limitów per typ zadania — jest jedna pula wątków i jeden `queue.Queue`.
Gemini rozwiązuje to wprost i celowo: uchwyt zdalny jest utrwalany **zanim** funkcja submitu wróci, `JobRecovery` po restarcie wznawia polling, a stan niejednoznaczny (`SUBMITTING` bez uchwytu) ląduje w `UNKNOWN_REMOTE_STATE` i **czeka na świadomą decyzję użytkownika** zamiast automatycznie płacić drugi raz.

**B. Caelo nie ma modelu zdolności.**
Zdolności modeli xAI siedzą w rozproszonych `if`-ach (`api_manager._apply_quality`, walidatory w `routes/media.py`, listy modeli w rendererze). Nie da się z tego wygenerować UI ani zwalidować żądania przed wysłaniem. Gemini ma `capabilityGuard.ts` używany przez **oba** kierunki: formularz ukrywa nieobsługiwane opcje, main process twardo odrzuca żądanie zanim ruszy w świat.

**C. Renderer Caelo buforuje całe media w pamięci.**
`ArtifactMedia.tsx` pobiera bajty artefaktu przez fetch z nagłówkiem Bearer i tworzy blob object URL. Dla obrazka to bez znaczenia. Dla klipu Veo 4K to jest kilkaset MB w pamięci renderera, bez przewijania i bez range requests. Gemini serwuje media przez prywatny schemat protokołu ze strumieniowaniem z dysku.

**D. Schemat mediów Caelo jest płaski.**
Tabela `artifacts` (jeden wiersz = jeden plik, `meta` jako JSON blob) plus `gen_jobs` (`params` jako JSON blob). Nie ma pojęcia wejść generacji, rodzeństwa w batchu, rodzica (lineage edycji konwersacyjnej) ani osobnego wiersza usage. Gemini ma to znormalizowane i zaindeksowane.

### 1.4. Co Caelo ma, a Gemini nie ma w ogóle

Czat, agent kodujący, MCP/skills/hooks/commands/marketplace, LSP, ACP, OAuth, voice, terminal, git, FTS5 + embeddingi, headless CLI, podpisane instalatory na 3 platformy, CI, licencja, dokumentacja. **To jest powód, dla którego Caelo jest gospodarzem, a nie odwrotnie.**

---

## 2. Teza architektoniczna

**Caelo jest gospodarzem. Gemini Desktop Studio jest dawcą architektury mediów. xAI traci uprzywilejowaną ścieżkę.**

Ostatnia część jest najważniejsza i najłatwiejsza do przeoczenia. Dziś w Caelo `api_manager.APIManager` jest wołany bezpośrednio z `backend_media.py`, a `responses_client.py` ma w docstringu napisane wprost: *„To jedyna cienka warstwa endpoint/auth — hedge na zmiany xAI, **nie multi-provider**"*. Jeśli dołożymy Google obok, powstanie drugi zestaw ścieżek i wrócimy do problemu, którego chcieliśmy uniknąć — tylko wewnątrz jednego procesu.

Dlatego xAI **też** przechodzi za nową abstrakcję. Refaktor xAI-a jest częścią pracy, nie efektem ubocznym.

### Architektura docelowa

```
┌─────────────────── Electron main (desktop/src/main) ────────────────────┐
│ okno · menu · IPC · cykl życia sidecara · handshake (port+token)          │
│ NOWE: sejf sekretów (safeStorage) · prywatny schemat caelo-media://       │
└──────────────────────────────────────────────────────────────────────────┘
        │  preload → window.caelo
        ▼
┌─────────────────── Renderer (React 19 + Tailwind 4) ─────────────────────┐
│ Chat · Code · Image · Video · Voice · Queue · Gallery · Extensions        │
│ Każdy moduł mediów: [Provider ▾][Model ▾] → formularz z /capabilities     │
└──────────────────────────────────────────────────────────────────────────┘
        │  REST + WS — 127.0.0.1, bearer token
        ▼
┌────────────── Sidecar Python „caelo-core" (FastAPI) ─────────────────────┐
│                                                                          │
│  ROUTES  /providers /models /capabilities /generations /jobs /chat …      │
│     │                                                                    │
│  ┌──▼─────────────────────────────────────────────────────────────────┐  │
│  │ GenerationService — jedyne wejście do generacji                    │  │
│  │   walidacja capabilities → cost guard → utrwal → zakolejkuj        │  │
│  └──┬─────────────────────────────────────────────────────────────────┘  │
│     │                                                                    │
│  ┌──▼──────────────┐   ┌──────────────────┐   ┌────────────────────────┐ │
│  │ JobQueue        │   │ ModelRegistry    │   │ FileManager            │ │
│  │ 13 stanów       │   │ + CapabilityGuard│   │ sidecary meta          │ │
│  │ recovery/retry  │   │ + cennik         │   │ miniatury · .part      │ │
│  └──┬──────────────┘   └──────────────────┘   └────────────────────────┘ │
│     │                                                                    │
│  ┌──▼───────────────────── providers/ ───────────────────────────────┐   │
│  │  base.py — ImageProvider · VideoProvider · ChatProvider · Tools   │   │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐                  │   │
│  │  │ xai/       │  │ google/    │  │ mock/      │                  │   │
│  │  │ owija      │  │ nowy klient│  │ dev bez    │                  │   │
│  │  │ api_manager│  │ REST       │  │ kosztów    │                  │   │
│  │  └────────────┘  └────────────┘  └────────────┘                  │   │
│  └───────────────────────────────────────────────────────────────────┘   │
│                                                                          │
│  BEZ ZMIAN: agent/ · mcp/ · skills/ · commands/ · hooks/ · lsp/ · acp/    │
│  KORZEŃ REPO (nietykalny): config.py · api_manager.py · oauth_manager.py  │
└──────────────────────────────────────────────────────────────────────────┘
        │                                    │
        ▼ api.x.ai + auth.x.ai               ▼ generativelanguage.googleapis.com
                                               (+ opcjonalnie *.googleapis.com dla Vertex)
```

---

## 3. Decyzje architektoniczne

### ADR-1 — Google przez surowy REST, nie przez SDK

**Kontekst.** Port do Pythona sugeruje sięgnięcie po `google-genai` (SDK Pythonowe). Ale kod TS opiera się na **Interactions API** (`@google/genai` v2.17+), a parytet tego interfejsu w SDK Pythonowym jest niepotwierdzony. Jednocześnie **cały istniejący kod xAI w Caelo to ręcznie pisane `requests` po REST** — `api_manager.py`, `responses_client.py`, `agent/llm.py`, wszystko. Nie ma tam ani jednego SDK.

**Decyzja.** Klient Google piszemy ręcznie na `requests`, w stylu `responses_client.py`. SDK traktujemy wyłącznie jako **dokumentację kształtu drutu**. Dla trybu GCP dopuszczamy lekkie `google-auth` wyłącznie do pozyskiwania i odświeżania tokenu ADC; żądania Vertex AI nadal idą przez `requests`.

**Konsekwencje.**
- Zero ryzyka parytetu SDK i zero nowego, ciężkiego drzewa zależności w PyInstallerze (`google-genai` ciągnie `google-auth`, `pydantic`, `httpx`, protobuf — to realny wzrost rozmiaru instalatora i nowe `hiddenimports` w `caelo_core.spec`).
- Spójność stylu: jeden wzorzec HTTP w całym backendzie.
- Koszt: sami obsługujemy LRO (long-running operations) Veo, upload plików i wygasanie URI. To jest do zrobienia — Caelo już robi polling wideo xAI w `backend_media._run_video_job`.
- **Rozstrzygnięty wyjątek:** tryb GCP/Vertex jest wymagany (O-3), więc `google-auth` służy wyłącznie do ADC. Nie wciągamy `google-genai`, `httpx` ani jego warstwy modeli.

### ADR-2 — Model kolejki z Gemini wygrywa i obejmuje oba providery

**Decyzja.** `GenJobManager` z `caelo_core/genjobs.py` zostaje **zastąpiony**, nie rozszerzony. Nowa kolejka to port maszyny stanów z `JobQueue.ts` + `JobRecovery.ts` + `RetryPolicy.ts`. xAI wjeżdża pod nią jako handler, dokładnie tak jak Google.

**Nienaruszalne reguły przeniesione ze specyfikacji Gemini:**
- Zadanie jest utrwalone w bazie **zanim** żądanie ruszy w sieć.
- Uchwyt zdalny jest utrwalony w tej samej chwili, w której przychodzi.
- Restart **nigdy** nie wysyła ponownie żądania, którego stan zdalny jest nieznany → `UNKNOWN_REMOTE_STATE` + świadome ponowienie przez użytkownika.
- `retry` z istniejącym uchwytem **wznawia polling**, nie płaci drugi raz.
- Anulowanie zatrzymuje polling lokalny, ale nie udaje, że zdalna generacja się nie odbyła (może być naliczona).
- Wiersz zablokowany (`locked_at`) przy starcie = proces, który padł → `RECOVERY_PENDING`.

**Konsekwencje.** To jest zmiana zachowania widoczna dla obecnych użytkowników Caelo (na plus). Wymaga migracji tabeli `gen_jobs` — patrz §6.

### ADR-3 — Schemat mediów z Gemini wygrywa; historia, FTS5 i embeddingi Caelo zostają

**Decyzja.** Dokładamy do `caelo_history.db` znormalizowane tabele mediów z `migrations.ts` (`generations`, `generation_inputs`, `generation_outputs`, `jobs`, `asset_references`, `presets`, `usage_records`, `remote_file_cache`, `tags`, `generation_tags`). Zostawiamy nietknięte `history_events`, `history_fts`, `event_embeddings`, `collection_files`, `projects`.

Tabela `artifacts` **zostaje jako indeks galerii** — dostaje kolumnę `generation_output_id` (nullable). Legacy artefakty mają tam NULL i nadal działają. Nowe generacje zapisują oba wiersze.

**Uzasadnienie.** `generations` w Gemini **ma już kolumnę `provider TEXT NOT NULL DEFAULT 'google'`** — schemat był projektowany pod multi-provider. Zmieniamy tylko default. Jednocześnie Gemini nie ma nic w miejscu FTS5 + embeddingów Caelo, więc tamta warstwa nie ma z czym konkurować.

**Konsekwencje.** Jedna baza, jeden plik, jeden backup. Migracje w Caelo są dziś ad-hoc (`ALTER TABLE` w `_init_schema`) — dokładamy **wersjonowaną, append-only tablicę migracji** wzorowaną na `migrations.ts`, bo dalej bez tego nie da się rozsądnie żyć.

### ADR-4 — Rejestr modeli i CapabilityGuard: jedno źródło prawdy, generowane do frontendu

**Kontekst.** W Gemini registry i guard leżą w `src/shared/` — współdzielone między main a rendererem przez import TS. Po przeniesieniu do Pythona granica procesu tę współdzielność zrywa. Duplikacja definicji w Pythonie i w TS to gwarantowany rozjazd.

**Decyzja.** Definicje modeli i zdolności żyją **w Pythonie** (`caelo_core/models/registry.py`) jako jedyne źródło prawdy. Backend wystawia je przez `GET /providers` i `GET /models?provider=…` razem z pełnym obiektem `capabilities`. Renderer **konsumuje je w runtime** i buduje formularz dynamicznie — nie ma własnych list modeli.

Typy TS dla kształtu odpowiedzi generujemy skryptem z definicji Pythonowych do `desktop/src/renderer/src/lib/generated/models.ts` (krok w `npm run typecheck`, plik commitowany, rozjazd wykrywany w CI).

**Konsekwencje.** Dodanie modelu = jeden wpis w Pythonie, zero zmian w rendererze. Walidacja zdolności działa po obu stronach z tej samej definicji: miękko w formularzu, twardo w `GenerationService` przed wydaniem pieniędzy.

### ADR-5 — Sekrety: `safeStorage` w Electronie jako sejf, sidecar dostaje je w pamięci

**Kontekst.** To jest realny konflikt, nie kosmetyka. Caelo trzyma dziś klucz API w `caelo_settings.json` i tokeny OAuth w `caelo_auth.json` — **czystym tekstem na dysku**. Gemini szyfruje sekrety przez `safeStorage` (DPAPI na Windows, Keychain na macOS). Sidecar Python **nie ma dostępu do `safeStorage`** — to API Electrona.

**Decyzja.** Electron main staje się sejfem. Sekrety (klucz xAI, tokeny OAuth, klucz Google) są szyfrowane przez `safeStorage` i zapisywane do `secrets.dat`. Przy starcie sidecara Electron odszyfrowuje je i przekazuje **w pamięci** — kanałem uwierzytelnionym tokenem sesji (rozszerzenie istniejącego handshake'u; **nie** przez zmienne środowiskowe, które wyciekają do listy procesów). Zmiana sekretu w Settings → push do sidecara przez REST, bez restartu.

**Konsekwencje.**
- Znika plaintext klucza z dysku — realne wzmocnienie także dla dzisiejszego Caelo.
- Precedencja auth (`auto` → OAuth → klucz → `.env`) i `active_auth_source()` zostają **bez zmian koncepcyjnie** — zmienia się tylko źródło odczytu.
- Migracja: przy pierwszym starcie 2.0 istniejące `caelo_settings.json`/`caelo_auth.json` są wciągane do sejfu, a plaintextowe pola **kasowane** (plik zostaje, bo trzyma też niesekretne ustawienia).
- `.env` / `XAI_API_KEY` zostaje jako ścieżka deweloperska.
- **Nowe:** analogiczna precedencja dla Google — `GEMINI_API_KEY` / `GOOGLE_API_KEY` z `.env`, klucz z sejfu, brak OAuth (Google nie ma odpowiednika PKCE flow z x.ai).

### ADR-6 — Komponenty React z Gemini nie są przenoszone; przenoszona jest logika

**Decyzja.** `ImageGeneratorPage.tsx`, `VideoGeneratorPage.tsx`, `GalleryPage.tsx`, `QueuePage.tsx`, `SettingsPage.tsx` z Gemini **nie trafiają do Caelo**. Portowana jest wyłącznie ich **logika sterowana zdolnościami** do istniejących `Image.tsx`, `Video.tsx`, `Gallery.tsx`, `GenQueue.tsx`, `Settings.tsx`.

**Uzasadnienie.** Caelo ma dojrzały system designu (Tailwind 4, 17 komponentów `ui/`, theme, toasty, popovery, command palette). Gemini ma styl inline/utility bez wspólnego kitu. Wciągnięcie jego stron dałoby dwa niespójne wizualnie światy w jednym oknie — dokładnie to, czego decyzja o „pełnej fuzji" miała uniknąć.

**Wyjątki — dwa ekrany wchodzą jako nowe, bo Caelo nie ma odpowiednika:**
- **Asset Inspector** — panel szczegółów artefaktu (pełne parametry, lineage edycji, ścieżka pliku, koszt).
- **Diagnostics** — test połączenia per provider, wersja bazy, wolne miejsce, integralność, raport recovery.

Zostają zaimplementowane od zera w kicie UI Caelo.

**Zarządzanie stanem:** zostaje wzorzec Caelo (`lib/hub.tsx`). Zustand i TanStack Query z Gemini **nie** wchodzą — dokładanie dwóch bibliotek stanu do działającej aplikacji to koszt bez zysku.

### ADR-7 — Kod Google nie dotyka modułów w korzeniu repo

**Decyzja.** Nic związanego z Google nie trafia do `config.py`, `api_manager.py`, `oauth_manager.py`, `chats_manager.py`, `history_manager.py`. Provider Google żyje wyłącznie w `caelo_core/providers/google/`.

**Uzasadnienie.** Wprost zakazane przez `CLAUDE.md` — te moduły są związane z `sys.path` shimem w `caelo_core/__init__.py`, `hiddenimports` w `caelo_core.spec` i (przez `config.py`) każdą ścieżką do danych. `responses_client.py` już ustanowił precedens: „klient ŻYJE TU, NIE w root `api_manager.py`".

**Konsekwencja dla xAI:** provider xAI (`providers/xai/`) jest **adapterem owijającym** `api_manager.APIManager`, a nie jego przepisaniem. Korzeń zostaje nietknięty; jeśli adapter ujawni brakującą funkcję, dokładamy ją w adapterze, nie w korzeniu.

### ADR-8 — Adapter tool-callingu na granicy agenta

**Kontekst.** To najtrudniejszy technicznie element całego planu. xAI używa kontraktu w stylu OpenAI: `tools[].function`, `tool_calls[]` z `id`, wiadomości roli `tool`. Google używa `functionDeclarations` oraz części `functionCall` / `functionResponse` w `contents[].parts[]`. **SPIKE-2 skorygował pierwotne założenie:** aktualny `gemini-3.5-flash` również zwraca `id` i wymaga jego ścisłego powtórzenia w `functionResponse`; starsze modele mogą go nie mieć. Do tego `agent/session.py` ma logikę specyficzną dla kontraktu xAI — m.in. wstawianie **syntetycznych wyników `tool`** dla przerwanych `tool_calls`, żeby historia pozostała zbalansowana.

**Decyzja.** Wprowadzamy neutralny format wewnętrzny (`ToolCall`, `ToolResult`, `AssistantTurn`) na granicy `agent/llm.py`. `session.py` widzi **tylko** format neutralny. Każdy provider dostarcza dwukierunkowy adapter.

**Konsekwencje.**
- Adapter Google **zachowuje natywne `functionCall.id`**, jeśli model je zwraca, i kopiuje je do odpowiadającego `functionResponse.id`. Syntetyczny identyfikator jest wyłącznie fallbackiem dla starszych odpowiedzi bez `id`.
- Pełna część modelu z `thoughtSignature` wraca bez zmian w następnej turze. Przy wywołaniach równoległych najpierw wysyłamy wszystkie `functionCall`, następnie odpowiadające im `functionResponse`, z identyczną liczbą, kolejnością, nazwami i identyfikatorami.
- Streaming Gemini 3.x może zwracać `partialArgs[]` z `jsonPath` i `willContinue`; adapter składa je do argumentów narzędzia, zachowując `id`, nazwę i podpis z pierwszego fragmentu.
- Loop guard, checkpointy, permission gate, hooki, telemetria tur — działają bez zmian, bo operują na formacie neutralnym.
- **Wymagany zestaw testów równoważności**: ta sama sesja agenta, oba providery, identyczna sekwencja narzędzi. Bez tego nie ma pewności, że agent na Google jest bezpieczny — a agent ma dostęp do plików i powłoki.

---

## 4. Struktura docelowa

```
Caelo_2.0/
├── config.py, api_manager.py, oauth_manager.py …   # KORZEŃ — nietykalny (ADR-7)
├── caelo_core/
│   ├── providers/                        # NOWE — serce integracji
│   │   ├── base.py                       # kontrakty (port providers.ts)
│   │   ├── errors.py                     # taksonomia błędów (port errors.ts)
│   │   ├── xai/  {image,video,chat,tools}.py     # adapter nad api_manager
│   │   ├── google/ {client,image,video,chat,tools,files}.py
│   │   └── mock/                         # dev bez kosztów (port MockProvider)
│   ├── models/
│   │   ├── registry.py                   # ModelRegistry (ADR-4)
│   │   ├── capabilities.py               # CapabilityGuard
│   │   ├── xai_models.py / google_models.py
│   │   └── pricing.py                    # jeden cennik obu providerów
│   ├── jobs/                             # zastępuje genjobs.py (ADR-2)
│   │   ├── queue.py, recovery.py, retry.py
│   │   ├── image_handler.py, video_handler.py, download_handler.py
│   │   └── finalizer.py
│   ├── storage/
│   │   ├── migrations.py                 # wersjonowane, append-only (ADR-3)
│   │   ├── repositories/                 # generations, jobs, refs, usage…
│   │   ├── files.py                      # FileManager
│   │   ├── metadata.py                   # sidecary JSON
│   │   └── thumbnails.py                 # Pillow (nie sharp)
│   ├── services/generation.py            # jedyne wejście do generacji
│   ├── routes/  providers.py · generations.py · jobs.py  (+ istniejące)
│   ├── agent/                            # bez zmian + adapter (ADR-8)
│   └── …                                 # mcp, skills, hooks, lsp, acp — bez zmian
├── desktop/src/
│   ├── main/  secrets.ts (safeStorage) · mediaProtocol.ts     # NOWE (ADR-5)
│   └── renderer/src/
│       ├── lib/generated/models.ts       # generowane z Pythona (ADR-4)
│       └── components/  Image · Video · Gallery · GenQueue (przerobione)
│                        AssetInspector · Diagnostics          # NOWE (ADR-6)
└── docs/plans/PLAN_INTEGRACJI.md         # ten dokument
```

---

## 5. Fazy

Szacunki w dniach roboczych jednej osoby, przy założeniu znajomości obu kodów. Traktuj jako rząd wielkości, nie zobowiązanie.

### Faza 0 — Fundament i spike'i · ~3–5 dni

> **STATUS: ZAKOŃCZONA (2026-08-28).** Fundament gotowy i zielony, ADR-y spisane.
> SPIKE-1 dla GCP/ADC zakończony PASS: połączenie, Nano Banana 2, Omni, Veo oraz Veo extend.
> SPIKE-2 dla GCP/ADC również zakończony PASS. Decyzje O-1…O-5 są rozstrzygnięte.
> Szczegóły poniżej w „Wyniki Fazy 0".

**Cel:** działający, zbudowalny `Caelo_2.0` + rozbrojenie ryzyk, zanim zaczniemy pisać.

- Kopia `grok_desktop_app` → `Caelo_2.0`, z pominięciem `node_modules`, `dist*`, `build`, `.venv`, `caelo_history.db*`, `worktrees`, `caelo_audit.log`, `generated_history`.
- Weryfikacja: `npm install`, venv, `npm run dev`, `pytest`, `npm run typecheck && lint && test`. **Zielono zanim cokolwiek zmienimy.**
- Wpisanie decyzji ADR-1…8 do `CLAUDE.md` (jest źródłem prawdy dla współpracowników).
- **SPIKE-1 (blokujący): kształt drutu Google.** Ręczne wywołania REST: Nano Banana przez Vertex `generateContent` + ADC (wymagany tryb), Omni przez Agent Platform Interactions (`inline` + polling) oraz Veo 3.1 (`predictLongRunning` + `fetchPredictOperation` + extend). Cel: potwierdzić, że da się to zrobić bez SDK, i spisać rzeczywiste kształty odpowiedzi. **Zakończony PASS dla GCP/ADC.**
- **SPIKE-2: tool-calling Google.** Minimalna pętla: deklaracja narzędzia → `functionCall` → `functionResponse` → odpowiedź. Cel: potwierdzić wykonalność ADR-8 i wyłapać pułapki (`id`, `thoughtSignature`, kolejność części, streaming). **Zakończony PASS dla GCP/ADC.**
- Decyzje O-1…O-5 z §9 — **rozstrzygnięte 2026-08-28**.

**Gotowe, gdy:** `Caelo_2.0` buduje się i uruchamia identycznie jak oryginał, oba spike'i mają zapisane wyniki, ADR-y są w `CLAUDE.md`.

#### Wyniki Fazy 0

**Fundament — zrobione i zweryfikowane:**

| Krok | Wynik |
|---|---|
| Kopia repo | `git clone` zamiast ręcznych wykluczeń — `.gitignore` już koduje dokładnie to, czego nie chcemy. 421 plików, 6 MB drzewa, pełna historia (299 MB). |
| Sekrety | **Nie przeniesione** — `caelo_settings.json` (zawierał klucz xAI, 84 znaki), `caelo_auth.json`, `.env`, `caelo_history.db` są gitignorowane, więc klon jest z nich czysty. Zweryfikowane jawnie. |
| Zabezpieczenie gita | `origin` przemianowany na `caelo-1x`, upstream odpięty. `git push` bez argumentów **kończy się błędem** — nie da się przypadkiem zapisać do repo 1.x ani na publiczny GitHub. |
| Środowisko | venv (`requirements.lock` + dev) i `npm install` (750 pakietów) — bez błędów. |
| `pytest` | **13 passed** |
| `typecheck` | **czysto** (node + web) |
| `lint` | **0 błędów**, 2 ostrzeżenia (istniejące wcześniej, `exhaustive-deps` w `Image.tsx`/`Video.tsx`) |
| `vitest` | **53 pliki, 304 testy — passed** |
| `npm run build` | przechodzi (3 bundle do `out/`) |
| Smoke sidecara | Handshake poprawny: `__CAELO_CORE_READY__ {"port":…,"token":…,"version":"2.0.0-dev"}`. `/health` OK, `/models` **401 bez tokenu** (fail-closed potwierdzony), `/auth/status` i `/genjobs` odpowiadają. |

Przy okazji potwierdziły się dwie rzeczy z planu: `pillow` **jest już zależnością** sidecara,
więc ADR-3 (miniatury na Pillow zamiast `sharp`) nie kosztuje nic; a `/models` zwraca płaskie
listy nazw bez zdolności — dokładnie to, co zastępuje ADR-4.

**SPIKE-1 — zakończony PASS na żywo przez GCP/Vertex AI + ADC.**

28.08.2026 wykonano surowe wywołania REST, używając istniejącej sesji
`gcloud auth application-default login` (token nie został zapisany ani wyświetlony).
Gemini i Omni użyły lokalizacji `global`, a Veo regionalnego endpointu `us-central1`:

| Test | Wynik |
|---|---|
| `gemini-3.5-flash-lite:generateContent` | **PASS** — ADC, projekt i endpoint Vertex AI działają. |
| `gemini-3.1-flash-image:generateContent` | **PASS** — 1 obraz PNG 1:1/1K, 957 283 B; odpowiedź `inlineData`; usage: 12 tokenów tekstu + 1120 tokenów obrazu. |
| `gemini-omni-flash-preview` — Omni | **PASS** — text-to-video 4,011 s, MP4 1 197 579 B; Agent Platform Interactions API, wynik po około 31 s. |
| `veo-3.1-fast-generate-001` — text-to-video | **PASS** — 4,000 s, MP4 1 964 731 B; Vertex AI LRO, wynik po około 48 s. |
| `veo-3.1-fast-generate-001` — extend | **PASS** — wejście 4 s, wynik 11,000 s (oryginał + 7 s kontynuacji), MP4 5 092 957 B; około 48 s. |

Tym samym ADR-1 jest empirycznie potwierdzone dla obrazu i wymaganych ścieżek wideo
w trybie GCP/ADC. SPIKE-1 jest zamknięty; alternatywna ścieżka AI Studio nie blokuje Fazy 2.

**SPIKE-2 — zakończony PASS na żywo przez GCP/ADC.**

28.08.2026 model `gemini-3.5-flash` w lokalizacji `global` przeszedł pełną pętlę
tool-callingu surowym REST-em:

| Pytanie | Wynik |
|---|---|
| P1 — kształt | **PASS** — odpowiedź zawiera `candidates[].content.parts[].functionCall`. |
| P2 — identyfikatory | **PASS, korekta ADR-8** — oba wywołania miały natywne `id` (`call_*`); `functionResponse` musi powtórzyć odpowiadające `id`. |
| P3 — równoległość | **PASS** — `get_weather` i `get_time` wróciły jako dwie uporządkowane części `[0, 1]`. |
| P4 — runda zwrotna | **PASS** — po zwróceniu dwóch wyników model odpowiedział tekstem: pogoda 12°C, lekki deszcz, godzina 14:30. |
| P5 — streaming | **PASS** — 5 zdarzeń SSE, 3 fragmenty `functionCall`; argument `city="Warsaw"` złożony z `partialArgs[]` po `jsonPath`. |

Pierwszy równoległy `functionCall` zawierał `thoughtSignature`, drugi nie — zgodnie z regułą
podpisu na pierwszej części grupy równoległej. Rundę zwrotną wykonano w prawidłowym
kontrakcie: pełna oryginalna część modelu wraz z podpisem, a następnie dokładnie dwa
`functionResponse` z dopasowanymi nazwami i identyfikatorami. Streaming rozpoczął się częścią
z `name`, `id`, `thoughtSignature` i `willContinue`; kolejne części niosły `partialArgs`
(`jsonPath`, wartość, `willContinue`), a zakończenie — pusty `functionCall` i `finishReason=STOP`.

ADR-8 jest wykonalne, ale adapter musi być tolerancyjny: zachowywać natywne ID modeli Gemini 3.x,
syntezować je tylko dla starszych odpowiedzi bez ID, przechowywać podpisy bez modyfikacji oraz
mieć akumulator `partialArgs` obsługujący pełne JSONPath.

**Analiza statyczna pozostałych powierzchni API.**

Główną niewiadomą ADR-1 dało się rozstrzygnąć bez sieci: SDK `@google/genai@2.17.1` leży
w `node_modules` Gemini Studio, a jego bundle zawiera realne ścieżki REST. Okazało się, że SDK
nie robi żadnej magii — składa zwykłe ścieżki HTTP z `x-goog-api-key` (AI Studio) albo
`Authorization: Bearer` (Vertex AI):

```
POST /v1beta/interactions                    ← AI Studio Interactions
GET|DELETE /v1beta/interactions/{id}         ← AI Studio: + POST .../cancel
POST /v1beta/models/{model}:generateContent  ← AI Studio generateContent
POST /upload/v1beta/files                    ← AI Studio Files API (resumable)
POST /v1beta1/projects/{project}/locations/{location}/publishers/google/models/{model}:generateContent
                                              ← Vertex AI / ADC: Gemini i obraz
POST /v1beta1/projects/{project}/locations/global/interactions
GET  /v1beta1/projects/{project}/locations/global/interactions/{id}
                                              ← Agent Platform / ADC: Omni
POST /v1/projects/{project}/locations/{region}/publishers/google/models/{model}:predictLongRunning
POST /v1/projects/{project}/locations/{region}/publishers/google/models/{model}:fetchPredictOperation
                                              ← Vertex AI / ADC: Veo i extend
```

Pełny wykaz i kontekst: [`scripts/spikes/README.md`](../../scripts/spikes/README.md).

**To obniża R1 z wysokiego na średnie, a dla przetestowanej ścieżki GCP/ADC — do niskiego.**
Na żywo potwierdzono zarówno ścieżki, jak i ciała żądań: Interactions API dla Omni oraz
`instances[]` / `parameters{}` dla Veo. Ryzykiem pozostają zmiany powierzchni preview i modeli,
dlatego registry i parser odpowiedzi nadal muszą być tolerancyjne.

Znaleziska z testów wideo, które wiążą implementację Fazy 2:

- `OmniVideoProvider.ts` dawcy ma nieaktualną blokadę trybu GCP. Agent Platform Interactions API
  działa z ADC; tej blokady nie przenosimy.
- `delivery: "uri"` bez `gcs_uri` kończy się `invalid_request`. Domyślnie odbieramy wynik
  jako `inline`; URI udostępniamy dopiero po skonfigurowaniu bucketa GCS.
- Veo przez Vertex używa wersji `v1`, regionalnego endpointu `us-central1` i modelu GA
  `veo-3.1-fast-generate-001`, nie wycofywanego identyfikatora `*-preview`.
- Po submitcie trzeba utrwalić `operation.name` przed rozpoczęciem pollingu. Wynik jest dostępny
  jako `response.videos[].bytesBase64Encoded`; extend zwraca cały sklejony film.

Dwa znaleziska uboczne, które **poprawiają** plan:
- `GET /interactions/{id}` przyjmuje `stream` **i `last_event_id`** → wznawialny strumień SSE.
  Kolejka w Fazie 3 może po restarcie *podjąć strumień*, nie tylko odpytać o stan.
- Istnieje `POST /interactions/{id}:cancel`. Gemini Studio przy anulowaniu zatrzymuje wyłącznie
  polling lokalny; w Caelo 2.0 możemy faktycznie przerwać zdalną pracę — i przestać za nią płacić.

**Spike'i znajdują się w `scripts/spikes/`**, wyłącznie na `requests`. Tryb Vertex pobiera
krótko żyjący token ADC z Google Cloud SDK; tryb AI Studio czyta klucz tylko ze zmiennej
środowiskowej. Wszystkie generacje obrazu i wideo mają jawną bramkę kosztową.

**Znalezisko bezpieczeństwa — do Twojej decyzji, nieruszane.**

`npm audit` na świeżym fundamencie: **Electron 42.3.2 jest objęty krytycznym advisory**
(GHSA-q6m5-f73j-m9mc — heap buffer under/overflow; zakres podatny `42.0.0-alpha.1 – 42.5.0`).
Dostępne jest **42.9.3**, a manifest (`^42.3.2`) już je dopuszcza — pinuje wyłącznie lockfile:

```bash
npm --prefix desktop update electron
```

Nie zastosowałem tego, bo kryterium wyjścia Fazy 0 brzmi „buduje się i uruchamia **identycznie**
jak oryginał", a podbicie Electrona to zmiana zachowania. Rekomendacja: **zrobić to pierwszym
commitem po zamknięciu Fazy 0.** Reszta krytycznych/wysokich wpisów (`tar`, `node-gyp`, …) siedzi
w drzewie `electron-builder` — build-time, nie shipowane; ich naprawa wymaga majora
`electron-builder` 26 i powinna poczekać na Fazę 7 (packaging).

### Faza 1 — Warstwa providerów, xAI jako pierwszy obywatel · ~5–8 dni

**Cel:** abstrakcja istnieje i xAI już za nią stoi. **Zero zmian widocznych dla użytkownika.**

- `providers/base.py` — port kontraktów z `providers.ts` na `Protocol`/ABC: `ImageProvider`, `VideoProvider`, `ChatProvider`, plus `VideoSubmission` / `VideoPollStatus` (utrwalany uchwyt zdalny).
- `providers/errors.py` — taksonomia z `api/gemini/errors.ts`, rozszerzona o błędy xAI. Kategoria błędu decyduje o retry (§ADR-2).
- `providers/xai/` — adapter nad `api_manager.APIManager` (ADR-7).
- `models/registry.py` + `capabilities.py` + definicje modeli xAI wydobyte z rozproszonych `if`-ów.
- `models/pricing.py` — scalenie `genjobs.estimate_cost` i `jobs/costs.ts`.
- Nowe route'y `GET /providers`, `GET /models`, `GET /capabilities`.
- `providers/mock/` — pełny MockProvider dla obu providerów.

**Gotowe, gdy:** wszystkie istniejące testy `caelo_core` przechodzą, generacja obrazu/wideo xAI działa **przez nową abstrakcję**, `/models` zwraca zdolności, mock pozwala pracować bez kosztów.

**Ryzyko:** kuszące będzie „przy okazji" poprawić `api_manager.py`. Nie robimy tego (ADR-7).

**Wykonano 2026-08-28 — Faza 1 zakończona.**

- Dodano neutralne kontrakty `ImageProvider`, `VideoProvider`, `ChatProvider`, struktury
  wyników mediów oraz `VideoSubmission` / `VideoPollStatus`.
- Dodano wspólną taksonomię błędów z jawną flagą `retryable`; błędy sieciowe, timeouty,
  chwilowe 5xx i burst rate-limit są ponawialne, a auth, quota, safety i błędne wejście — nie.
- `providers/xai/` opakowuje istniejący `APIManager`; pliki korzeniowe objęte ADR-7 pozostały
  nietknięte. Wszystkie produkcyjne ścieżki obrazu/wideo (kolejka, legacy routes i narzędzie
  obrazu w czacie) przechodzą przez adapter.
- Rejestr modeli i `CapabilityGuard` walidują model, operację, rozdzielczość, proporcje,
  jakość, czas oraz limity referencji przed zakolejkowaniem płatnej pracy.
- Cennik xAI i estymator z Gemini zostały scalone w `models/pricing.py`; stare importy
  `genjobs.estimate_cost` zachowano jako kompatybilny re-eksport.
- `GET /providers`, rozszerzone `GET /models` (także filtry `provider`/`media_type`) oraz
  `GET /capabilities` zwracają maszynowo czytelny katalog. Dotychczasowy kształt `/models`
  pozostał, więc renderer nie zmienił zachowania; dodano mu typy i klienty nowych tras.
- Lokalny `MockProvider` obsługuje obraz, wideo i czat, zapisuje artefakty przez ten sam
  pipeline i zawsze ma koszt `0.0`.
- Weryfikacja: backend `20 passed`, testy renderera `304 passed`, TypeScript bez błędów,
  ESLint bez błędów (pozostają 2 wcześniejsze ostrzeżenia hooków). Test tras obejmuje nowe
  endpointy. Dwa testy tree-kill wymagają normalnego środowiska procesu Windows; pełny bieg
  poza sandboxem przeszedł.

### Faza 2 — Google jako provider mediów · ~8–12 dni

> **STATUS: ZAKOŃCZONA (2026-08-28).** Adaptery mediów Google, oba tryby auth,
> katalog 8 modeli, upload/cache plików, cennik i konfiguracja aplikacji są zaimplementowane.

**Cel:** Nano Banana, Omni i Veo generują, wyniki lądują w istniejącej galerii.

- `providers/google/client.py` — transport (auth, retry, mapowanie błędów), wzorowany na `responses_client.py`.
- `providers/google/image.py` — Nano Banana 2 / Pro / Lite / legacy; port `ImageRequestBuilder.ts` (role referencji, limity, thinking, search grounding).
- `providers/google/video.py` — Omni (Interactions + polling + streaming download) i Veo (LRO, extend, first/last frame).
- `providers/google/files.py` — upload plików + `remote_file_cache` (deduplikacja po sha256, obsługa wygaśnięcia URI).
- `models/google_models.py` — port `imageModels.ts` + `videoModels.ts` 1:1, ze wszystkimi zdolnościami i limitami.
- Cennik Google + prognoza kosztu przed wysłaniem.

**Gotowe, gdy:** dla każdego z 8 modeli Google przechodzi generacja end-to-end, plik ląduje na dysku, artefakt w galerii, koszt w `usage_records`.

**Ryzyko:** modele są w statusie `preview` — kształt API może się zmienić. Mitygacja: tolerancyjny parser (wzorzec z `responses_client.py`: *„parser jest TOLERANCYJNY na kształt"*).

**Wykonano 2026-08-28 — Faza 2 zakończona.**

- Dodano lekki klient REST Google bez `google-genai`: ADC pozyskiwane przez `google-auth`,
  wywołania nadal realizuje `requests`. Obsługiwane są Vertex/Agent Platform oraz alternatywny
  klucz AI Studio; klucz nigdy nie wraca z `/settings` ani nie trafia do URL.
- Dodano konfigurację Google w ustawieniach Caelo: tryb uwierzytelnienia, Cloud Project ID,
  osobne lokalizacje obrazów i wideo oraz jednokierunkowe przechowywanie/usuwanie klucza AI Studio.
- `providers/google/image.py` obsługuje cztery modele Nano Banana, role referencji, limity,
  thinking, Search grounding, PNG/JPEG i tolerancyjne wydobywanie `inlineData`.
- `providers/google/video.py` obsługuje Gemini Omni przez Interactions oraz trzy warianty Veo
  przez LRO. Zaimplementowano text/image/reference-to-video, first/last frame, edit/extend,
  polling, pobieranie URI i tolerancyjny parser odpowiedzi Vertex/AI Studio.
- `providers/google/files.py` realizuje resumable upload do Gemini Files API oraz cache SHA-256
  z deduplikacją i wygasaniem. Cache jest na razie procesowy; jego trwały odpowiednik jest częścią
  migracji `remote_file_cache` w Fazie 3.
- Registry udostępnia łącznie 8 modeli Google (4 obrazu + Omni + 3 Veo) wraz z deklaratywnymi
  zdolnościami, limitami czasu, rozdzielczościami, referencjami, natywnym audio i rozszerzaniem.
- Cennik Google rozróżnia wariant i rozdzielczość wideo; koszt jest zapisywany w istniejącym
  `gen_jobs.cost`. Docelowy znormalizowany `usage_records` powstaje wraz ze schematem Fazy 3 —
  nie wprowadzono przedwcześnie częściowej migracji bazy.
- Test połączenia jest dostępny jako `POST /providers/{provider_id}/validate`; nie uruchamia
  płatnej generacji.
- Weryfikacja kontraktowa end-to-end obejmuje każdy z 8 modeli: submit/generate, polling,
  zapis pliku na dysku i artefakt galerii. Pełny wynik: backend **45 passed**, renderer
  **53 pliki / 304 testy passed**, TypeScript bez błędów, build produkcyjny przechodzi,
  ESLint bez błędów (pozostają 2 wcześniejsze ostrzeżenia hooków).
- Płatnych testów live wszystkich ośmiu wariantów nie powtarzano. Ich wspólne transporty zostały
  wcześniej potwierdzone na żywo w Fazie 0 dla Nano Banana, Omni, Veo Fast i Veo extend;
  pozostałe warianty pokrywają deterministyczne fixture'y kontraktów REST.

### Faza 3 — Trwała kolejka i warstwa plików · ~8–12 dni

**Status: ZAKOŃCZONA 2026-08-28.**

**Cel:** obie ścieżki generacji chodzą przez jedną kolejkę, która nie gubi płatnej pracy.

- `storage/migrations.py` — wersjonowany runner + migracja 001 (nowe tabele mediów).
- `storage/repositories/` — port repozytoriów Gemini na `sqlite3` (bez ORM — Caelo go nie używa).
- `jobs/queue.py` — port maszyny stanów. **Uwaga na model współbieżności:** Gemini używa jednego ticka `setInterval` na pętli zdarzeń; Caelo ma pulę wątków. Cel: pojedynczy wątek-scheduler + pula workerów, z blokowaniem wiersza (`locked_at`) jako sekcją krytyczną — tak jak w oryginale.
- `jobs/recovery.py` — port `JobRecovery`, uruchamiany przy starcie sidecara.
- `jobs/retry.py` — backoff z jitterem, decyzja o retry na podstawie kategorii błędu.
- `storage/files.py` + `metadata.py` + `thumbnails.py` — struktura workspace, sidecary JSON, miniatury (Pillow), kosz datowany, **streaming do `.part` i atomowy rename**.
- `services/generation.py` — port `GenerationApplicationService`: guard → cost guard → utrwalenie → zakolejkowanie, dla **obu** providerów.
- `mediaProtocol.ts` w Electronie + przełączenie `ArtifactMedia.tsx` na `caelo-media://` (usuwa problem 1.3.C).
- **Usunięcie `caelo_core/genjobs.py`** i przekierowanie `/genjobs` na nowe API (z zachowaniem kompatybilności kształtu odpowiedzi lub jawnym bumpem).

**Gotowe, gdy:** zabicie sidecara w trakcie generacji Veo i restart → zadanie wznawia polling i kończy się sukcesem; zabicie w trakcie submitu → `UNKNOWN_REMOTE_STATE`, brak automatycznego ponowienia; klip 4K odtwarza się z przewijaniem bez skoku pamięci renderera.

**Ryzyko: najwyższe w całym planie.** Dotykamy działającego kodu produkcyjnego i bazy użytkownika. Migracja musi być testowana na kopii realnego `caelo_history.db` (260 MB).

**Wynik realizacji.** Dodano wersjonowane migracje i repozytoria `sqlite3` dla generacji,
wejść/wyjść, kolejki, użycia i cache plików zdalnych. Stary import `caelo_core.genjobs`
pozostał wyłącznie jako zgodnościowy re-eksport nowego `caelo_core.jobs`; produkcja używa
pojedynczego schedulera, puli workerów i blokad `locked_at`. Uchwyt operacji zdalnej jest
utrwalany przed pollingiem. Recovery wznawia `PROCESSING`, gdy uchwyt istnieje, a stan
`SUBMITTING` bez uchwytu zmienia na `UNKNOWN_REMOTE_STATE` bez automatycznego ponowienia.

Pliki trafiają strumieniowo do `.part`, po `fsync` są atomowo przemianowywane, mają
sidecar JSON i miniaturę obrazu; usuwanie może używać datowanego `.trash`. Cache Google
Files oraz rekordy szacowanego użycia są trwałe. Electron obsługuje chroniony
`caelo-media://artifact/<id>` i przekazuje nagłówek HTTP `Range`, więc odtwarzacz nie
tworzy pełnego Blob-a filmu w rendererze.

Testy odbiorcze pokryły oba scenariusze restartu, zapis atomowy, sidecar, kosz i odpowiedź
`206 Partial Content`. Migrację wykonano na spójnej kopii rzeczywistej bazy użytkownika,
która w dniu testu miała **1 903 747 072 bajty** (planowane 260 MB było już nieaktualne):
rozmiar kopii był identyczny, zastosowano migracje 1–2, a `PRAGMA quick_check` zwrócił `ok`.

### Faza 4 — Fuzja UI mediów · ~6–9 dni

**Status: ZAKOŃCZONA 2026-08-28.**

**Cel:** jeden moduł Image i jeden Video, z wyborem providera.

- Picker `[Provider ▾][Model ▾]` w `Image.tsx` i `Video.tsx`.
- Formularz budowany z `/capabilities` — nieobsługiwane opcje znikają, nie są wyszarzane (wzorzec Gemini).
- Generator typów TS z registry Pythonowego + krok w `typecheck`.
- `GenQueue.tsx` — 13 stanów, progres pobierania, retry/cancel, wyróżniony `UNKNOWN_REMOTE_STATE` z wyjaśnieniem.
- `Gallery.tsx` — filtr po providerze, lineage edycji, ulubione, tagi.
- **`AssetInspector.tsx`** i **`DiagnosticsPage`** — nowe, w kicie UI Caelo (ADR-6).
- Biblioteka referencji z rolami zależnymi od modelu: character / general / object /
  style / starting image oraz osobnymi limitami każdej kategorii.

**Gotowe, gdy:** użytkownik przełącza xAI ↔ Google w jednym formularzu i formularz sam się dostosowuje; jedna galeria pokazuje wyniki obu providerów.

**Wykonano 2026-08-28 — Faza 4 zakończona.**

- Moduły Image i Video mają wspólny picker provider/model oraz renderują wyłącznie
  kontrolki obsługiwane przez wybrany descriptor z `/capabilities`.
- Registry Pythona generuje commitowany snapshot i unie typów TS; `typecheck` odrzuca
  nieaktualny plik generowany.
- Kolejka pokazuje pełne stany trwałej maszyny, postęp, próby i specjalne ostrzeżenie
  `UNKNOWN_REMOTE_STATE` przed świadomym ponowieniem płatnego żądania.
- Galeria filtruje xAI/Google, przechowuje ulubione i tagi, a Asset Inspector pokazuje
  metadane oraz lineage źródeł i pochodnych.
- Dodano bibliotekę referencji character/general/object/style/starting image z limitami
  kategorii zależnymi od modelu i przekazywaniem ról do providerów. `General` jest
  bezpieczną rolą domyślną, `Starting Image` ma limit jednej pozycji, a `Style` jest
  dostępne tylko w modelach, które je obsługują. Dodano też osobną stronę Diagnostics
  z kolejką, schematem i testami połączeń.
- Żądania obrazowe Google jawnie ustawiają generowanie osób dorosłych (`ALLOW_ADULT`)
  oraz `OFF` dla czterech konfigurowalnych filtrów. Niewyłączalne blokady Google są
  mapowane na szczegółowe kody (`IMAGE_SAFETY`, `PROHIBITED_CONTENT`, `BLOCKLIST`)
  i nie są automatycznie ponawiane; pusta odpowiedź techniczna pozostaje ponawialna.

### Faza 5 — Gemini w czacie · ~5–8 dni

**Cel:** Gemini 2.5/3.x jako alternatywa w module Chat.

- `providers/google/chat.py` — streaming SSE, wizja, długi kontekst, mapowanie na neutralny format zdarzeń czatu Caelo.
- Rozszerzenie `ChatProvider` o to, co Caelo ma dziś na Responses API — i **jawne oznaczenie, czego Google nie ma** (live search X!). Model zdolności obejmuje też czat: gdy provider nie wspiera funkcji, kontrolka znika.
- Picker providera w `ChatView.tsx`, per konwersacja.

**Gotowe, gdy:** rozmowa z Gemini streamuje, obsługuje obrazy, a funkcje niedostępne u Google są ukryte, nie zepsute.

**Uwaga:** to jest budowa od zera. Ani Caelo, ani Gemini Studio nie mają czatu tekstowego Google.

**Status: ZAKOŃCZONA 2026-08-31 — test live użytkownika PASS.**

- Dodano adapter `providers/google/chat.py` i klient SSE `streamGenerateContent` dla
  Vertex AI/ADC oraz AI Studio/API key. Neutralny wynik zawiera tekst, cytowania,
  użycie tokenów i liczbę wywołań narzędzi.
- Historia, instrukcja systemowa, obrazy i PDF są mapowane na format Gemini. Pliki
  Office otrzymują jawny komunikat o braku obsługi zamiast ogólnego błędu sieci.
- Picker xAI/Google i modelu działa per rozmowa. Dla Google znika wyszukiwanie web/X
  z Responses API, a ustawienia temperature/effort są pokazywane wyłącznie zgodnie
  z descriptorami modelu.
- Testy kontraktowe pokrywają payload, Unicode SSE, użycie, cytowania, blokady treści,
  zamykanie strumienia HTTP i registry. Test live na koncie Google/Vertex potwierdził
  streaming odpowiedzi Gemini w module Chat.

### Faza 6 — Gemini jako silnik agenta · ~8–12 dni

**Cel:** moduł Code działa na Google z tymi samymi gwarancjami bezpieczeństwa.

- Neutralny format tool-callingu na granicy `agent/llm.py` (ADR-8).
- `providers/xai/tools.py` — refaktor istniejącego kodu do adaptera (nie powinien zmienić zachowania).
- `providers/google/tools.py` — `functionDeclarations` ↔ `functionCall`/`functionResponse`, synteza identyfikatorów.
- Picker silnika agenta w `AgentPanel.tsx`.
- **Testy równoważności** — ta sama sesja, oba providery: approval gate, loop guard, checkpointy, syntetyczne wyniki przerwanych narzędzi, scrubbed env.

**Gotowe, gdy:** zestaw równoważnościowy przechodzi na obu providerach. **Dopóki nie przechodzi, agent na Google zostaje za flagą.** Agent ma dostęp do plików i powłoki — to nie jest miejsce na „prawie działa".

**Zakończona i odebrana 2026-08-31 — połączenie, narzędzia oraz selektory providera
i modelu potwierdzone live przez użytkownika.**

- `agent/llm.py` definiuje neutralną wiadomość asystenta i wywołanie narzędzia;
  dotychczasowy transport xAI przeniesiono bez zmiany protokołu do
  `providers/xai/tools.py`.
- `providers/google/tools.py` mapuje deklaracje i historię na Gemini, zachowuje
  natywne identyfikatory oraz `thoughtSignature`, syntetyzuje ID wyłącznie przy ich
  braku, składa `partialArgs` po pełnym JSONPath i zwraca równoległe
  `functionResponse` w kolejności wywołań.
- Runner, WebSocket, trwałe sesje i subagenci przenoszą provider razem z modelem.
  Narzędzie `web_search` oparte o xAI nie jest reklamowane ani wykonywane przez
  agenta Google.
- W `AgentPanel` dodano picker xAI / Google Gemini; wybór modelu jest ograniczony
  do modeli czatowych z obsługą narzędzi i zapisywany w ustawieniach/sesji.
- Zestaw równoważnościowy przechodzi dla obu providerów: approval gate,
  checkpointy, loop guard, syntetyczne wyniki przerwanych wywołań oraz scrubbed env.
  Testy kontraktowe faz 1–6: **68 PASS**; frontend: **330 PASS**, lint i typecheck PASS.
- Test użytkownika potwierdził połączenie z Google i wykonywanie narzędzi przez agenta.
  Naprawiono układ nagłówka, który ściskał selektor modelu do zerowej szerokości, oraz
  dodano bezpieczny fallback dla starszej pamięci podręcznej katalogu modeli.
- Nie zbudowano instalatora — zgodnie z decyzją użytkownika. Widoczność i działanie
  poprawionego selektora modelu zostały potwierdzone w teście live.

### Faza 7 — Sekrety, migracja, hardening, wydanie · ~5–8 dni

- `secrets.ts` (`safeStorage`) + kanał przekazywania do sidecara (ADR-5).
- Jednorazowa migracja plaintextowych sekretów do sejfu + wyczyszczenie plików.
- Migracja danych użytkownika (§6), testowana na kopii realnej bazy.
- Aktualizacja `caelo_core.spec` (nowe moduły, `hiddenimports`), weryfikacja rozmiaru instalatora.
- **Przepisanie README, SECURITY.md i sekcji prywatności** — patrz §8.1.
- Aktualizacja `docs/guides/API.md`, `USER_GUIDE.md`, `CHANGELOG.md`, `CLAUDE.md`.
- Podpisany build Win + macOS + Linux, smoke na czystej maszynie.

**Implementacja lokalna zakończona 2026-08-31.**

- Electron main jest właścicielem wersjonowanego `secrets.dat`, szyfrowanego przez
  `safeStorage`. Migracja najpierw utrwala zaszyfrowaną kopię, a dopiero potem usuwa
  klucze z `caelo_settings.json` i kasuje poprawny `caelo_auth.json`; operacja jest
  idempotentna i nie czyści plaintextu, gdy szyfrowanie zawiedzie.
- Oddzielny token kanału sekretów jest podawany sidecarowi przez stdin, nie argv ani
  środowisko. Prywatne endpointy import/export nie akceptują publicznego tokenu sesji,
  nie są publikowane w OpenAPI, a Python przechowuje klucze i OAuth wyłącznie w pamięci.
- Migracja SQLite v4 tworzy kopię przez SQLite Backup API przed zmianą i dodaje nullable
  `artifacts.generation_output_id` bez backfillu. `scripts/verify_phase7_migration.py`
  uruchomiono na kopii rzeczywistej bazy użytkownika z `%LOCALAPPDATA%\Caelo`
  (119 070 720 B): `integrity_check=ok`, wersje 1–4 oraz liczniki zachowane — 1117
  artefaktów, 1162 zdarzenia/rekordy FTS, 3 projekty i 288 legacy `gen_jobs`.
  Plik źródłowy pozostał otwarty wyłącznie do odczytu i nie został zmieniony.
- Spec PyInstallera zawiera moduły sekretów i migracji oraz wyklucza testy. Zbudowany
  sidecar ma 70,85 MiB (spadek z 75,62 MiB), uruchamia się i odpowiada poprawnie na
  uwierzytelnione `/whoami`.
- Lokalny unsigned NSIS Windows 2.0.7 ma 129,91 MiB (SHA-256
  `C7CA87E25FE1135744118ABEAF93A0180D73AA27E932207EE86E35504A6633C0`). Smoke
  rozpakowanej aplikacji potwierdził start Electron i spakowanego sidecara na Windows.
- **Aktualizacja 2026-09-01:** na maszynie użytkownika jest już certyfikat i `signtool`,
  więc build 2.0.8 wyszedł **podpisany** (`Get-AuthenticodeSignature` → `Valid`, CN=AuraVix
  Studio Marcin Stelmach). `Caelo-Setup-2.0.8.exe` ma 129,77 MiB (SHA-256
  `E4E55AC389A8E14F92DA76F1FB585DC77DD3B79A423E531BF48E25045BFA22FC`), a `sidecar_smoke`
  przeszedł na spakowanym `caelo-core.exe` przed spakowaniem instalatora. Poniższy akapit
  o braku certyfikatu na hoście dotyczy stanu z fazy 7 i nie obowiązuje dla Windows.
- Dokumentacja README, SECURITY/privacy, API, USER_GUIDE, CHANGELOG, CLAUDE i NOTICE
  opisuje obu providerów, ADC oraz nowy model przechowywania poświadczeń.
- Testy kontraktowe faz 1–7: **72 PASS**; testy sejfu/IPC: **6 PASS**; lint i typecheck:
  **PASS**. `genjobs_check` przechodzi po dostosowaniu do zewnętrznych payloadów.
- **Pozostaje krok infrastrukturalny, nie kodowy:** ten host nie ma certyfikatu
  Authenticode ani `signtool`, a buildów macOS/Linux nie można wiarygodnie wykonać na
  Windows. Podpisany Windows, notaryzowany macOS, Linux i smoke na czystych maszynach
  muszą zostać wykonane przez istniejący pipeline per-OS po dostarczeniu sekretów
  podpisujących. Lokalnego unsigned builda nie oznaczamy jako wydania produkcyjnego.

**Suma: ~48–74 dni roboczych.** Fazy 0–4 (~30–46 dni) dają samodzielnie wartościowy produkt: pełne studio mediów dwóch providerów z porządną kolejką. Fazy 5–6 to rozszerzenie, które można wydać później.

---

## 6. Migracja danych

Baza użytkownika ma **260 MB** (+15 MB WAL). Zasada: **nic nie przepisujemy masowo.**

| Element | Działanie |
|---|---|
| `artifacts` | Zostaje. Nowa kolumna `generation_output_id` (nullable). Legacy = NULL, działa dalej. **Bez backfillu.** |
| `history_events`, `history_fts`, `event_embeddings` | Nietknięte. |
| `projects`, `collection_files` | Nietknięte. |
| `gen_jobs` | Zakończone → skopiowane do nowego `generations`/`jobs` jako historia. Aktywne przy migracji → `UNKNOWN_REMOTE_STATE` (nie znamy uchwytów zdalnych — to poprawna, konserwatywna odpowiedź). Stara tabela zostaje przez jedno wydanie, potem usuwana. |
| Nowe tabele mediów | Dodane migracją 001. |
| `caelo_settings.json` | Pola sekretne → sejf, potem usunięte z pliku. Reszta ustawień zostaje. |
| `caelo_auth.json` | Tokeny OAuth → sejf, plik usuwany. |
| Pliki mediów (`generated_history/`) | **Nie ruszamy.** Nowe generacje idą w nową strukturę workspace; stare ścieżki nadal rozwiązywalne. |

**Wymagane przed wydaniem:** automatyczny backup bazy przed migracją (Caelo ma już `_backup_corrupt` — ten sam mechanizm), test na kopii realnego pliku 260 MB, ścieżka wycofania.

---

## 7. Ryzyka

| # | Ryzyko | Waga | Mitygacja |
|---|---|---|---|
| R1 | Kształt API Google inny niż zakłada kod TS; modele w `preview` | ~~Wysoka~~ → **Średnia ogólnie / niska dla przetestowanej ścieżki GCP** (Faza 0) | **SPIKE-1 PASS na żywo:** potwierdzone `generateContent`, Agent Platform Interactions, Veo `predictLongRunning` / `fetchPredictOperation` i extend przez ADC. Test wykrył nieaktualną blokadę GCP w kodzie dawcy oraz wymóg `gcs_uri` dla `delivery: "uri"`. Nadal stosować registry modeli i tolerancyjne parsery, bo powierzchnie preview mogą się zmieniać. |
| R2 | Faza 3 psuje działającą kolejkę / bazę użytkownika | **Wysoka** | Migracja append-only, backup przed, test na kopii 260 MB, mock provider do testów bez kosztów, wycofanie. |
| R3 | Agent na Google zachowuje się inaczej niż na xAI — ma dostęp do plików i powłoki | **Wysoka** | Testy równoważności jako warunek wyjścia z Fazy 6. Flaga do czasu zaliczenia. |
| R4 | Rozjazd registry Python ↔ typy TS | Średnia | Generowanie + porównanie w CI (ADR-4). |
| R5 | Rozrost sidecara w PyInstallerze | Średnia | ADR-1 (bez SDK). Pomiar rozmiaru w Fazie 7. |
| R6 | Ograniczenia regionalne Google (edycja wideo w EEA/CH/UK — `regionalNotes` w `videoModels.ts`) | Średnia | Zdolności regionalne w registry; komunikat w UI zamiast błędu z API. |
| R7 | „Przy okazji" refaktor modułów korzenia | Średnia | ADR-7 wpisane do `CLAUDE.md`; sprawdzenie w code review. |
| R8 | Zakres pełzający — 4 fazy to już produkt, 7 to podwojenie | Średnia | Świadome wydanie po Fazie 4 jako punkt decyzyjny. |

---

## 8. Co integracja zmienia — konsekwencje zaakceptowane

### 8.1. Obietnica prywatności Caelo przestaje być prawdziwa w obecnym brzmieniu

To najpoważniejsza konsekwencja nietechniczna i nie da się jej obejść implementacją.

README Caelo mówi dziś dosłownie: *„A fresh install talks only to `api.x.ai`"*, ma diagram z podpisem **„← the only outbound destination"** i punkt **„No third-party servers — nothing is sent anywhere except xAI's own API"**. Po integracji drugim celem wychodzącym jest `generativelanguage.googleapis.com` (a przy trybie Vertex — kolejne domeny Google).

Sama obietnica *„local-first, bring-your-own-key, zero telemetrii"* pozostaje w mocy i nadal jest prawdziwa. Ale zdania o **jednym** celu wychodzącym trzeba przepisać, nie doprecyzować. Dotyczy to README, `SECURITY.md` i strony projektu. Do tego dochodzi drugi zestaw warunków korzystania i drugi model retencji danych po stronie dostawcy — użytkownik powinien to zobaczyć w Settings przy wprowadzaniu klucza Google.

**Decyzja zaakceptowana (O-2):** przed wydaniem aktualizujemy README, `SECURITY.md`, stronę
projektu i ekran ustawień. Użytkownik ma widzieć, do którego providera trafią jego dane.

### 8.2. Licencja

Caelo: **Apache-2.0**, publiczne repo GitHub, CLA, CONTRIBUTING, Code of Conduct.
Gemini Desktop Studio: **UNLICENSED**, `"private": true`.

Wciągnięcie architektury Gemini Studio do Caelo 2.0 czyni implementację Caelo 2.0
Apache-2.0 i publiczną. Decyzja O-1 to potwierdza. Szczegółowa wewnętrzna specyfikacja
Gemini Desktop Studio pozostaje poza publicznym zakresem wydania.

### 8.3. Marka i pozycjonowanie

README: *„Every mode of xAI's Grok — in one desktop app"*. Nazwa **Caelo** („every mode under one sky") na szczęście skaluje się na wielu providerów. Ale cały tekst, banner, screenshoty i `NOTICE` (znaki towarowe xAI) wymagają aktualizacji — dochodzą znaki towarowe Google.

### 8.4. Powierzchnia ataku: service account GCP

`GeminiClient.ts` wspiera tryb `gcp` ze **ścieżką do pliku klucza service accountu**. W aplikacji BYO-key z obietnicą „klucz nigdy nie opuszcza maszyny" wprowadzenie długożyjącego poświadczenia GCP z potencjalnie szerokimi uprawnieniami to jakościowo inna kategoria sekretu niż klucz API. Decyzja O-3 wybiera ADC; obsługi pliku service account nie przenosimy do zakresu Caelo 2.0.

---

## 9. Otwarte pytania

Nie blokują startu Fazy 0 i 1, ale muszą być rozstrzygnięte przed odpowiednimi fazami.

**O-1 · Publikacja — ROZSTRZYGNIĘTE 2026-08-28.** Caelo 2.0 pozostaje publicznym repo
Apache-2.0 na GitHubie. Wewnętrzna specyfikacja Gemini Desktop Studio nie jest częścią
publicznego zakresu wydania.

**O-2 · Zmiana obietnicy prywatności — ROZSTRZYGNIĘTE 2026-08-28.** Zmiana jest
zaakceptowana. README, SECURITY i ekran ustawień mają jasno wskazywać, że dane trafiają do
wybranego providera xAI albo Google. Deklaracje local-first, BYO credentials i zero telemetrii pozostają.

**O-3 · Tryb auth Google — ROZSTRZYGNIĘTE 2026-08-28.** GCP/Vertex przez ADC jest
wymaganym trybem, ponieważ tak działa obecna konfiguracja użytkownika. Klucz AI Studio pozostaje
alternatywą. `google-auth` jest dopuszczone wyłącznie do ADC; projekt i region nie są sekretami.

**O-4 · Wydanie po Fazie 4 — ROZSTRZYGNIĘTE 2026-08-28.** „Studio mediów dwóch
providerów" wychodzi jako **Caelo 2.0**, a czat i agent Google później jako **Caelo 2.1**.

**O-5 · Los starych repozytoriów — ROZSTRZYGNIĘTE 2026-08-28.** `grok_desktop_app`
i `gemini-desktop-studio` pozostają osobnymi projektami. Nie archiwizujemy ich, nie usuwamy
i nie modyfikujemy w ramach prac nad Caelo 2.0.

**O-6 · Voice.** Moduł Voice zostaje xAI-only? Gemini Omni generuje natywne audio w wideo, ale to nie jest odpowiednik TTS/STT. Rekomendacja: **poza zakresem 2.0**.

**O-7 · Tożsamość projektów.** Caelo ma projekty czatu (`kind='chat'`) i workspace'y Code (`kind='code'`), rozdzielone świadomie w M22. Gemini ma projekty z `root_path` i drzewem workspace mediów. Czy projekt mediów to trzeci `kind`, czy rozszerzenie projektu czatu? Rekomendacja: **trzeci `kind='media'`** — zachowuje rozdział z M22. *(przed Fazą 3)*

---

## 10. Następny krok

**Fazy 0–4 są zakończone, a implementacja Fazy 5 jest gotowa do testu live.**
Następny krok to rozmowa testowa Gemini przez skonfigurowane ADC/API key: tekst,
obraz, PDF, przerwanie odpowiedzi i powrót do zapisanej rozmowy. Po odbiorze można
przejść do Fazy 6 — Gemini jako silnika agenta — pozostającej częścią Caelo 2.1.
