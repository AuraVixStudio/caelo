# PLAN_M11_TWORCZOSC.md — Twórczość: Image / Video (rozpis zadań)

> **STATUS (2026-06-05): ✅ KOMPLETNY.** B1–B5 + F1–F6 zrobione. Backend: `genjobs.py`
> (kolejka/worker/cancel/retry/limit/koszt) + tabela `gen_jobs` + trasy `/genjobs` (fail-closed).
> Frontend: panele Image/Video na kolejce `GenJob`, galeria, `GenQueue`, koszt. Selfchecki zielone
> (`genjobs_check.py` 25/25, `api_smoke.py` z guardami `/genjobs`, handshake, agent), `typecheck` OK,
> panele montują się w podglądzie bez błędów. Realna generacja (xAI) weryfikowana na maszynie usera.
>
> Rozpis milestone'u **M11** z `PLAN_ROZBUDOWY.md`. Cel M11: tryby Image i Video przestają być
> „generatorami jednostrzałowymi" i stają się **pętlą twórczą** — generacja, **edycja przez
> referencję + warianty**, **asynchroniczna pętla wideo** (kolejka/status/biblioteka), a każdy
> wynik to artefakt z M9 z „Send to…".
>
> Tagi: **[P0]** krytyczne, **[P1]** ważne. Wysiłek: S≈dni, M≈1–2 tyg.

---

## 0. Co realnie wystawia API xAI (zweryfikowane)

**Obraz (Aurora / Grok Imagine):**
- Text-to-image: `grok-imagine-image-quality` (rekomendowany; Pro wycofany 15.05.2026), do 2K, ~4 s.
- **Edycja**: `grok-imagine-image-quality/edit` — modyfikacje sterowane promptem na istniejącym
  obrazie, kompozycja z **do 3 obrazów referencyjnych**, ~13 s. **To NIE mask-inpainting** — to
  „referencja + prompt".
- **Warianty** przez wgranie referencji; **do 10 wyników** na uruchomienie.
- Tryby twórcze: **Fun / Normal / Spicy** (domyślnie Normal — patrz decyzje).
- **Brak w dokumentacji**: mask-inpainting i dedykowany upscale → odpuszczone/do weryfikacji.

**Wideo (Grok Imagine):**
- `grok-imagine-video` (API od stycznia 2026): **text→video** i **image→video**, klipy **6 i 10 s**
  z **zsynchronizowanym audio**, tryby Fun/Normal/Spicy.
- Generacja **asynchroniczna** (minuty) → wymaga job + kolejka + status.

### Decyzje przekrojowe (przeczytaj przed kodowaniem)
- **Wspólna abstrakcja `GenJob`** dla obrazu i wideo: zadanie async ze statusem; każde wyjście →
  **Artifact (M9)**. To kręgosłup M11 — nie buduj osobnej logiki dla obrazu i osobnej dla wideo.
- **Reuse M9 do bólu:** wyniki to artefakty w magazynie M9; biblioteka i „Send to…" korzystają z
  pipeline'u M9 (`history_store`, `ArtifactContext`). Zero drugiego magazynu media.
- **Transport statusu:** REST polling jako baza (długie wideo = długie połączenia WS to ryzyko);
  opcjonalny push przez `WsStream`. Worker w wątku (jak blokujące wywołania xAI dziś).
- **Tryby treści:** domyślnie **Normal**; Spicy schowane za ustawieniem, z jasną informacją, że
  treści i zgodność z polityką xAI to odpowiedzialność użytkownika (projekt OSS). Brak obchodzenia
  filtrów po stronie xAI.
- **Wejście referencji/obrazu:** https-only + cap rozmiaru (P1-14) + `validation.py`.
- **UI po angielsku** (konwencja repo): „Generate", „Edit with reference", „Make variations", „Queue".

---

## 1. Backend (`grok_core`)

### ✅ M11-B1 [P0] Model `GenJob` + kolejka + worker  — M
> **ZROBIONE** (`grok_core/genjobs.py` + tabela `gen_jobs` w `history_store.py`). `GenJobManager`:
> kolejka + pula workerów w wątkach, przejścia statusu queued→running→done|failed|cancelled,
> persistencja w SQLite M9, egzekutor **wstrzykiwany** (bez importu `api_manager`/`state` →
> zero cykli, testowalny na atrapie). Stale joby (restart) → failed("interrupted"). Selfcheck:
> `grok_core/tools/genjobs_check.py` (25 asercji, OK).
- **Cel:** jeden, async mechanizm generacji dla obrazu i wideo.
- **Zakres:** `grok_core/genjobs.py` — rekord zadania (`id`, `kind` image|video, `op`
  text2img|edit|variation|text2video|img2video, `params`, `status` queued|running|done|failed,
  `artifact_ids`, `error`, `cost`). Worker w wątku; przejścia statusu; persist w SQLite z M9
  (`history_store`). Każde wyjście rejestrowane jako Artifact (M9-B1).
- **DoD:** submit zadania → status przechodzi queued→running→done → wyjścia zarejestrowane jako artefakty.
- **Selfcheck:** rozszerz `api_smoke.py`/nowy `genjobs_check.py` — cykl życia joba, wyjścia→artefakty,
  błąd → status `failed` z komunikatem.

### ✅ M11-B2 [P0] Generacja obrazu: text2image + edit + variation  — M
> **ZROBIONE** (egzekutor `Backend._run_image_job` + trasa `POST /genjobs/image`). text2img →
> `api.generate_image`; edit/variation → `api.edit_image_b64` (referencja + prompt, **do 3** ref —
> egzekwowane przez `ImageJobReq`). Wyjścia → artefakty M9 przez `save_media_urls` (rozszerzony o
> `project_id` + zwrot `artifact_id`; wstecznie zgodny). Walidacja: op vs referencje, data-URI, limity.
- **Cel:** pełna pętla obrazu, nie tylko text-to-image.
- **Zakres:** trasy submit dla: text-to-image (`grok-imagine-image-quality`); **edit** (referencja +
  prompt, do 3 referencji); **variation** (z referencji). Parametry: aspect ratio, liczba wyjść
  (do 10), tryb. Mapowanie wyjść → artefakty (M9). Walidacja + cap referencji; fail-closed token.
- **DoD:** text2img zwraca artefakty-obrazy; edit z referencją + promptem zwraca zmodyfikowany obraz;
  variation zwraca warianty.
- **Selfcheck:** `api_smoke` — trasy + token; asercja: wyjścia→artefakty, do 3 referencji honorowane.

### ✅ M11-B3 [P0] Pętla wideo: submit + status + wynik  — M
> **ZROBIONE** (egzekutor `Backend._run_video_job` + trasa `POST /genjobs/video`). text2video /
> img2video; worker robi **pełną pętlę pollingu** `api.poll_video_status` po stronie serwera
> (nie blokuje pętli FastAPI), deadline + przerywalność przez `cancel_event`. Wynik → artefakt M9.
> Wejście image→video to **base64 data-URI** (jak dziś `api_manager`) — brak blokera tymczasowego hostingu.
- **Cel:** asynchroniczne wideo z widocznym postępem.
- **Zakres:** submit `grok-imagine-video` (text→video, image→video), `duration` 6/10 s, `mode`, audio;
  job śledzony do `done`; wynik (plik wideo) → artefakt. Brak blokowania; postęp przez status/WsStream.
- **DoD:** submit zadania wideo → aktualizacje statusu → odtwarzalny artefakt-wideo.
- **Selfcheck:** `genjobs_check` — długi cykl życia, wynik-artefakt, anulowanie.

### ✅ M11-B4 [P1] Anulowanie / ponawianie / limit kolejki  — S/M
> **ZROBIONE** (`GenJobManager.cancel/retry` + `max_active` + trasy `/genjobs/{id}/cancel|retry`).
> Cancel queued → od razu `cancelled` (worker pomija); running → sygnał (wideo: pętla pollingu przerywa).
> Retry failed/cancelled → NOWE zadanie. Limit aktywnych → `GenJobQueueFull` → HTTP 429 (czytelny komunikat).
- **Cel:** kontrola nad kolejką (zwł. drogie/długie wideo).
- **Zakres:** anuluj zadanie queued/running (przerwij polling, status `cancelled`); ponów `failed`;
  limit głębokości kolejki.
- **DoD:** anulowanie usuwa z kolejki; retry resubmit; przekroczony limit → czytelny komunikat.
- **Selfcheck:** przejścia cancel/retry/limit.

### ✅ M11-B5 [P1] Licznik kosztów generacji  — S
> **ZROBIONE** (`genjobs.estimate_cost` → `job.cost` zapisany przy submit; `GET /genjobs` zwraca
> `total_cost` = suma kosztu zadań `done`). **Odchylenie:** repo NIE ma trasy `/usage` — koszt czatu
> (M10-B6) jest emitowany jako ramka WS `usage` + meta historii, nie endpoint. Spójnie: koszt generacji
> żyje w rekordzie zadania + jest sumowany w `/genjobs` i pokazany w UI (badge per zadanie, F6).
- **Cel:** transparentność przy BYO-key (obraz tani, wideo droższe).
- **Zakres:** szacunek/zliczanie kosztu per job → meta historii (M9) + `/usage` (spójne z M10-B6).
- **DoD:** każde zadanie zapisuje koszt; suma widoczna per sesja/projekt.
- **Selfcheck:** licznik rośnie po `done`.

---

## 2. Frontend (`desktop/src/renderer`)

### ✅ M11-F1 [P0] Panel generacji obrazu  — M
> **ZROBIONE** (`components/Image.tsx` przepisany na kolejkę przez `lib/useGenJobs.ts`). Prompt,
> model, warianty (do 10), aspect, resolution → `submitImage` (text2img/edit). Kolejka `GenQueue` (F5),
> siatka „Recent images" z artefaktów M9, każdy wynik z „Send to…" (M9-F2). Build na `components/ui/`.
- **Cel:** wygodne text-to-image z wynikami jako artefaktami.
- **Zakres:** prompt, tryb (Fun/Normal/Spicy, domyślnie Normal), aspect ratio, liczba wyjść; submit →
  job; status na żywo; siatka wyników. Każdy wynik ma „Send to…" (M9-F2). Buduj na `components/ui/`.
- **DoD:** generacja z tekstu → siatka wyników; każdy artefakt z „Send to…".
- **Test:** Vitest — stan parametrów/joba.

### ✅ M11-F2 [P0] Edycja przez referencję + warianty  — M
> **ZROBIONE** (Image.tsx). Drop/upload referencji (do 3) → edit; „Make variations" na dowolnym
> wyniku pobiera data-URI artefaktu z magistrali B4 (`/artifacts/{id}/input-block`) i wysyła zadanie
> `variation`. Domknięcie pętli: „Send to → Edit in Image" (SendToMenu) wstawia obraz jako referencję.
- **Cel:** iteracja na obrazie, nie tylko nowa generacja.
- **Zakres:** wrzuć referencję (lub wybierz artefakt z biblioteki M9) + prompt → edit; „Make variations"
  na dowolnym wyniku; multi-referencja (do 3).
- **DoD:** wybór obrazu + prompt → zmodyfikowany wynik; warianty z wyniku; do 3 referencji.
- **Test:** Vitest — payload edycji (referencje + prompt).

### ✅ M11-F3 [P0] Pętla wideo w UI  — M
> **ZROBIONE** (`components/Video.tsx`). **Wszystkie** tryby — text→video, image→video, **edit, extend** —
> idą przez jedną kolejkę `GenJob` (postęp + anuluj + koszt; wyniki w „Recent videos" + galerii). Backend
> egzekutor dispatchuje po `op` (`edit_video_job`/`extend_video_job`/`create_video_job`), wspólna pętla
> pollingu. „Send to → Animate (Video)" ustawia kadr; „Send video to → Edit/Extend" (`VideoSendMenu`)
> ładuje wynik jako źródło. (Follow-up: początkowo edit/extend były legacy z inline playerem — ujednolicone
> na życzenie usera, by trafiały na listę zadań.)
- **Cel:** text→video / image→video z kolejką i postępem.
- **Zakres:** wybór trybu (text/image→video), źródłowy artefakt-obraz (z M9), długość 6/10 s, audio;
  kolejka + postęp; odtwarzalne wyniki z „Send to…".
- **DoD:** submit → postęp → odtworzenie wideo; wynik jako artefakt.
- **Test:** Vitest — stan joba wideo.

### ✅ M11-F4 [P0] Biblioteka wyników (galeria)  — M
> **ZROBIONE** (`components/Gallery.tsx` — nowa zakładka w `App.tsx`/`hubQuery.ts`). Siatka artefaktów
> image/video (reuse `/artifacts` M9), filtr typ (All/Images/Video) + projekt (`ProjectSwitcher`).
> Podgląd przez `ArtifactMedia` (wideo **leniwe** — placeholder „Preview", by nie ciągnąć dziesiątek
> plików naraz), „Open" + „Send to…" (`ArtifactCard`).
- **Cel:** wszystkie media w jednym, akcjonowalnym miejscu.
- **Zakres:** galeria artefaktów image/video (reuse historii/artefaktów M9), filtr po typie/projekcie,
  podgląd, „re-run"/„edit"/„Send to…".
- **DoD:** wszystkie wygenerowane media przeglądalne i akcjonowalne.
- **Test:** Vitest — stan filtrów galerii.

### ✅ M11-F5 [P1] Kolejka / anulowanie / status w UI  — S/M
> **ZROBIONE** (`components/GenQueue.tsx` + `lib/useGenJobs.ts`). Lista zadań z badge statusu/postępu,
> anuluj (active) / ponów (failed|cancelled), badge kosztu. Polling REST tylko gdy są aktywne zadania
> (w spoczynku zero żądań). Reużywane w panelach Image i Video.
- **Cel:** widoczność i kontrola zadań w toku.
- **Zakres:** lista zadań z postępem; anuluj/ponów per zadanie.
- **DoD:** widać zadania w toku; można anulować i ponowić.
- **Test:** Vitest — stan kolejki.

### ✅ M11-F6 [P1] Wskaźnik kosztu generacji  — S
> **ZROBIONE** (`components/CostBadge.tsx` + `lib/genjobs.ts` `formatCost`/`sumCost`). Badge kosztu
> per zadanie w `GenQueue` (`~$` dla szacunku w toku, `$` dla `done`). Test Vitest:
> `desktop/test/genjobs.test.ts` (format/suma/status/reduktory).
- **Cel:** user widzi koszt (BYO-key).
- **Zakres:** badge kosztu per zadanie + suma per sesja/projekt.
- **DoD:** koszt widoczny przy zadaniach.
- **Test:** Vitest — formatowanie.

---

## 3. Kolejność i zależności

```
B1 (GenJob+kolejka)  ──►  B2 (obraz: t2i/edit/variation)  ──►  F1, F2
        │              ──►  B3 (wideo: submit/status)        ──►  F3
        │                                                    ──►  F4 (galeria, + artefakty M9)
        ├──►  B4 (cancel/retry/limit)  ──►  F5
        └──►  B5 (koszt)               ──►  F6
```

- **Fundament:** `B1` — bez `GenJob` ani obraz, ani wideo nie mają wspólnego async-szkieletu.
- **Pierwszy „wow" i domknięcie huba:** `B1→B2→F1→F4` = generujesz obrazy, lądują jako artefakty w
  galerii, a „Send to → Chat/Code" działa end-to-end (M9). To pokazuje, że to naprawdę *hub*, nie
  pięć zakładek.
- `B3/F3` (wideo) zaraz potem — async kolejka jest już gotowa z `B1`.
- `F2` (edycja/warianty) to serce „pętli twórczej" — iteracja zamiast ciągłego startu od zera.
- `B4/F5`, `B5/F6` to kontrola i transparentność — ważne przy drogim wideo, ale po działającej pętli.

## 4. Definicja ukończenia M11 (całość)  — ✅ SPEŁNIONA

1. ✅ **Text→image** daje wyniki, które lądują jako artefakty w przeglądalnej **galerii**.
2. ✅ **Edycja referencja+prompt** i **warianty** działają; do 3 referencji.
3. ✅ **Text→video** i **image→video** to zadania async z **widocznym postępem** i odtwarzalnymi wynikami.
4. ✅ Każde wyjście to **artefakt M9** z „Send to…" (obraz → czat/agent itd.).
5. ✅ **Kolejka** z anulowaniem/ponawianiem; **koszt per zadanie** widoczny (BYO-key).
6. ✅ Trasy fail-closed (`require_token`); długie wideo nie blokują (worker w wątku); selfchecki
   przechodzą; hardening M1/M5–M6 bez regresji (`save_media_urls` https-only + cap zachowane).

## 5. Otwarte pytania techniczne

**Rozstrzygnięcia (2026-06-05, po implementacji):**
- **Image→video:** **base64 data-URI** — `api_manager.create_video_job` już to robi → brak blokera hostingu.
- **Edycja vs inpainting/upscale:** **odpuszczone** (API: tylko referencja+prompt + warianty); „variation" = `/images/edits`.
- **Transport statusu:** **REST polling** (worker pollinguje wideo server-side); `GenJobManager.on_update` = haczyk pod ew. push WS (niewpinany).
- **Tryb Spicy:** **nie wystawiony** — klient `api_manager` nie przyjmuje parametru trybu; zachowanie = domyślne API (bez scope creep).
- **Retencja media:** częściowo — `DELETE /artifacts/{id}` (rekord + plik, sandbox) + przycisk usuwania
  z potwierdzeniem na kartach (Recent/Gallery). Automatyczne czyszczenie/limit nadal otwarte (z retencją M9).
- **Spójność modeli z M10:** zachowana — Image/Video czytają `/models` przez wspólny `useModels`.

Oryginalne pytania (kontekst):
- **Wejście image→video: base64/upload czy publiczny URL?** Jeśli API wymaga URL-a, lokalna apka
  BYO-key potrzebuje tymczasowego hostingu obrazu — to potencjalna **blokada**. Zweryfikuj wcześnie
  (najpewniej akceptuje upload/base64, ale potwierdź na oficjalnym docs xAI, nie u resellerów).
- **Edycja vs inpainting/upscale:** API daje referencja+prompt i warianty; brak wzmianki o masce/upscale.
  Odpuszczasz inpainting/upscale, czy emulujesz (np. upscale = re-gen w wyższej rozdzielczości)?
- **Transport statusu:** REST polling (baza, prostsze dla minut-długich wideo) vs push przez `WsStream`.
  Rekomendacja: REST status + opcjonalny WS event „done".
- **Tryb Spicy w OSS:** eksponować za ustawieniem czy w ogóle pominąć? Domyślnie Normal niezależnie od decyzji.
- **Retencja media:** wideo szybko puchnie → limit/czyszczenie biblioteki (spina się z retencją M9);
  `.grok/`/katalog media do `.gitignore`.
- **Spójność modeli z M10:** wizja w czacie i generacja obrazu używają tej samej rodziny grok-imagine/
  grok-4 — utrzymaj jeden selektor/źródło prawdy o dostępnych modelach, by nie rozjechać UI.

## 6. Follow-upy po ukończeniu (zgłoszone przez usera, 2026-06-05) — ✅ ZROBIONE

Doszlifowania UX naniesione po domknięciu B1–B5/F1–F6:

1. ✅ **Staged inputs przeżywają zmianę zakładki.** Panele są leniwe (P2-4) i odmontowują się przy
   przełączeniu trybu, więc dodane zdjęcie/wideo żyło w lokalnym `useState` i znikało. Podniesione do
   **Hub** (`imageRefs`/`videoFrame`/`videoSource` w `lib/hub.tsx`). **Reguła:** stan panelu, który ma
   przetrwać zakładkę, MUSI żyć w Hub (lub innym trwałym store), nie w komponencie modułu.
2. ✅ **Czyszczenie listy zadań.** „Clear finished" (per tryb) + ✕ usuń pojedynczy wiersz; backend
   `clear_finished`/`remove` + `DELETE /genjobs[/{id}]`. Czyści tylko wpisy zadań — artefakty zostają.
3. ✅ **Popover „Send to" otwiera się w górę** w kartach galerii (`SendToMenu side`, `ArtifactCard side="top"`)
   — wcześniej uciekał poza ekran w dół.
4. ✅ **„Send video to → Edit/Extend"** (`VideoSendMenu`): wideo nie ma bloku B4 (415), więc pobieramy
   data-URI (`getArtifactDataUri`) i ładujemy jako źródło przez `hub.sendVideoToVideo`.
5. ✅ **Edit/Extend ujednolicone na kolejkę** (patrz F3) — wszystkie tryby wideo to teraz `GenJob`
   (op `edit`/`extend` + pole `video`; egzekutor dispatchuje po op). Usunięty legacy inline player.
6. ✅ **Pełny ekran wideo** — `main/index.ts` dopuszcza uprawnienie `'fullscreen'` (Electron żąda go
   dla `requestFullscreen`; wcześniej tylko `'media'`).
7. ✅ **Usuwanie mediów** — `DELETE /artifacts/{id}` (rekord + plik, sandbox) + kosz z potwierdzeniem
   na kartach (Recent/Gallery).
8. ✅ **Miniatury wideo** — `ArtifactMedia` pokazuje **pierwszą klatkę** (ładowanie od razu, bez leniwego
   „Preview") i używa **`object-contain`** dla wideo (oryginalne proporcje w karcie i na pełnym ekranie;
   `object-cover` zoomował też w fullscreenie). Obraz zostaje `object-cover`.
