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
