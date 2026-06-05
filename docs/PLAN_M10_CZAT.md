# PLAN_M10_CZAT.md — Czat na poziomie (rozpis zadań)

> Rozpis milestone'u **M10** z `PLAN_ROZBUDOWY.md`. Cel M10: zakładka Chat dorasta do
> daily-drivera — **live search z X/web + cytowania**, **wizja na wejściu** i **Q&A nad
> dokumentami**. To najtańszy duży skok (narzędzia są wbudowane w API) i najlepsze demo.
>
> Tagi: **[P0]** krytyczne, **[P1]** ważne. Wysiłek: S≈dni, M≈1–2 tyg., L≈3–4 tyg.

---

## 0. Decyzja architektoniczna, na której wisi całe M10

**Live search = Responses API + `tools`, NIE `search_parameters`.**

- Stare Live Search (`search_parameters` w `chat/completions`) **wycofane 12.01.2026** →
  żądania zwracają **410 Gone**. Sam `chat/completions` jest legacy; nowe rzeczy idą przez
  **Responses API** (`POST /v1/responses`).
- Twoja ścieżka `api_manager.chat_completion_stream` **nie udźwignie** searcha. M10 wprowadza
  **nowego klienta Responses API** w `grok_core`.
- Nowy model działania: dołączasz narzędzia `web_search()` / `x_search()` → serwer xAI sam
  prowadzi pętlę „przeanalizuj → szukaj → doczytaj → odpowiedz", strumieniuje zdarzenia
  wywołań narzędzi (`verbose_streaming`) i zwraca **cytowania** po zakończeniu streamu.
- Wizja oraz `file_search` (Q&A nad kolekcjami) wymagają **rodziny grok-4** + Responses API.

### Decyzje przekrojowe (przeczytaj przed kodowaniem)
- **Nowy klient w `grok_core/responses_client.py`** — NIE restrukturyzuj root `api_manager.py`
  (zasada repo). Zachowaj dekodowanie UTF-8 jak w `chat_completion_stream`
  (`iter_lines(decode_unicode=False)` + `.decode("utf-8")`). Precedencja auth bez zmian
  (OAuth → klucz → `XAI_API_KEY`); cienka warstwa endpoint/auth jako jedyny hedge.
- **Strumień przez istniejący `WsStream`** (`routes/_ws.py`) — deltas + nowy typ zdarzenia
  `tool_call` (jaki tool, jaki query) + `citations` na końcu. Jeden skeleton, bez dryfu.
- **Koszt:** narzędzia serwerowe są płatne per wywołanie (+ tokeny) → licznik użycia od razu
  (model BYO-key = pieniądze usera). Tryb `auto/on/off` + opcjonalny limit.
- **Stateless zostaje** — wysyłasz historię w żądaniu (jak teraz). Stanowość Responses API
  (przechowywanie 30 dni + kontynuacja po `response_id`) poza zakresem M10.
- **UI po angielsku** (konwencja repo): „Search the web", „Sources", „Based on document".
- **Spina się z M9:** wejście obrazu/dokumentu korzysta z magistrali „send-to" (M9-B4) i
  pipeline'u załączników (M9-F4) — nie buduj drugiego mechanizmu.

---

## 1. Backend (`grok_core`)

### M10-B1 [P0] Klient Responses API ze strumieniem  — M/L
- **Cel:** jeden, nowoczesny kanał czatu, gotowy na narzędzia serwerowe.
- **Zakres:** `grok_core/responses_client.py` — `POST /v1/responses`, streaming deltas;
  parser zdarzeń (delta tekstu, `tool_call`, `usage`, `citations`); dekodowanie UTF-8 jak
  w legacy; precedencja auth z `state.get_api_key`. Trasa `/chat/stream` przełączona na ten
  klient (lub nowa `/chat/responses` na czas migracji — patrz pytania).
- **DoD:** zwykły czat (bez narzędzi) strumieniuje poprawnie przez Responses API; polski tekst
  bez „krzaków"; `{"type":"stop"}` przerywa.
- **Selfcheck:** rozszerz `api_smoke.py` — zamockowany `/v1/responses` stream, asercje:
  deltas dekodowane UTF-8, balans historii, enforcement tokenu (fail-closed).

### M10-B2 [P0] Live search jako narzędzia (web_search + x_search)  — M
- **Cel:** czat odpowiada z danymi w czasie rzeczywistym, z cytowaniami.
- **Zakres:** dołączanie `web_search()` / `x_search()` do żądania; konfiguracja `mode`
  (auto/on/off), `max_search_results`, `sources` (web/x/news), zakres dat. Emisja zdarzeń
  `tool_call` przez `WsStream`; zbieranie `citations` po streamie. Reuse `validation.py`
  na limity wejścia.
- **DoD:** pytanie wymagające świeżej wiedzy uruchamia search po stronie serwera i zwraca
  listę cytowań; `mode=off` całkowicie wyłącza narzędzia.
- **Selfcheck:** `api_smoke` — mock zwraca `tool_call` + `citations`; asercje: zdarzenia
  wyemitowane, cytowania sparsowane, `off` nie dokłada narzędzi.

### M10-B3 [P0] Wizja na wejściu  — S/M
- **Cel:** obraz w czacie → Grok go czyta.
- **Zakres:** akceptacja bloków `image` (base64) w żądaniu Responses dla rodziny grok-4;
  reuse walidatorów data-URI/limitu rozmiaru (`validation.py`, P1-14). Wejście z magistrali
  M9-B4 (artefakt-obraz → blok vision) albo z bezpośredniego załącznika.
- **DoD:** wysłany obraz → trafny opis; model spoza grok-4 → czytelny komunikat zamiast błędu.
- **Selfcheck:** `api_smoke`/`history_check` — kształt bloku image, cap rozmiaru, łagodne
  odrzucenie nie-grok-4.

### M10-B4 [P1] Q&A nad dokumentem — ścieżka inline  — M
- **Cel:** dołącz PDF/arkusz do jednej rozmowy i pytaj o treść.
- **Zakres:** załącznik dokumentu jako blok `document` w żądaniu; https-only + cap rozmiaru
  (P1-14) + `validation.py`. Bez trwałego magazynu (to B5).
- **DoD:** załączony PDF → odpowiedź ugruntowana w treści dokumentu.
- **Selfcheck:** kształt bloku document + cap rozmiaru.

### M10-B5 [P1] Kolekcje (file_search) — trwała wiedza projektu  — L *(stretch)*
- **Cel:** dokumenty projektu (M9) przeszukiwane w wielu rozmowach.
- **Zakres:** vector store (collection) per projekt; upload dokumentów; narzędzie `file_search`
  (grok-4 + Responses API). Wiąże się z `project_id` z M9-B5.
- **DoD:** dokument dodany do kolekcji projektu jest znajdowany w nowych czatach tego projektu.
- **Selfcheck:** mock create/list kolekcji; `file_search` poprawnie dołączone.
- **Uwaga:** opcjonalne w M10 — rozważ przesunięcie, jeśli M10 robi się ciężkie.

### M10-B6 [P1] Licznik kosztów narzędzi serwerowych  — S
- **Cel:** transparentność wydatków przy BYO-key.
- **Zakres:** zliczanie wywołań narzędzi + tokenów per odpowiedź (z `usage`/zdarzeń);
  zapis do meta historii (M9); ekspozycja przez `/usage` lub w odpowiedzi streamu.
- **DoD:** każde wywołanie searcha/narzędzia inkrementuje widoczny licznik.
- **Selfcheck:** `api_smoke` — licznik rośnie na zdarzeniach `tool_call`.

---

## 2. Frontend (`desktop/src/renderer`)

### M10-F1 [P0] Strumień ze zdarzeniami narzędzi  — M
- **Cel:** widać, że agent szuka, zanim pojawi się odpowiedź.
- **Zakres:** UI czatu pokazuje aktywność z `verbose_streaming` przez `WsStream`
  („Searching X…", „Searching the web…") → potem strumień tekstu. Buduj na `components/ui/`.
- **DoD:** podczas odpowiedzi z live searchem UI pokazuje wskaźnik szukania, potem tekst.
- **Test:** Vitest — mapowanie zdarzenie → stan wskaźnika.

### M10-F2 [P0] Cytowania / źródła w UI  — M
- **Cel:** odpowiedź z searcha ma klikalne źródła.
- **Zakres:** panel/odnośniki źródeł po zakończeniu streamu; klikalne (https), dedup.
- **DoD:** odpowiedź z live searchem pokazuje klikalne źródła.
- **Test:** Vitest — parsowanie/dedup listy cytowań.

### M10-F3 [P0] Przełącznik wyszukiwania  — S
- **Cel:** kontrola nad tym, kiedy (i gdzie) Grok szuka.
- **Zakres:** toggle `mode` (Auto/On/Off) + opcjonalny wybór źródeł (web/X/news); domyślna
  wartość per-rozmowa w ustawieniach.
- **DoD:** Off wyłącza narzędzia, On wymusza, Auto zostawia decyzję modelowi.
- **Test:** Vitest — stan trybu.

### M10-F4 [P0] Wejście obrazu w czacie  — S
- **Cel:** wrzuć obraz do composera → wejście vision.
- **Zakres:** załącznik obrazu w composerze (reuse pipeline M9-F4) → blok vision; chip podglądu.
- **DoD:** drop obrazu → pytanie → odpowiedź o obrazie.
- **Test:** Vitest — załącznik → payload vision.

### M10-F5 [P1] Załącznik dokumentu + UI Q&A  — S/M
- **Cel:** dołącz PDF/xlsx i pytaj.
- **Zakres:** chip dokumentu (reuse M9-F4); przepływ pytania; oznaczenie „Based on document".
- **DoD:** załączony dokument → ugruntowana odpowiedź.
- **Test:** Vitest — stan załącznika dokumentu.

### M10-F6 [P1] Wskaźnik kosztu/użycia  — S
- **Cel:** user widzi, ile go kosztuje rozmowa (BYO-key).
- **Zakres:** mały badge: liczba wywołań narzędzi + zużycie tokenów per rozmowa.
- **DoD:** licznik widoczny per rozmowa.
- **Test:** Vitest — formatowanie użycia.

---

## 3. Kolejność i zależności

```
B1 (klient Responses)  ──►  B2 (live search)  ──►  B6 (licznik)
        │                ──►  B3 (wizja)
        │                ──►  B4 (dokument inline)  ──►  B5 (kolekcje, stretch)

F1 (zdarzenia narzędzi) ─┐
F2 (cytowania)          ─┼─► po B1/B2
F3 (przełącznik search) ─┘
F4 (obraz)  → po B3 ;  F5 (dokument) → po B4 ;  F6 (koszt) → po B6
```

- **Fundament:** `B1` — bez nowego klienta Responses nic z M10 nie ruszy.
- **Pierwszy „wow" (i materiał marketingowy):** `B1→B2→F1→F2→F3` = live search z X/web,
  widoczny wskaźnik szukania i klikalne cytowania. To jest wyróżnik, którego rdzeń
  Claude Code/Codex nie ma.
- `B3/F4` (wizja) spina się z M9-B4 — „Send to → Describe" działa end-to-end.
- `B5` traktuj jako stretch; jak M10 puchnie, przesuń kolekcje dalej.

## 4. Definicja ukończenia M10 (całość)

1. Pytanie o świeży temat uruchamia live web/X search po stronie serwera, a odpowiedź ma
   **klikalne cytowania**.
2. Przełącznik **Auto/On/Off** realnie steruje narzędziami.
3. Wrzucony **obraz** → trafny, ugruntowany opis (vision).
4. Załączony **PDF/arkusz** → odpowiedź oparta na treści dokumentu.
5. **Licznik wywołań/tokenów** widoczny per rozmowa (transparentność BYO-key).
6. Rdzeń czatu chodzi przez **Responses API** (zero `search_parameters`); strumień UTF-8 bez
   regresji; trasy fail-closed na tokenie; `api_smoke` + Vitest przechodzą; hardening
   M1/M5–M6 nienaruszony.

## 5. Otwarte pytania techniczne

- **Migracja rdzenia czatu:** przełączasz CAŁY czat na Responses API od razu (jeden kod,
  ale większy refactor), czy nowy klient obsługuje tylko wiadomości z narzędziami, a zwykły
  czat zostaje na `chat/completions` do czasu? Rekomendacja: cały na Responses — `chat/completions`
  i tak jest legacy, a dwie ścieżki to dług.
- **OAuth vs klucz dla Responses + tools:** zweryfikuj, czy tool-use działa na tokenie OAuth;
  jeśli nie — wymuś ścieżkę klucza API dla wiadomości z searchem.
- **Modele w selektorze:** wizja i `file_search` wymagają grok-4. Czy wszystkie modele w UI to
  grok-4? Jeśli nie — wyłącz/ukryj wizję i kolekcje dla starszych, z czytelnym komunikatem.
- **Kolekcje (B5):** koszt utrzymania vector store per projekt + limity — w M10 czy później?
- **Cytowania a copyright:** pokazuj źródła i krótkie streszczenia własnymi słowami, nie kopiuj
  długich fragmentów stron do UI (czysto produktowo bezpieczniejsze).

---

## 6. Status M10 — KOMPLETNY: B1–B6 + F1–F6 (2026-06-05)

Zrealizowano **CAŁY M10**: `B1→B6` i `F1→F6`. **Live search ORAZ Q&A nad dokumentem działają na
realnym API** (potwierdzone przez użytkownika: pytanie → search → klikalne cytowania [1..7] +
licznik „1 search · 12k tokens"; załączony PDF → trafne streszczenie z „Based on document").
Ostatni element — **B5 (kolekcje/`file_search`)** — domknięty (trwała wiedza projektu).

**Backend (`grok_core`):**
- **B1 ✅ `responses_client.py`** — klient `POST /v1/responses` ze streamingiem: konwersja
  `messages → input` (`to_input`: user/system→`input_text`, assistant→`output_text`,
  `image_url`→`input_image`, balans historii), parser zdarzeń typowanych
  (`response.output_text.delta`, `*_search_call.*`, `annotation`, `response.completed`),
  **jawne UTF-8** (`iter_lines(decode_unicode=False)`+`.decode`), auth z `state.get_api_key`.
  Zwraca `{text, citations, usage, tool_calls}`. Cienka warstwa endpoint/auth — root
  `api_manager.py` NIETKNIĘTY.
- **B2 ✅ live search** — `build_search_tools(mode, sources)`: `off`→brak narzędzi,
  `auto/on`→`web_search`/`x_search`. Cytowania zbierane (dedup po URL) ze zdarzeń adnotacji
  i z `response.completed`. Liczone unikalne wywołania narzędzi.
- **B3 ✅ wizja** — `to_input` mapuje obraz→`input_image`; trasa gat­uje obraz/dokument na
  modelu spoza rodziny grok-4 czytelnym błędem (`_is_grok4` = `grok-4*`, `_has_rich_input`).
- **B4 ✅ Q&A nad dokumentem (inline)** — `to_input` mapuje part `document`
  (`{data:<data-URI>, mime, name}` z send-to/composera) → `input_file` (`file_data`+`filename`);
  `validation.validate_document_uri` (data-URI + cap `MAX_DOCUMENT_URI` 48 MB) — oversize
  pomijany (skip-with-log, bez wywracania tury). Bez trwałego magazynu (to B5).
- **`routes/chat.py`** — `/chat/stream` przełączony na `responses_client.stream_response`
  (single-flight, `stop`, `record_event` zachowane); **fallback na legacy
  `chat/completions`** tylko dla czystego czatu, gdy Responses padnie przed pierwszą deltą
  (search nie ma fallbacku — `search_parameters` = 410). Nowe ramki WS: `tool_call`,
  `citations`, `usage`. Pola wejścia: `search_mode` (domyślnie `off` — bez kosztu bez zgody),
  `sources`.
- **B5 ✅ wiedza projektu — LOKALNA, dołączana na żądanie** ⚠️ **PIVOT (2026-06-05):** xAI
  **nie wspiera** serwerowych vector stores (`/v1/vector_stores` → **404**, potwierdzone przez
  usera), więc `file_search` odpadł. Zamiast tego: dokumenty trzymane **lokalnie** pod
  `config.PROJECT_DOCS_DIR` (`DATA_DIR/project_docs/<project_id>`), dołączane do wiadomości jako
  `input_file` **na żądanie** („Attach all") — ścieżka B4, sprawdzona. Bez kosztu per wiadomość;
  user decyduje, kiedy. `history_store`: tabela `collection_files` (+ kolumny `path`,`mime`;
  migracja `ALTER TABLE`); `Backend.collection_upload/files/file_path/remove` (zapis na dysk,
  anty-traversal pod PROJECT_DOCS_DIR); `routes/collections.py`: `POST /collections/files`
  (data-URI JSON), `GET /collections`, `GET /collections/files/{id}/content` (FileResponse,
  sandbox), `DELETE …`. **`collections_client.py` USUNIĘTY** (był pod vector store); chat nie
  dokłada już `file_search`.
- **B6 ✅ (przez B2)** — `usage` (tokeny) + `tool_calls` emitowane ramką `usage` i zapisane
  w `meta` historii huba (`record_event`).
- **`routes/settings.py`** — `chat_search_mode` + `chat_search_sources` (domyślny tryb per app).

**Frontend (`desktop/src/renderer`):**
- **F1 ✅** wskaźnik „Searching the web/X…" z ramek `tool_call` (`searchActivityLabel`).
- **F2 ✅** panel **Sources** — klikalne chipy (https, `target=_blank`→`shell.openExternal`),
  dedup, zapis na wiadomości asystenta (przeżywa reload). **Polish:** etykieta chipa to
  `citationLabel` — realny tytuł, a gdy API zwraca numer odnośnika (`"1"`,`"2"`) → domena
  (`citationHost`). (Realne API zwraca numeryczne tytuły — widoczne w zrzucie usera.)
- **F3 ✅** przełącznik **Auto/On/Off** + wybór źródeł (Web/X) w popoverze nagłówka; domyślny
  tryb zapisywany w `/settings`.
- **F4 ✅** wejście obrazu — istniejący pipeline załączników (M9-F4, `toApiMessages`→`image_url`)
  + gating B3; domyślny model `grok-4.3` (rodzina grok-4) obsługuje wizję.
- **F5 ✅** załącznik dokumentu — `fileToAttachment`/`isDocumentFile` (PDF/Office → data-URI,
  cap 32 MB), `toApiMessages`→part `document`, chip z badge'em (PDF/XLS…), `inputBlockToAttachment`
  obsługuje blok document (**domyka dług M9** „document→załącznik"), oznaczenie **„Based on
  document"** na odpowiedzi (gdy poprzednia tura miała dokument).
- **F6 ✅** badge kosztu „N searches · X tokens" (`formatUsage`) na wiadomości.
- **B5 UI ✅** `KnowledgePopover` (ikona Library w nagłówku): upload/list/remove dokumentów
  wiedzy aktywnego projektu + **„Attach all to message"** (pobiera treść każdego dokumentu →
  `blobToDataUri` → załącznik `document` w composerze przez `onAttach=att.add`). Brak projektu →
  **inline create/select** (lista projektów + pole „New project…"; przełącznik był tylko w History).
- Czyste utile w `lib/searchState.ts` (Vitest: `searchState.test.ts`); document w
  `attachments.test.ts` + `sendTo.test.ts`.

**Decyzje (odpowiedzi na §5 „otwarte pytania"):**
- **Migracja rdzenia:** CAŁY czat idzie przez Responses (zgodnie z rekomendacją), ale czysty
  czat ma **fallback na legacy** — bo realnego `/v1/responses` nie da się zweryfikować w
  sandboxie (TLS), więc fallback chroni podstawowy czat przy rozjeździe wire-formatu. Search
  (z narzędziami) fallbacku NIE ma.
- **`tool_choice`:** `auto`→bez `tool_choice` (model decyduje), `on`→`tool_choice="required"`
  (wymuszony search). Wartość „required" do potwierdzenia na realnym API (izolowana).
- **Modele/wizja:** gating po `grok-4*`; starsze (grok-3) dostają czytelny błąd zamiast
  niejasnego 4xx.

**Zweryfikowane:**
- **NA REALNYM API (user, 2026-06-05):** live search end-to-end (pytanie → server-side search →
  klikalne cytowania [1..7] + „1 search · 12k tokens") ORAZ **Q&A nad dokumentem** (załączony PDF
  → trafne streszczenie). Kształt drutu Responses/search/citations/usage/`input_file` POTWIERDZONY.
  **`/v1/vector_stores` → 404** (user) → B5 zpivotowane na lokalne dokumenty + „Attach all" (B4).
- `api_smoke.py` — **141/141 PASS** (`_unit_responses_client`: UTF-8, balans `input`, zdarzenia
  narzędzi, dedup cytowań, usage, `off`→bez narzędzi, bearer z providera, document→`input_file`,
  oversize-skip; **`_unit_collections`** (lokalne): upload→plik na dysku+rekord(path/mime), list,
  content (FileResponse), remove, **anty-traversal** pod PROJECT_DOCS_DIR, data-URI/projekt guard;
  `_unit_chat_bridge` — protokół, `tool_call`,
  `citations`, fallback, gating wizji/dokumentu, single-flight).
  `agent_selfcheck.py` 81/81 — zero regresji (mimo migracji schematu `projects`/`collection_files`).
- `npm run typecheck` ✅. UI w podglądzie web (devMock): popover Auto/On/Off + źródła, panel
  **Sources**, badge kosztu, chip dokumentu (PDF) + „Based on document", **Knowledge popover
  (Library) + inline create projektu** — renderują się.
- Vitest (`searchState`/`attachments`/`sendTo`) **napisany**, ale devDep `vitest` nie jest
  zainstalowany w tym środowisku (jak w CLAUDE.md — wymaga jednorazowego `npm install -D`); logika
  sprawdzona typami + ręcznie.

**Do weryfikacji po stronie użytkownika (pozostałe):** **B5 lokalne** — pełny przepływ „Attach all"
na maszynie usera (upload PDF do projektu → „Attach all" → wiadomość → odpowiedź ugruntowana). Mechanizm
opiera się WYŁĄCZNIE na sprawdzonym `input_file` (B4 potwierdzony), więc ryzyko niskie. `tool_choice=
"required"` dla trybu „On" (web search) — do potwierdzenia (izolowane w `responses_client.py`).

**M10 zamknięty** — wszystkie kamienie B1–B6 + F1–F6 zrealizowane. Kolejny milestone wg roadmapy:
**M13** (agent: zaufanie — diffy/plan/checkpoint/`GROK.md`).
