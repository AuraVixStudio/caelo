# PLAN_WERYFIKACJI_LIVE.md — Caelo Desktop

> **Cel:** zamknąć największe ryzyko projektu (patrz SWOT 2026-06-07) — **przepaść między
> zbudowaną powierzchnią a jej weryfikacją na żywo**. Self-checki są zielone, ale testują
> kontrakty na **mockach**; sandbox dewelopera blokuje `api.x.ai` i exec OS. Ten dokument to
> **runbook do wykonania na Twojej maszynie** (ważny klucz/OAuth + sieć + realny OS).
>
> **Gotowe przykłady (prompty/komendy/configi + kryteria „✅"):** [`FAZA_C_PRZYKLADY.md`](FAZA_C_PRZYKLADY.md)
> — cookbook do otwartych sekcji (E-reszta/D/F/G/H/I/J/K).
>
> **Jak używać:** wykonuj sekcjami wg priorytetu (P0 → P3). Każde zadanie ma: *Cel ·
> Wymagania · Kroki · Oczekiwany wynik · Pułapki · Status*. Po teście wstaw `x` w `[ ]`,
> dopisz datę i krótką notatkę „DZIAŁA / NIE DZIAŁA + co". Na końcu zaktualizuj
> **tabelę wyników** i oznacz w docs/CLAUDE.md, co RZECZYWIŚCIE działa (zamiast „zrobione na mocku").
>
> **Legenda priorytetów:**
> **P0** = fundament, blokuje wszystko inne (auth + kształt drutu + tool-use na OAuth) ·
> **P1** = rdzeń produktu (czat, obraz, diffy agenta) ·
> **P2** = pełne tryby (wideo, głos, subagenci, MCP, headless) ·
> **P3** = funkcje-widma OFF-by-default (decyzja: włączyć po weryfikacji ALBO usunąć) + reszta.

---

## Tabela wyników (uzupełniaj na bieżąco)

| Sekcja | Zakres | Prio | Status | Data | Notatka |
|---|---|---|---|---|---|
| A | Auth + kształt drutu | P0 | ✅ | 2026-06-07 | **A1–A3 wszystkie ✅.** OAuth login + tryb API key + twardy przełącznik/usuwanie/maska klucza; **A3: web_search działa na OAuth → tool-use (MCP/agent) bez klucza API** |
| B | Czat (Responses API) | P1 | ✅ | 2026-06-07 | **B1–B10 wszystkie ✅** (UTF-8, web/x search + koszt, wizja, PDF Q&A, wiedza projektu, effort, media-gen img2video, eksport MD) |
| C | Twórczość (Image/Video) | P1/P2 | ✅ | 2026-06-07 | **C1–C7 wszystkie ✅** (text2img, edycja, warianty, text2video/img2video, edit/extend, galeria+kolejka+koszt) |
| D | Głos | P2 | 🟡 | 2026-06-19 | **D1 (TTS) ✅ + D2 (STT batch) ✅.** D1: 5 głosów + EN/PL, read-aloud + Speak, badge kosztu. D2: dyktowanie czat/Code + Transcribe — transkrypt PL poprawny, koszt z czasu. **2 bugi naprawione:** feedback Settings → toast (`17c2caa`); **CSP `script-src` bez `blob:` blokował AudioWorklet → Talk/Live/STT-stream padały „Audio capture is unavailable" — dodano `blob:` (`a02e67f`, +test).** ⚠️ koszt TTS = SZACUNEK (faktura). **D5 (Live) ✅.** **D3 ROZSTRZYGNIĘTE: streaming `/v1/stt` niekompatybilny** (xAI odrzuca `input_audio_buffer.append`, oczekuje binarnego/`audio.done`) — partiale odłożone. **D4 (Talk) przepięty na batch-STT+VAD** (`497cbb2`, czeka na retest). Zostają D6/D7. |
| E | Agent kodowania | P1 | ✅ | 2026-06-17 | **E1–E10 ✅ — CAŁA SEKCJA E.** Pełny bieg, diff approval, plan mode, 4 tryby+bypass, checkpointy/undo, CAELO.md, sesje, @-pliki, reguły glob deny>allow, **LSP diagnostyka (pyright)**. Naprawiono ~17 bugów/UX (rundy 1–11): m.in. izolacja CAELO.md, edit_file taby/CRLF, @-wyszukiwanie, loop guard (r.8), **LSP URI-match Windows g%3A vs G: (r.10), sesja przeżywa zmianę zakładki — backend mintuje świeże id per połączenie (r.10)**. |
| F | Subagenci / zespoły | P2 | ✅ | 2026-06-18 | **F1–F4 ✅ — CAŁA SEKCJA F.** F1: 3 subagenci równolegle, kontekst rodzica czysty, głębia 1. F2: review w MODALU (Accept&merge/Discard/Cancel zawsze w zasięgu), merge→workspace, **checkpoint cofalny** („Undid 2 checkpoints"), **konflikt wykryty** (implementer+test-writer na `src/calculator.py` → badge „1 conflict"). F3: **cascade stop** — Stop orkiestratora → tester CANCELLED, `python slow_task.py` **ubity (tree-kill)**, brak osieroconego procesu (`Get-CimInstance` = pusto, sprawdzone w sekundy po Stop). F4: **skill `implement` steruje** delegate+rolami (PLAN fazowy → implementer→reviewer→apply, walidacja `--count<0` w `parse_args()`). UX naprawione na żywo: review-modal (diff uwięziony w max-h-64), przycisk zwijania Team, `shrink-0` na kartach (panel ściskał wpisy zamiast scrollować). |
| G | Rozszerzalność (MCP/headless/ACP/LSP) | P2 | 🟡 | 2026-06-19 | **G1+G2+G3+G5+G6 ✅** (MCP stdio realny + w agencie + w czacie; interop `.mcp.json`/`AGENTS.md`/`~/.claude/skills` niedestrukcyjnie; headless CLI plain/json/streaming-json + fail-closed + allow + sesje). LSP ✅ w E10. **4 realne bugi backendu naprawione**: cwd serwera (`3a004ef`), `start_enabled` martwy kod (`0376351`), warm-start (`24d4a4a`), **MCP jako provider — agent gubił narzędzia po rebuildzie** (`dc8da65`). Nauki: grok-build-0.1 niestabilny w deklarowaniu narzędzi (czat→grok-4.3), MCP-w-czacie wymaga „Always allow" (nie „Accept"). Zostają G4 (remote MCP), G7 (ACP). |
| H | Funkcje-widma (decyzja) | P3 | ⬜ | | |
| I | Pakiety / marketplace | P3 | ⬜ | | |
| J | Cross-platform | P3 | ⬜ | | |
| K | Terminal | P3 | ⬜ | | |

Legenda statusu: ⬜ nie zaczęte · 🟡 częściowe · ✅ działa · ❌ nie działa · ⏭️ odłożone/usunięte.

---

## Część 0 — Przygotowanie środowiska (raz, przed testami)

> Wszystkie polecenia z **korzenia repo** w PowerShell, chyba że napisano inaczej.
> Sidecar uruchamiany przez Electron dziedziczy zmienne środowiskowe z powłoki, w której
> odpalasz `npm run dev` — dlatego flagi env (`$env:CAELO_*`) ustawiaj **w tej samej powłoce**.

- [ ] **0.1 — Poświadczenia.** Wybierz JEDNĄ ścieżkę (precedencja: OAuth → klucz z ustawień → `.env`):
  - **Klucz API (najprostsze do testów backendu):** w `.env` (korzeń repo) ustaw `XAI_API_KEY=xai-...`.
  - **OAuth (testuje pełny przepływ logowania):** zaloguj się w apce (sekcja A1).
- [ ] **0.2 — Backend venv gotowy:** `caelo_core\.venv\Scripts\python.exe -c "import fastapi, uvicorn; print('ok')"`.
- [ ] **0.3 — Frontend deps:** `cd desktop; npm install` (jeśli jeszcze nie). Powrót: `cd ..`.
- [x] **0.4 — pełny pytest:** ✅ 2026-06-17 — `13 passed in 17.16s` (pytest 9.1.0). ⚠️ `Scripts\pip.exe`
      `Fatal error in launcher` → instaluj przez `.venv\Scripts\python.exe -m pip install …`.
- [ ] **0.5 — (opcjonalnie) E2E + Terminal:** `cd desktop; npx playwright install chromium` ·
      `caelo_core\.venv\Scripts\pip install pywinpty` (Terminal — sekcja K).
- [ ] **0.6 — Baseline offline (sanity przed live):** uruchom self-checki — muszą być zielone PRZED testami live, by odróżnić regresję od problemu z API:
  ```powershell
  caelo_core\.venv\Scripts\python caelo_core\tools\handshake_check.py
  caelo_core\.venv\Scripts\python caelo_core\tools\agent_selfcheck.py
  caelo_core\.venv\Scripts\python caelo_core\tools\api_smoke.py
  ```
- [ ] **0.7 — Apka startuje:** `cd desktop; npm run dev` → okno Electrona, brak błędów w konsoli DevTools, handshake w logu. (Jeśli `Error: Electron uninstall` → patrz CLAUDE.md „Gotcha — TLS-interception".)

**Modele referencyjne (z `config.py`, do użycia w krokach):** czat `grok-4.3` · obraz
`grok-imagine-image` · wideo `grok-imagine-video-1.5-preview` · głos `grok-voice-latest` ·
embeddingi `embedding-beta-3-small`. Wizja wymaga rodziny **grok-4**.

---

## Część A — Auth + kształt drutu  🔴 P0 (blokuje wszystko)

> Bez działającego auth i potwierdzonego kształtu odpowiedzi xAI żaden inny test nie ma sensu.
> **Najważniejsze otwarte pytanie projektu (A3) testuj NAJPIERW** — przesądza architekturę agenta.

> **Postęp 2026-06-07 (z testów na żywo u usera):** logowanie OAuth **DZIAŁA** (zalogowany jako
> `grooverpty6@proton.me`), czat odpowiada na tokenie OAuth; tryb **API key DZIAŁA** (model odpowiedział).
> Test ujawnił, że pierwotny **łagodny fallback** po cichu używał OAuth, gdy wybrano „API key" bez klucza
> → wprowadzono **twardy przełącznik źródła** (Settings → „Model source": auto/oauth/api_key, `oauth`/
> `api_key` bez krzyżowego fallbacku), **usuwanie klucza** (`DELETE /settings/api-key`), **maskę kropek**
> dla zapisanego klucza i **status footera „Not signed in"**, gdy brak aktywnego źródła. **A3 ZALICZONE
> (2026-06-07): web_search działa na OAuth** → tool-use (a więc MCP/narzędzia agenta) NIE wymaga klucza
> API; „zaloguj się i koduj/szukaj" jest realne bez klucza. **Cała sekcja A ✅.**

- [x] **A1 — Logowanie OAuth (`auth.x.ai`, PKCE).**  ✅ POTWIERDZONE 2026-06-07 (zalogowany w apce).
  - *Cel:* potwierdzić, że nieudokumentowany przepływ OAuth grok-cli/Hermes nadal działa.
  - *Kroki:* w apce → Settings/Auth → „Sign in" → przejdź flow w przeglądarce → wróć do apki.
  - *Oczekiwane:* status „zalogowany", `caelo_auth.json` zawiera tokeny (gitignored).
  - *Pułapki:* endpointy `auth.x.ai` są nieudokumentowane — mogą paść server-side bez ostrzeżenia.
    Jeśli nie działa: użyj klucza API (0.1) i odnotuj „OAuth broken".

- [x] **A2 — Precedencja + przełącznik źródła.**  ✅ POTWIERDZONE 2026-06-07 (oba tryby autoryzują).
  - *Stan:* czat działa na OAuth **i** na kluczu API. Dodano **twardy przełącznik** (Settings → „Model
    source"): `auto` = OAuth → klucz → `.env`; `oauth`/`api_key` = **tylko** wybrane źródło (bez cichego
    fallbacku). „Currently using" pokazuje faktyczne aktywne źródło; `/settings` NIE zwraca klucza (tylko flagi).
  - *Do sprawdzenia (regresja):* `auto` przy zalogowanym OAuth **i** zapisanym kluczu → używa OAuth;
    usunięcie klucza (Remove) → `has_stored_key=false`; wybór „API key" bez klucza → czat odmawia (nie OAuth).

- [x] **A3 — ⭐ Function-calling na tokenie OAuth.**  ✅ POTWIERDZONE 2026-06-07 — **web_search działa na OAuth**.
  - *Wynik:* tool-use (web_search; a więc także MCP i narzędzia agenta) **działa na samym tokenie OAuth,
    BEZ klucza API**. Rozstrzyga otwarte pytanie z `PLAN_ROZBUDOWY.md` §0 — „zaloguj się i koduj/szukaj"
    jest realne bez klucza. Nie trzeba wymuszać ścieżki klucza dla agenta/narzędzi.
  - *Pozostaje (nice-to-have):* potwierdzić to samo dla **narzędzi agenta Code** (sekcja E1) i **MCP**
    (sekcja G) na OAuth — ta sama ścieżka function-calling, więc bardzo prawdopodobne.

---

## Część B — Czat (Responses API)  🟠 P1

> Rdzeń `/v1/responses` (streaming). Stare `search_parameters` zwraca **410 Gone** (sty 2026) —
> upewnij się, że idzie ścieżka Responses, nie legacy. Vector stores `/v1/vector_stores` → **404**.

> **Postęp 2026-06-07 (testy na żywo u usera): B1–B10 ✅ POTWIERDZONE — CAŁA CZĘŚĆ B.** UTF-8, live
> web_search (cytowania + Sources x.ai/imagine.art/the-decoder/klingaio, „4 searches · 20k tokens"), live
> x_search (źródła x.com, trendy PL), wizja (opis obrazu cyberpunk), Q&A nad PDF (instrukcja-logowania),
> wiedza projektu (CAELO.md, „Based on document"); B7 koszt rośnie z web-search, B8 wyższy effort =
> dokładniejsza odpowiedź, B9 media (obraz inline + img2video „animuj psa"), B10 eksport `.md`.
> **WAŻNE dla A3:** web_search + x_search to
> SERWEROWE narzędzia xAI — skoro działają, **tool-use działa na aktywnym źródle auth**. Jeśli podczas
> tych testów aktywny był OAuth (footer „Connected", nie „Not signed in") → **A3 w praktyce zaliczone**;
> by domknąć formalnie: ustaw „Model source" = `xAI account` i powtórz web_search (sekcja A3).

- [x] **B1 — Zwykły czat + UTF-8.**  ✅ 2026-06-07. Polskie znaki renderują się poprawnie.
  - *Oczekiwane:* płynny streaming, **poprawne polskie znaki** (nie „Å›/Ä…"). Potwierdza UTF-8 SSE.

- [x] **B2 — Live web_search.**  ✅ 2026-06-07. Cytowania [1..4] + panel Sources + „4 searches · 20k tokens".
  - *Oczekiwane:* wskaźnik „Searching…", odpowiedź z **klikalnymi cytowaniami [1..n]**, panel Sources,
    badge kosztu/tokenów. (To było potwierdzone 2026-06-05 — sprawdź czy nadal.)
  - *Pułapki:* realne API zwraca w `title` cytowania NUMER odnośnika → `citationLabel` pokazuje wtedy
    domenę zamiast numeru (kosmetyka).

- [x] **B3 — Live x_search.**  ✅ 2026-06-07. Trendy PL ze źródłami x.com.
  - *Oczekiwane:* cytowania z X, sensowna treść live.

- [x] **B4 — Wizja (obraz na wejściu).**  ✅ 2026-06-07. Poprawny opis załączonego obrazu (grok-4.3).
  - *Oczekiwane:* poprawny opis. Na modelu spoza grok-4 → czytelny błąd gatingu.

- [x] **B5 — Q&A nad dokumentem.**  ✅ 2026-06-07. Odpowiedź z treści PDF, badge „Based on document".
  - *Oczekiwane:* odpowiedź z treści dokumentu. (Potwierdzone 2026-06-05 — re-test.)

- [x] **B6 — Wiedza projektu (lokalna).**  ✅ 2026-06-07. CAELO.md dołączony, „Based on document".
  - *Oczekiwane:* dokument dołączony jako `input_file`, odpowiedź z jego treści. (xAI nie ma vector stores → to lokalne.)

- [x] **B7 — Tryby wyszukiwania auto/on/off + koszt.**  ✅ 2026-06-07. Koszt wyraźnie wyższy z web-search (tokeny + opłata za narzędzie).
  - *Oczekiwane:* „off" = brak narzędzi; „on" = wymusza search; badge sumuje koszt. *Potwierdzone:* `tool_choice="required"` dla „on" akceptowane przez API.

- [x] **B8 — Reasoning effort (M19-B9).**  ✅ 2026-06-07. Wyższy effort → dokładniejsza odpowiedź; brak błędu 400.
  - *Oczekiwane:* `reasoning.effort` trafia do API (dłuższe/krótsze rozumowanie), brak błędu 400 za nieznane pole.

- [x] **B9 — Generowanie mediów w czacie (M20).**  ✅ 2026-06-07. Obraz inline + img2video („animuj psa", DONE); czat używa modelu bazowego `grok-imagine-video`.
  - *Oczekiwane:* `generate_image` woła się, obraz renderuje **inline** (ramka `artifact`), trafia do Galerii.
    „Zrób wideo z…" → `generate_video` zakolejkowane, info „śledź w zakładce Video". (Edycja obrazu — już potwierdzona LIVE.)
  - *Pułapki:* narzędzia mediów są AMBIENTNE (nie liczą się do `has_tools`); wyłącznik `CAELO_CHAT_MEDIA=0`.

- [x] **B10 — Eksport do Markdown (M19-B10).**  ✅ 2026-06-07. Pliki eksportują się poprawnie do `.md`.
  - *Oczekiwane:* poprawny `.md` z przebiegiem rozmowy (treść + cytowania).

---

## Część C — Twórczość: Image / Video  🟠 P1 (Image) / P2 (Video)

> Jedna async kolejka `GenJob` (queued→running→done/failed/cancelled). Wideo poll **server-side**.

> **Postęp 2026-06-07 (testy na żywo u usera): C1–C7 ✅ POTWIERDZONE — CAŁA CZĘŚĆ C.** Generacja
> i edycja obrazu, warianty, wideo text2video/img2video, edit/extend, galeria + zarządzanie kolejką
> (cancel/retry/delete) i koszt — wszystko działa poprawnie.

- [x] **C1 — Obraz text2img.**  ✅ 2026-06-07. Wynik w galerii + koszt.
  - *Oczekiwane:* zadanie w kolejce → wynik w galerii, koszt na badge.

- [x] **C2 — Edycja obrazu (referencje ≤3).**  ✅ 2026-06-07.
  - *Oczekiwane:* poprawny wynik; walidacja odrzuca >3 referencje.

- [x] **C3 — Warianty.**  ✅ 2026-06-07.
  - *Oczekiwane:* nowe warianty (data-URI z B4-pipeline).

- [x] **C4 — Wideo text2video.**  ✅ 2026-06-07. Kolejka + poll server-side → galeria.
  - *Oczekiwane:* zadanie zakolejkowane, **poll server-side** (FastAPI nie blokuje), wynik w galerii.
  - *Pułapki:* render trwa minuty — to oczekiwane; sprawdź że UI nie zawiesza się i poll działa po przeładowaniu.

- [x] **C5 — Wideo img2video.**  ✅ 2026-06-07. Obraz jako pierwsza klatka → animacja (m.in. pies z czatu).
- [x] **C6 — Wideo edit / extend.**  ✅ 2026-06-07. Op `edit`/`extend` przez kolejkę.
  - *Oczekiwane:* op `edit`/`extend` przez kolejkę (`edit_video_job`/`extend_video_job`).
- [x] **C7 — Zarządzanie kolejką/galerią.**  ✅ 2026-06-07. Cancel/Retry/Delete + fullscreen + miniatury + koszt.
  - *Oczekiwane:* wszystkie działają; `total_cost` się sumuje.

---

## Część D — Głos  🟡 P2

> Audio: renderer → sidecar → xAI; **klucz NIE dociera do renderera** (most dokłada `Authorization`).

- [x] **D1 — TTS (5 głosów + język).**  ✅ 2026-06-19. 5 głosów (Eve/Ara/Rex/Sal/Leo) + EN/PL działają; read-aloud w czacie + tryb Speak; badge kosztu rośnie (33 znaki → ~$0.0005, zgodnie z $0.015/1k).
  - *Oczekiwane:* odtwarzanie, koszt na badge. *Pułapka:* `TTS_COST_PER_1K_CHARS=0.015` to **strojalny szacunek** (cena znakowa nie jest publiczna) — **DO ZWERYFIKOWANIA na fakturze**.
  - *Bug naprawiony (live):* zapis w Settings → Voice (i Output/Models) renderował potwierdzenie w bannerze na **górze** strony, poza widokiem → user nie widział feedbacku. Cały kanał feedbacku Settings przełączony na **toast** (fixed bottom-right, ROAD-4.1-d), banner usunięty. Commit `17c2caa` + test `desktop/test/components/Settings.test.tsx`.
  - *Uwaga (nie-bug, świadomy design):* tryb Speak trzyma pojedynczy `ttsAudio` → widać tylko ostatnią generację; pliki zapisują się na dysku, „Open file" otwiera każdy. Lista poprzednich syntez = ewentualny feature request, nie regresja.

- [x] **D2 — STT batch (dyktowanie).**  ✅ 2026-06-19. Dyktowanie w czacie/Code + tryb Transcribe; transkrypt PL poprawny („Napisz funkcję dodającą dwie liczby."), koszt z czasu (STT 3s → ~$0.0001).
  - *Oczekiwane:* poprawna transkrypcja wstrzyknięta do composera; koszt z czasu trwania.

- [x] **D3 — STT stream (partiale).**  ⛔ ROZSTRZYGNIĘTE 2026-06-19: **streaming `/v1/stt` NIE DZIAŁA — protokół potwierdzony niekompatybilny.** Log mostu (`CAELO_VOICE_DEBUG=1`) pokazał: xAI łączy się, odsyła `transcript.created`, a potem **odrzuca** nasze ramki: `error: unknown variant input_audio_buffer.append, expected audio.done`. Czyli `/v1/stt` oczekuje innego (binarnego) formatu, nieudokumentowanego — to NIE jest błąd mostu (Live na tym samym moście działa, bo `/v1/realtime` faktycznie używa `input_audio_buffer.append`).
  - *Decyzja (opcja 1, akcept. usera):* **partiale na żywo odłożone**; Talk (D4) przepięty na działający batch-STT + VAD. `parseStt`/`/voice/stt/stream` zostają w kodzie na wypadek dokumentacji endpointu.
  - *Po drodze naprawiony bug CSP* (blokował też D4/D5): `script-src` bez `blob:` → AudioWorklet nie wstawał (`a02e67f`). Diagnostyka ramek: `CAELO_VOICE_DEBUG=1` (`6e48df1`).

- [x] **D4 — Talk (pipeline converse) + batch-STT + VAD + barge-in.**  ✅ 2026-06-19 (fix `497cbb2`). Po werdykcie D3 Talk używa **batch `/voice/stt`** (jak dyktowanie D2) z lokalnym **VAD** (AnalyserNode RMS, auto-stop na ~1,5 s ciszy): mów → cisza → transkrypt → `/voice/converse` (Responses M10 + live search + historia M9) → odpowiedź tekst+głos. Barge-in zachowany (mowa w trakcie TTS przerywa). **Wymaga retestu na żywo u usera.**
  - *Oczekiwane:* stany listening/thinking/speaking; auto-stop na ciszy; **przerwanie mową = barge-in** (pomija TTS); turę zapisuje do M9; opcjonalnie live-search.

- [x] **D5 — Realtime (Live).**  ✅ 2026-06-19. Pełna dwukierunkowa rozmowa głos↔głos (PL+EN, sensowne odpowiedzi), niska latencja. `/voice/realtime` → `grok-voice-latest`. Dowodzi też, że most proxy sidecara (`_bridge_upstream`) jest sprawny — wspólny z `/voice/stt/stream`.
  - *Oczekiwane:* niskolatencyjna rozmowa głos↔głos.

- [ ] **D6 — Read-aloud + D7 koszt sesji.** Czytanie odpowiedzi głosem z ustawień; badge sumuje audio per sesja.

---

## Część E — Agent kodowania (Code)  🟠 P1

> **Table stakes** trybu Code. Testuj na **kopii** prawdziwego repo (agent pisze pliki).
> Najpierw potwierdź A3 (czy narzędzia działają na Twoim aucie).

> **Postęp 2026-06-08 (testy na żywo u usera): E1 ✅ + 3 realne bugi NAPRAWIONE** (których mocki nie
> złapały): izolacja CAELO.md/CLAUDE.md (agent nad cudzym projektem dostawał reguły repo Caelo, commit
> `8a811d9`); panel agenta „ściskał" wpisy w paski i nie przewijał się → przyciski APPROVE nieosiągalne
> (`65744c0` shrink-0 + `23b64c4` rAF auto-scroll). Po fixach: pełny bieg z edycjami (accept-edits) działa,
> wpisy w pełnej wysokości, lista płynnie się przewija, analiza renderuje markdown. **Zostają E2–E10.**

> **Postęp 2026-06-13 (4 spostrzeżenia z weryfikacji E — NAPRAWIONE w kodzie, do re-testu live):**
> (1) **Wklejanie zrzutu** — composer Code dostał `onPaste` (parytet z czatem: obraz ze schowka →
> załącznik). (2) **Licznik tokenów** — nowa ramka WS `usage` (skumulowane `input/output_tokens` sesji)
> + badge „N tok" w nagłówku panelu agenta (reset na New/Open session). (3) **„Max iterations reached"** —
> domyślny `max_iters` 25→**50** ORAZ po wyczerpaniu limitu agent robi JEDNĄ finalną turę **bez narzędzi**
> (`_finalize_on_limit` w `session.py`) → użytkownik dostaje podsumowanie/plan + notkę „send another
> message to continue" zamiast surowego błędu (nowa ramka `info`). (4) **Poprawianie pisowni** — proces
> main Electrona: `setSpellCheckerLanguages(['en-US','pl'])` + handler `context-menu` z sugestiami /
> „Add to dictionary" / Cut-Copy-Paste (jak w Claude Code). Self-checki zielone (agent_selfcheck OK,
> typecheck/lint/Vitest 244 OK). ⚠️ **Re-test live u usera**: realne tokeny w badge, finalne podsumowanie
> po limicie (wymaga realnego xAI), podkreślenia pisowni (słowniki Hunspell pobiera Electron — w sieci
> TLS-interception mogą nie wejść).

> **Postęp 2026-06-13 (runda 2 — UX panelu Code; do re-testu live):** #1 (max iterations) POTWIERDZONE
> przez usera (agent dokończył i przedstawił plan). Dalsze 4 spostrzeżenia → NAPRAWIONE w kodzie:
> (2) **Miernik okna kontekstowego** — backend liczy `context_tokens` (realne `usage.input` z ostatniego
> wywołania LUB szacunek ~4 znaki/token, fallback offline) + `max_context` (`config.context_window_for`,
> SZACUNEK per model) → ramka `usage` → pasek „X/Y · %" w nagłówku panelu (kolor ostrzega przy zapełnieniu;
> tooltip z sumą tokenów sesji). UWAGA: na ścieżce agenta `llm.py` celowo NIE wysyła `stream_options.
> include_usage` (ryzyko 4xx na krytycznej ścieżce), więc realne tokeny pojawią się tylko gdy serwer i tak
> je zwróci — inaczej miernik pokazuje szacunek. (3) **Wskaźnik pracy** — trwały pasek „Working… / Running
> <tool>… / Writing… / Waiting for approval…" z licznikiem sekund, widoczny przez całą turę (jasny sygnał,
> że agent żyje). (4) **Wiadomości użytkownika** — wyrównane w PRAWO, dymek z akcentem (odróżnienie od
> odpowiedzi/narzędzi agenta po lewej). (5) **Pisownia w czacie** — menu kontekstowe jest GLOBALNE (działa
> i w czacie, i w Code); „No suggestions" w teście wynika z braku słownika PL (Hunspell nie pobrał się w
> sieci TLS-interception) — naprawa = `NODE_EXTRA_CA_CERTS` lub pobranie słownika, NIE kod. Self-checki
> zielone (agent/headless/acp OK, typecheck/lint/Vitest 244 OK).

> **Postęp 2026-06-13 (runda 3 — miernik na żywo):** user „dalej nie widzę licznika" — dwie przyczyny:
> (a) ramka `usage` szła TYLKO na końcu tury → w trakcie długiej tury miernik się nie pojawiał;
> (b) **sidecar Python nie hot-reloaduje** zmian backendu (Vite HMR odświeża tylko renderer — stąd #3
> działało, a `usage` nie). Naprawa kodu: `session._emit_usage()` woła się **po KAŻDYM wywołaniu LLM**
> w turze (live miernik, jak Claude Code) + przy finalizacji limitu. WYMAGANE u usera: **pełny restart
> `npm run dev`** (Ctrl+C + ponownie), by sidecar wczytał backend rundy 2/3. Self-checki agent/headless/
> acp = OK.

> **Postęp 2026-06-13 (runda 4):** ✅ licznik tokenów/kontekstu POTWIERDZONY przez usera („114k/256k").
> Ostatnie: słownik pisowni ma podążać za **językiem systemu**, nie być na sztywno EN. Naprawa
> ([main/index.ts](../../desktop/src/main/index.ts)): zamiast `['en-US','pl']` biorę języki z
> `app.getPreferredSystemLanguages()` (dopasowanie kodów `pl-PL`→`pl`, cap 3, kolejność systemu;
> fallback EN tylko gdy brak). Na polskim Windowsie → polskie sugestie. **Wszystkie spostrzeżenia
> usera z E-weryfikacji zamknięte.** (Słowniki nadal pobiera Electron; sieć usera działa — EN się
> pobrał — więc PL też powinien.)

> **Postęp 2026-06-13 (runda 5):** ✅ wklejanie zrzutu w Code potwierdzone. Dwie nowe sprawy:
> (a) **Drzewo plików nie odświeżało się** — agent tworzył pliki/foldery (np. `build/`, `ReadyToInstall/`),
> a nie pojawiały się w panelu. Przyczyna: [FileTree.tsx](../../desktop/src/renderer/src/components/code/FileTree.tsx)
> `refreshKey` odświeżał TYLKO korzeń, a `TreeNode` cache'uje dzieci w stanie i nie pobierał ich ponownie.
> Naprawa: `refreshKey` przekazany do każdego `TreeNode` → rozwinięty katalog pobiera dzieci na nowo,
> zwinięty czyści cache; dodatkowo ramka `checkpoint` odświeża drzewo NA ŻYWO (write_file/edit_file w
> trakcie tury), a `run_command` (build/) dochodzi na `done`. (b) **Reguła run_command** w SYSTEM_PROMPT
> agenta + wzmocniony opis narzędzia: jeden program/wywołanie, BEZ `&&`/`|`/`;`/`&`/`>`/`<`/`2>&1` (agent
> marnował iteracje na łańcuchy odrzucane przez P0-1; teraz wie, że ma rozbijać kroki i nie przekierowywać
> wyjścia). Self-checki agent OK; typecheck/lint/Vitest 244 OK.

> **Postęp 2026-06-13 (runda 6):** agent **zapętlił się na `edit_file`** (wielokrotne „old_string
> not found" na pliku DAZ SDK — taby vs spacje). Naprawa [tools.py](../../caelo_core/agent/tools.py):
> wspólny matcher `_compute_edit` (egzekucja + preview spójne): exact → fallback CRLF (model wysłał
> `\r\n`, plik znormalizowany do `\n`) → fallback **tolerujący wcięcia/białe znaki** (`_flexible_line_span`:
> blok linii zgodny po `.strip()`, TYLKO 1 trafienie — bez zgadywania) → czytelny błąd „kopiuj verbatim
> albo użyj write_file". + wskazówka edit_file w SYSTEM_PROMPT (kopiuj dokładnie; po porażce re-read /
> write_file; nie pętl). Nowe testy: indent/CRLF/ambiguous (+4, agent_selfcheck OK). UWAGA: backend →
> wymaga restartu `npm run dev`.

> **Postęp 2026-06-13 (runda 7):** ✅ **Bypass (E4)** i ✅ **sesje (E7)** potwierdzone na żywo.
> `@`-wyszukiwanie nie znajdowało plików własnego projektu — 3 przyczyny naprawione:
> (a) **limit** [fs.py](../../caelo_core/routes/fs.py) `MAX_FS_FILES` 5000→**30000**: `os.walk`
> alfabetyczny wypełniał limit wielkim `DazSDK-main` ZANIM dotarł do `SCENE MANAGER` (sortowane po 'D'),
> więc pliki usera nie wchodziły do listy; (b) `/fs/files` dołącza teraz **katalogi** (z trailing `/`) →
> da się odwołać do folderu, a `fuzzyFiles` poprawnie dopasowuje nazwę katalogu mimo `/`; (c) lista `@`
> była pobierana RAZ przy otwarciu — teraz **odświeżana po każdej turze** (pliki tworzone przez agenta
> trafiają do podpowiedzi). Testy: composerSuggest (+1, dir), api_smoke `/fs/files` (+2: plik + katalog).
> Typecheck/Vitest 245 OK. UWAGA: backend → restart `npm run dev`. ✅ **E8 potwierdzone po restarcie**
> (`@Scene` → `SCENE MANAGER/` + pliki w całym projekcie).

> **Postęp 2026-06-17 (runda 8 — z weryfikacji E5/E6/E9):** ✅ **E5 (checkpointy/undo)** i ✅ **E6
> (CAELO.md)** potwierdzone na żywo (m.in. „Undo all — removed 3" + „partial undo" po `run_command`;
> docstring/f-string wymuszony przez CAELO.md). ✅ **E9 (reguły glob)** — odrzucenie deny działa. **BUG
> LIVE złapany i naprawiony:** po serii reject/accept model **zapętlił się na identycznym `edit_file`**
> (dodał ~25× tę samą linię, aż `old_string is not unique (10 matches)`) — prompt „Never loop on a failing
> edit" był ignorowany. **Fix (deterministyczny):** [session.py](../../caelo_core/agent/session.py)
> `LOOP_GUARD_LIMIT=3` — IDENTYCZNE wywołanie (name+args) powtórzone > próg w jednej turze kończy turę
> czysto (ramka `info` + `stopped`, zbalansowana historia, „send another message"), nie wykonując wywołania
> (chroni plik). Test: `agent_selfcheck` `test_loop_guard` (6 asercji), RESULT OK. ⚠️ backend → restart `npm run dev`.

> **Postęp 2026-06-17 (runda 9 — E10 + bug zakładek):** serwer **pyright RUNNING** ✅ przez GUI
> (Extensions → Language Servers), ale **diagnostyki nie pokazywały się**. Przyczyna: w
> [lsp/client.py](../../caelo_core/lsp/client.py) `DEFAULT_DIAGNOSTICS_WAIT_S=1.5` s było za krótkie
> (pyright publikuje wynik później, często NAJPIERW pusty `publishDiagnostics`, potem analizę) →
> `wait_diagnostics` zwracało pustkę → renderer nic nie pokazuje. **Fix:** bump do **5.0 s** (pętla i tak
> przerywa od razu po nadejściu wyniku, więc czysty plik nie płaci pełnego budżetu) + **łaska
> `DIAG_EMPTY_GRACE_S`** na DOSŁANIE wyniku po pustym pierwszym publishu. `lsp_check` OK — **wymaga
> re-testu LIVE** (restart `npm run dev`). **BUG UX (osobny, naprawiony):** zmiana zakładki Code→inna→Code
> gubiła transkrypt sesji (panel leniwy → unmount → lokalny `useState` przepadał). Fix: `hub.codeSessionId`
> (Hub przeżywa unmount) + auto-wznowienie ostatniej sesji na (re)montażu `AgentPanel`; `newSession` czyści
> zapamiętane id. typecheck/lint/Vitest 252 OK.

> **Postęp 2026-06-17 (runda 10 — głębsze przyczyny, oba bugi z rundy 9 wracały):** ✅ **E10 prawdziwy
> root-cause:** na Windows pyright publikuje `publishDiagnostics` pod URI `file:///g%3A/...` (mała litera
> dysku, `:`→`%3A`), a nasz `path_to_uri` daje `file:///G:/...` — surowe stringi się NIE zgadzały, więc
> `_diagnostics` był kluczowany inaczej przy zapisie i odczycie → **zawsze pusto** (timeout z rundy 9 był
> wtórny). Fix [lsp/client.py](../../caelo_core/lsp/client.py): `canon_key()` (uri→ścieżka→`normcase`/
> `normpath`) kluczuje zapis i odczyt diagnostyk tym samym kluczem. Test `lsp_check` `test_canon_key_uri_match`
> (3 asercje, Win/POSIX). ✅ **Bug zakładek prawdziwy root-cause:** [routes/agent.py:107](../../caelo_core/routes/agent.py)
> — KAŻDE połączenie WS mintuje ŚWIEŻĄ sesję i ogłasza ją przy connect, więc po reconnect frontend dostawał
> nowe puste id; poprzedni fix blokował się na tym. Przeprojektowany [AgentPanel](../../desktop/src/renderer/src/components/code/AgentPanel.tsx):
> mirror do Hub tylko gdy jest transkrypt (entries>0, by świeże id nie nadpisało zapamiętanego), restore
> wznawia zapamiętaną sesję i ZASTĘPUJE świeże id (`setSession(sid)` → backend wczytuje historię). typecheck/lint OK.
> ⚠️ **oba wymagają pełnego restartu `npm run dev`** (backend client.py + renderer).

- [x] **E1 — Pełny bieg agenta.**  ✅ 2026-06-08. Agent czytał (read_file/grep/list_dir) i edytował pliki (edit_file App.tsx/icon-generator.ts) w accept-edits; pętla domknięta, analiza wyrenderowana.
  - *Oczekiwane:* agent czyta (read_file/grep/list_dir), proponuje edycje, woła run_command — pętla domyka się.

- [x] **E2 — Diff approval.**  ✅ 2026-06-13. Karta zatwierdzenia z czytelnym unified diff + Accept/Reject/Always allow (potwierdzone na żywo).
  - *Oczekiwane:* accept zapisuje, reject pomija; diff czytelny.

- [x] **E3 — Tryb planowania.**  ✅ 2026-06-13. Plan mode: READONLY działa, write_file „Blocked in plan mode", plan → faza review (Approve & run) — potwierdzone na żywo. (Sub-punkt „plan nie tworzy checkpointu" pokrywa selfcheck B2.)
  - *Oczekiwane:* READONLY działa, MUTATING „Blocked in plan mode", plan NIE tworzy checkpointu.

- [x] **E4 — 4 tryby.**  ✅ 2026-06-13. Ask (pyta), accept-edits/Edits (auto write/edit, baner), plan (READONLY) i **bypass** (baner „every change runs without asking", wszystko bez pytania) — potwierdzone na żywo.
  - *Oczekiwane:* accept-edits auto-akceptuje write/edit; bypass wszystko.

- [x] **E5 — Checkpointy + undo.**  ✅ 2026-06-17. „Undo all — removed 3" + baner „partial undo" po `run_command` (potwierdzone na żywo).
  - *Oczekiwane:* pliki wracają (odwrotna kolejność), utworzone usunięte; `run_command` → baner „partial undo".

- [x] **E6 — CAELO.md wpływa na zachowanie.**  ✅ 2026-06-17. Reguły z CAELO.md zastosowane (docstring + f-string w wygenerowanej funkcji).
  - *Oczekiwane:* agent stosuje regułę. (Też: edytor reguł w nagłówku Code.)

- [x] **E7 — Sesje kodu (M21).**  ✅ 2026-06-13. Sesje zapisują się automatycznie i są na liście „Sessions" (This project / All projects); potwierdzone na żywo.
  - *Oczekiwane:* historia wczytana, kontekst zachowany; ramka WS `session`.

- [x] **E8 — Komendy + @-pliki w composerze (M20).**  ✅ 2026-06-13. `@nazwa` fuzzy po plikach I katalogach całego projektu — potwierdzone na żywo (`@Scene` → `SCENE MANAGER/` + pliki). Komendy `/` używają tej samej ścieżki autocomplete (`detectSuggest`).
  - *Oczekiwane:* podpowiedzi, wstawienie referencji pliku do promptu.

- [x] **E9 — Reguły glob (M19-B4).**  ✅ 2026-06-17. Odrzucenie deny działa; przy okazji złapany i naprawiony bug pętli agenta (loop guard, patrz runda 8 wyżej).
  - *Oczekiwane:* **deny > allow**; deny = twarda odmowa nawet w bypass; allow auto-akceptuje. **P0-1 zachowane:** `Bash(...)` allow NIE omija metaznaków (`git && rm` dalej blokowane).

- [x] **E10 — LSP diagnostyka (M19-B3).**  ✅ 2026-06-17. pyright dodany przez Extensions → Language Servers (RUNNING); po `write_file` pliku `.py` z błędem typu panel agenta pokazał diagnostykę (*Type „Literal['hello']" is not assignable to „int"*). Wymagało naprawy match URI na Windows (`canon_key`, runda 10).
  - *Oczekiwane:* po edycji pliku ramka WS `diagnostics` (w panelu agenta); narzędzie `lsp` widoczne tylko gdy serwer skonfigurowany.
  - *Pułapki:* LSP używa **Content-Length framing** (binarny stdio) — inaczej niż MCP; ⚠️ URI pyright (`file:///g%3A/…`) ≠ nasz (`file:///G:/…`) — matchujemy po `canon_key`.

---

## Część F — Subagenci / zespoły (M17)  🟡 P2

> **Postęp 2026-06-18 (F1 ✅ na żywo):** workspace `G:\Testy\caelo-test-project` (świeży, bez CAELO.md),
> tryb accept-edits, model `grok-build-0.1`. Prompt „delegate researcher (config.py paths) + implementer
> (version() w util.py) + reviewer … in parallel" → orkiestrator zawołał `delegate`, **TeamView pokazał 3
> subagentów RUNNING równolegle**, potem DONE; kontekst rodzica czysty (jeden `delegate` zwrócił findings/
> summary/verdict, nie transkrypty); głębia 1 (żaden subagent nie delegował); `version()` dopisany do
> `util.py`, implementer dostał „Review merge — 1 file" (wejście do F2). **Drobny UX dodany po feedbacku
> usera:** przycisk **zwijania panelu Team** (chevron w nagłówku; zwinięty pokazuje „· N agents · koszt") —
> [`TeamView.tsx`](../../desktop/src/renderer/src/components/code/TeamView.tsx). Czysto renderer (bez
> restartu sidecara); typecheck/lint/Vitest 252 OK.
>
> **Postęp 2026-06-18 (F2 ✅ na żywo):** merge review przeszedł — Accept&merge scaliło `util.py` do workspace,
> **checkpoint cofalny** zadziałał („Undid 2 checkpoints — restored 2", `version()` zniknął), a przy dwóch
> mutujących subagentach na `src/calculator.py` **konflikt został wykryty** (badge „1 conflict" + ostrzeżenie
> w modalu). **2 realne bugi UX złapane na żywo i naprawione** (commit po F2): diff był uwięziony inline w
> panelu Team `max-h-64` (przyciski Accept/Discard nieosiągalne) → przeniesiony do **modala** (scrollowalny
> diff + przyklejona stopka, Esc/klik tła zamyka); panel Team przy wielu wpisach **ściskał karty** bez paska
> przewijania → `shrink-0` na kartach + `overflow-y-auto` + `max-h-80`. Test regresyjny
> [`TeamView.test.tsx`](../../desktop/test/components/TeamView.test.tsx). Zostają **F3–F4**.

- [x] **F1 — Delegacja end-to-end.**  ✅ 2026-06-18. 3 subagenci równolegle w TeamView, kontekst rodzica czysty (1 `delegate` = streszczenia), głębia 1, `version()` w `util.py`.
  - *Oczekiwane:* TeamView (drzewo) pokazuje subagentów równolegle; kontekst rodzica czysty (1 `tool` = streszczenia). Brak `delegate` u subagentów (głębia 1).

- [x] **F2 — Merge review (worktree).**  ✅ 2026-06-18. Review w MODALU → jeden diff `util.py`; Accept&merge → „Merged subagent changes into the workspace" + **checkpoint cofalny** („Undid 2 checkpoints — restored 2"); KONFLIKT wykryty (implementer+test-writer oba na `src/calculator.py` → badge „1 conflict" + ostrzeżenie „Merging will overwrite the other subagent's version").
  - *Bugi UX naprawione na żywo:* (a) diff był renderowany inline w panelu Team `max-h-64` → przyciski poza zasięgiem → przeniesione do **modala** (scrollowalny diff + przyklejona stopka); (b) panel Team przy wielu wpisach **ściskał** karty bez scrolla → `shrink-0` na kartach + `overflow-y-auto`; (c) przycisk zwijania panelu Team.
  - *Pułapka (kosmetyka, nie blokuje):* diff worktree pokazuje cały plik jako zmieniony (CRLF vs LF) — scalenie poprawne, diff hałaśliwy; ew. follow-up = normalizacja EOL przy liczeniu diffu.
- [x] **F3 — Cascade stop.**  ✅ 2026-06-18. Stop orkiestratora w trakcie biegu `tester` (`python slow_task.py`, na żywo `working… 23/60`) → tester `CANCELLED`, output urwany przed 60, a proces dziecka **ubity (tree-kill)** — `Get-CimInstance Win32_Process` po `slow_task` zwróciło pusto (brak osieroconego `python.exe`).
- [x] **F4 — Skille-orkiestratory (M19-B6).**  ✅ 2026-06-18. Skill `implement` włączony (Extensions → Skills) wstrzyknął fazowy PLAN i poprowadził pętlę wielo-agentową: delegate implementer (worktree) → reviewer → apply; efekt: walidacja `--count<0` (`parser.error`) w `parse_args()`. Kontekst rodzica czysty, głębia 1.
  - *Oczekiwane:* skill steruje `delegate`+rolami; sensowny przebieg wielo-agentowy.
  - *Obserwacja (nie bug):* orkiestrator próbował weryfikować przez `python -c "…; …"` → odbity przez P0-1 (metaznaki), obszedł przez `write_file` tymczasowego skryptu → run → cleanup. P0-1 działa zgodnie z projektem.

---

## Część G — Rozszerzalność: MCP / headless / ACP / interop  🟡 P2

> **Postęp 2026-06-19 (G1–G3 ✅ na żywo): 4 realne bugi backendu złapane i naprawione** (mocki były
> zielone — ścieżki nigdy nie odpalone live, klasyczny dług weryfikacji):
> (1) **cwd serwera** [`3a004ef`] — serwer stdio startował w CWD sidecara → ścieżki WZGLĘDNE „access denied";
> teraz startuje w korzeniu workspace (jawny `cwd` ma pierwszeństwo). (2) **`start_enabled` martwy kod**
> [`0376351`] — nikt go nie wołał → włączone serwery nie wstawały po restarcie/zmianie workspace; teraz
> `Backend.mcp` auto-startuje je w tle po (prze)budowie. (3) **warm-start** [`24d4a4a`] — serwery wstają już
> przy starcie sidecara (mniej „pierwsze żądanie nie ma narzędzia"). (4) ⭐ **MCP jako provider** [`dc8da65`]
> — `AgentSession` łapała instancję `McpManagera` RAZ; po przebudowie (`backend.mcp` jest workspace-aware)
> trzymała STARĄ/ubitą → **agent tracił WSZYSTKIE narzędzia MCP** mimo serwera READY. Fix: `mcp_provider`
> resolwujący `backend.mcp` na żywo (jak `lsp_provider`); subagenci dalej dostają instancję (ScopedMcp).
> **Nauki (nie-bug):** grok-build-0.1 bywa niestabilny w deklarowaniu narzędzi (twierdzi „brak", potem używa
> po ponowieniu) → do czatu używaj **grok-4.3**; MCP-mutujące w czacie wymaga **„Always allow"** (trwałe),
> nie „Accept" (jednorazowe) — komunikat odmowy wspomina „MCP configuration", choć nie ma tam przycisku
> (drobny brak UX, ew. follow-up: per-tool „allow in chat" w ustawieniach MCP). Testy regresyjne: `mcp_check`
> 46→**51** (cwd default/override + start_enabled), `agent_selfcheck` `test_mcp_provider_live` (+5).

- [x] **G1 — Realny serwer MCP (stdio).**  ✅ 2026-06-19. Filesystem przez katalog (Extensions → MCP), STDIO · READY · 14 narzędzi `mcp__filesystem__*`; subproces hardened (`npx`→`cmd /c`).
  - *Oczekiwane:* narzędzia `mcp__<srv>__<tool>` wylistowane; subproces hardened (scrubbed_env, tree-kill; Windows `.cmd`→`cmd /c`).

- [x] **G2 — MCP w agencie.**  ✅ 2026-06-19. Agent dostał kartę `mcp__filesystem__write_file` (kind `mcp_tool_call`, JSON args), po zatwierdzeniu plik utworzony; READONLY MCP bez pytania. (Wymagało fixu provider — patrz wyżej.)
- [x] **G3 — MCP w czacie.**  ✅ 2026-06-19. READONLY MCP w czacie działa; mutujące niepre-approved → odmowa z komunikatem; po „Always allow" w Code (`mcp:mcp__filesystem__write_file` na allowliście) czat (grok-4.3) **utworzył `chat_mcp.txt`** — ścieżka „dozwolone" potwierdzona.
- [ ] **G4 — Remote MCP (native).** Skonfiguruj `tools=[{type:mcp,server_url,…}]` → wykonanie po stronie xAI (bez lokalnej bramki).
- [x] **G5 — Interop (M19-B5).**  ✅ 2026-06-19. Wszystkie 3 ścieżki + niedestrukcyjność potwierdzone na żywo:
  - **MCP** — `<ws>/.mcp.json` (serwer `interop-demo`) zaimportowany **STOPPED · Enabled odznaczone** (`enabled=False`, autostart pominięty) ze znacznikiem źródła. ✅
  - **AGENTS.md** — sklejony do promptu agenta: agent przeczytał `AGENTS.md` i zakończył odpowiedź dokładną linią z reguły (`INTEROP-OK: AGENTS.md was loaded`). ✅
  - **Skille** — `belt`/`daz-studio-6-plugin` z `~/.claude/skills` odkryte w Extensions → Skills z badge **`~/.CLAUDE`** (read-only, bez Delete, niewłączone). ✅
  - **Niedestrukcyjność** ✅ — `~/.claude/skills` nietknięty (brak nadpisań/`.corrupt`).
- [x] **G6 — Headless CLI (M19-B1).**  ✅ 2026-06-19. Zweryfikowane na żywo (PowerShell, `cd` do korzenia repo + `.\caelo_core\.venv\Scripts\python.exe -m caelo_core run …`):
  - `plain` → sformatowany tekst (drzewo + streszczenie util.py); `json` → jeden obiekt `{text,stopReason,sessionId}`; `streaming-json` → NDJSON (`tool_call`/`text`/`end`).
  - **fail-closed** ✅ — „Create headless_test.txt" bez uprawnień → mutacja odrzucona (brak „Created", w przeciwieństwie do biegu z allow).
  - **allow** ✅ — `--permission-mode accept-edits --allow "Write(**)"` → „Created headless_ok.txt".
  - sesje ✅ — pliki `<id>.json` w `sessions\` (DATA_DIR = korzeń repo w dev).
  - ⚠️ **Pułapka uruchomienia:** musisz być w korzeniu repo (`python -m caelo_core` importuje pakiet z CWD); odpalenie z `C:\Users\…` → „module caelo_core could not be loaded".

- [ ] **G7 — ACP (M19-B2).** W Zed/Neovim/Emacs skonfiguruj agenta ACP: `python -m caelo_core acp`.
  - *Oczekiwane:* JSON-RPC stdio działa, `session/request_permission` poprawnie korelowane, ramki → `session/update`.

---

## Część H — Funkcje-widma OFF-by-default  ⚪ P3 (DECYZJA: włączyć po teście ALBO usunąć)

> To kod zbudowany, **wyłączony i niezweryfikowany**. Każda pozycja: zweryfikuj → jeśli działa,
> rozważ ON-by-default; jeśli nie/niepotrzebna → **usuń, by nie utrzymywać martwego kodu** (SWOT W3).

- [ ] **H1 — ⭐ Embeddingi spike (gate dla całego B8).**
  ```powershell
  caelo_core\.venv\Scripts\python caelo_core\tools\embeddings_check.py --live
  ```
  - *Oczekiwane:* `POST /v1/embeddings` zwraca wektory (~1024 wymiarów).
  - *Decyzja:* **jeśli 404/400 → xAI nie ma embeddingów → odłóż/usuń B8 (NIE wprowadzaj torch).**

- [ ] **H2 — Pamięć hybrydowa (zależy od H1).** `$env:CAELO_MEMORY="1"; npm run dev` → agent w 2. sesji odwołuje się do faktu z 1.
  - *Oczekiwane:* recall wstrzyknięty na 1. turze (kNN∪FTS5). Tylko jeśli H1 = OK.

- [ ] **H3 — Sandbox OS (Linux/macOS).** Na Linux/mac:
  ```bash
  python -m caelo_core run -p "spróbuj zapisać poza workspace" --cwd <ws> --sandbox strict
  ```
  - *Oczekiwane:* realny **bwrap** (Linux) / **sandbox-exec seatbelt** (macOS) blokuje zapis poza CWD i sieć (profil strict). Windows = no-op (oczekiwane).

- [ ] **H4 — web_fetch (M19-B13).** `$env:CAELO_WEB_FETCH="1"; npm run dev` → poproś agenta o pobranie strony.
  - *Oczekiwane:* https-only, SSRF-guard blokuje loopback/IP prywatne; narzędzie gated (Always-allow per host). Bez flagi ukryte.

- [ ] **H5 — git worktree (M19-B12).** W repo git: `python -m caelo_core run -p "…" --cwd <repo> --worktree` (lub `$env:CAELO_GIT_WORKTREE="1"`).
  - *Oczekiwane:* mutujący subagent dostaje realny `git worktree` (start z HEAD), diff vs HEAD, sprzątanie `git worktree remove`.

- [ ] **H6 — auto-compact (M19-B10).** `$env:CAELO_AUTOCOMPACT="1"` → długa sesja agenta.
  - *Oczekiwane:* historia przycinana na granicy `user` (balans tool_call↔tool zachowany), deterministyczny digest, bez utraty kontraktu xAI.

---

## Część I — Pakiety / marketplace (M16)  ⚪ P3

- [ ] **I1 — Fetch registry.** Extensions → Marketplace → Browse (sieć).
  - *Oczekiwane:* lista z `PACKAGES_REGISTRY_URL` (https-only + cap).
- [ ] **I2 — Instalacja `.caelopkg`.** Import → ConsentCard (uprawnienia/ryzyko) → Install.
  - *Oczekiwane:* odmowa bez zgody I przy złej integralności (tamper/sha256); skille install **disabled**, MCP `enabled=False`.
- [ ] **I3 — Export/Share.** Share na panelu Skills/Commands/MCP/Templates → plik `.caelopkg`.
  - *Oczekiwane:* sekrety (`authorization`/`env`) **zdjęte** przy eksporcie.

---

## Część J — Cross-platform (M15)  ⚪ P3 (gdy masz dostęp do mac/Linux)

- [ ] **J1 — Build mac/Linux.** `cd desktop; npm run dist:full` na danym OS (NSIS/dmg/AppImage/deb).
  - *Oczekiwane:* instalator się buduje (3 kroki sieciowe wg rozpisu M15: devDeps, electron-updater, sekrety GitHub).
- [ ] **J2 — PTY terminal cross-platform.** Terminal działa (stdlib `pty` na Unix, pywinpty na Win).
- [ ] **J3 — tree-kill POSIX.** Stop długiego `run_command` zabija drzewo procesów (SIGTERM→SIGKILL). *(Pokrywa się z H3.)*

---

## Część K — Terminal  ⚪ P3

- [ ] **K1 — Terminal (pywinpty).** `caelo_core\.venv\Scripts\pip install pywinpty` → Terminal w apce.
  - *Oczekiwane:* interaktywny shell; **env scrubbed** (brak `XAI_API_KEY`/`CAELO_CORE_TOKEN` — sprawdź `echo $env:XAI_API_KEY` w terminalu apki = puste).

---

## Po weryfikacji — co zrobić z wynikami

1. **Zaktualizuj tabelę wyników** (góra dokumentu) i wstaw daty/notatki przy zadaniach.
2. **Skoryguj docs** — w `CLAUDE.md` i planach zamień „zrobione (mock)" na realny status
   (✅ działa / ❌ / ⏭️ odłożone) — to domyka dług „dokumentacja przecenia kompletność" (SWOT W2).
3. **Decyzje per funkcja-widmo (H)** — włącz domyślnie albo usuń (SWOT W3).
4. **Rozważ publikację** (push + remote) gdy P0+P1 są ✅ (SWOT — brak remote = projekt „OSS" bez repo).

> **Pułapki ogólne (z historii projektu):** stare `search_parameters` → 410; vector stores → 404
> (wiedza = lokalny `input_file`); cytowania mogą mieć NUMER w `title`; STT-stream sample-rate
> niepotwierdzony; tool-use na OAuth = otwarte (A3); koszt TTS = szacunek. Self-checki ≠ live.
