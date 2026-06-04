# PLAN_M9_SZKIELET.md — Szkielet huba (rozpis zadań)

> Rozpis milestone'u **M9** z `PLAN_ROZBUDOWY.md` na zadania w stylu `P0-x` z
> `PLAN_NAPRAWY`. Cel M9: pięć trybów przestaje być pięcioma zakładkami i zaczyna
> dzielić **jeden kręgosłup** — model artefaktu, jedną przeszukiwalną historię,
> pipeline załączników, wspólny projekt i paletę komend.
>
> Tagi: **[P0]** krytyczne dla M9, **[P1]** ważne. Wysiłek: S≈dni, M≈1–2 tyg.

---

## Status (2026-06-04)

## ✅ M9 UKOŃCZONY — Backend (B1–B5) + Frontend (F1–F6). B6 pominięty (zrealizowany przez B2).

Backend:
- [x] **B1** — model artefaktu + magazyn SQLite/FTS5 + `history_check` (`38863c9`)
- [x] **B2** — rejestracja zdarzeń ze wszystkich trybów (`3991357`)
- [x] **B3** — REST `/history`,`/artifacts`,`/artifacts/{id}/content` (+ fix kolizji z legacy `/history`) (`ed75f2e`)
- [x] **B4** — magistrala „send-to" → blok wejściowy LLM (`166ac57`)
- [x] **B5** — projekt jako wspólny scope historii/artefaktów (`c4cc512`)
- [~] **B6** — POMINIĘTY (zrealizowany przez B2 — patrz niżej)

Frontend:
- [x] **F1** — klient API huba + `Hub` context (`hub.tsx`/`hubQuery.ts`) (`42b7f1b`)
- [x] **F2** — wzorzec „Send to…" (`SendToMenu` + konsumenci Chat/Code) (`507ac28`)
- [x] **F3** — jedna przeszukiwalna historia (przebudowa `History.tsx`) (`42b7f1b`)
- [x] **F4** — załączniki: miniatury w History (`ArtifactThumb`) + drop plików do composera (`efa4db1`)
- [x] **F5** — paleta komend Ctrl-K (`CommandPalette`) (`efa4db1`)
- [x] **F6** — przełącznik projektu (`ProjectSwitcher`) (`507ac28`)

Jakość: `history_check` 59 PASS, `api_smoke` rozszerzony, frontend typecheck czysty, Vitest gotowy
(`hubQuery`/`sendTo`/`commands`), render-smoke palety w podglądzie web. Zero regresji M1/M5–M6.
**Następny kamień: M10** (czat: Responses API + live search) — patrz `PLAN_M10_CZAT.md`.

---

## 0. Koncept spinający: Artefakt

Sercem M9 jest jeden typ: **Artifact** — znormalizowany rekord dowolnej treści, która
może przepływać między trybami.

```
Artifact {
  id            // uuid
  type          // "image" | "video" | "audio" | "file" | "text" | "code"
  mode          // tryb-źródło: "chat" | "image" | "video" | "voice" | "code"
  mime          // np. image/png, application/pdf
  path          // ścieżka pod config.DATA_DIR (lokalna); url tylko https (P1-14)
  thumb_path    // miniatura (opcjonalnie)
  meta          // { prompt, model, ts, ... }
  project_id    // przypisanie do projektu (M9-B5)
  created_at
}
```

Wszystko inne w M9 (historia, „Wyślij do…", paleta) operuje na tym typie.

### Decyzje przekrojowe (przeczytaj przed kodowaniem)
- **Magazyn = SQLite** (`config.DATA_DIR/grok_history.db`, w IS_FROZEN → `%LOCALAPPDATA%`).
  `sqlite3` jest w stdlib (zero nowych zależności), a **FTS5** daje pełnotekstowe szukanie
  po całej historii. Działa identycznie na Windows/macOS/Linux — spójne z celem cross-platform.
- **NIE pisz do `grok_config.json`** — należy wyłącznie do `HistoryManager` (przepisywany w całości).
  M9 dostaje własny magazyn.
- **Czat zostaje w `localStorage` (`useConversations`)** — M9 dokłada *dodatkowo* most do
  backendowej historii (M9-B6), nie wyrywa istniejącego mechanizmu. (Decyzja długoterminowa:
  czy backend staje się jedynym źródłem prawdy — poza zakresem M9.)
- **REST, nie WS** — M9 to zapytania (lista/szukaj/pobierz), nie strumień. Wszystkie nowe trasy
  **fail-closed** (`require_token`, P1-10), wejście walidowane przez `validation.py`.
- **UI po angielsku** (konwencja repo): w kodzie stringi „Send to…", „Search history…",
  „New project". Polski tylko w tym planie i w komentarzach.

---

## 1. Backend (`grok_core`)

### ✅ M9-B1 [P0] Model artefaktu + magazyn SQLite  — M
- **Cel:** trwały, przeszukiwalny magazyn artefaktów i zdarzeń historii.
- **Zakres:** nowy moduł `grok_core/history_store.py`. Schemat: tabele `artifacts`,
  `history_events`, wirtualna tabela `history_fts` (FTS5 nad treścią + meta). Inicjalizacja
  idempotentna; kontrola integralności przy starcie (uszkodzona baza → `.corrupt` backup,
  analogicznie do `config.load_json_or_backup`). Ścieżki wyłącznie przez `config` (IS_FROZEN-aware).
- **DoD:** insert artefaktu i odczyt po id; baza powstaje pod `DATA_DIR`; przeżywa restart sidecara.
- **Selfcheck:** nowy `grok_core/tools/history_check.py` — roundtrip insert→get, FTS zwraca trafienie,
  ścieżka bazy faktycznie pod `DATA_DIR` (brak ucieczki), uszkodzony plik → backup nie wipe.

### ✅ M9-B2 [P0] Rejestracja zdarzeń ze wszystkich trybów  — M
- **Cel:** każdy tryb dorzuca zdarzenie do wspólnej historii.
- **Zakres:** cienki helper `history_store.record_event(mode, text, artifact_id?, project_id)`
  wpięty w istniejące trasy: chat (po odpowiedzi), media image/video (po wygenerowaniu),
  voice (transkrypt), agent (podsumowanie sesji). Bez blokowania ścieżki użytkownika
  (zapis poza gorącą pętlą; przy strumieniu — po `WsStream` zakończeniu).
- **DoD:** wiadomość czatu, generacja obrazu i transkrypt głosu produkują wyszukiwalne zdarzenia.
- **Selfcheck:** `history_check` — dla każdego trybu zdarzenie ląduje i jest znajdowane przez FTS.

### ✅ M9-B3 [P0] REST: historia i artefakty  — M
- **Cel:** front ma czym czytać kręgosłup.
- **Zakres:** nowy router `grok_core/routes/history.py`:
  - `GET /history` — lista + filtry `mode`, `project_id`, `from/to`, `q` (FTS), paginacja.
  - `GET /artifacts` — lista (filtry jw.).
  - `GET /artifacts/{id}` — metadane.
  - `GET /artifacts/{id}/content` — strumień pliku (z `DATA_DIR`, walidacja ścieżki).
  Modele Pydantic z limitami z `validation.py`. Wszystko `require_token` (fail-closed).
- **DoD:** `GET /history?q=cyberpunk&mode=image` zwraca ranking; `/artifacts/{id}/content` oddaje plik;
  brak/zły token → 401.
- **Selfcheck:** rozszerz `grok_core/tools/api_smoke.py` o te trasy + enforcement tokenu.

### ✅ M9-B4 [P0] Magistrala „send-to": artefakt → wejście trybu  — M
- **Cel:** wynik jednego trybu staje się poprawnym wejściem innego (rdzeń „all-in-one").
- **Zakres:** `history_store`/helper zamienia `artifact_id` na gotowy blok wejściowy dla celu:
  - obraz → blok vision (base64 `image`) dla czatu/agenta,
  - pdf/arkusz → blok `document`,
  - text/code → cytat/kontekst.
  Reużyj walidatorów media/data-URI z `validation.py`; obrazy z dysku, nie z sieci.
- **DoD:** dla artefaktu-obrazu backend zwraca blok vision gotowy do `chat`; dla pdf — blok document.
- **Selfcheck:** `history_check` — kształt bloku zgodny z typem artefaktu (image→vision, pdf→document).

### ✅ M9-B5 [P1] Projekt jako obywatel pierwszej kategorii  — S/M
- **Cel:** historia i artefakty są scope'owane projektem.
- **Zakres:** rekord `project` (id, name, root, created). `history_events`/`artifacts` niosą
  `project_id`. `recent_workspaces` z ustawień podniesione do listy projektów (most, nie duplikat).
- **DoD:** przełączenie projektu zawęża wyniki `/history` i `/artifacts`.
- **Selfcheck:** `history_check` — filtr `project_id` izoluje zdarzenia poprawnie.

### M9-B6 [P1] Most czatu do historii (addytywny)  — S
> **STATUS (2026-06-04): POMINIĘTY — zrealizowany przez B2.** Decyzja: B2 już zapisuje czat
> serwerowo (event `mode=chat` po każdej turze WS, z promptem usera w `meta`/FTS), więc DoD B6
> („wiadomość czatu znajdowana przez `GET /history?q=...`") jest spełniony bez osobnej trasy
> renderer→event. Dodatkowy `POST /history/event` byłby źródłem duplikatów. `localStorage`
> (`useConversations`) zostaje fast-path/cache'em. Gdyby pojawiła się potrzeba pushu zdarzeń
> nie-streamowanych z UI, można dodać tę trasę później (z dedup względem B2).
- **Cel:** czat (dziś w `localStorage`) jest widoczny w jednej historii, bez wyrywania `useConversations`.
- **Zakres:** trasa `POST /history/event` (lub piggyback na B2) wywoływana przez renderer po wysłaniu/
  odebraniu wiadomości; `localStorage` zostaje cache'em/fast-path.
- **DoD:** wiadomość czatu jest znajdowana przez `GET /history?q=...`.
- **Selfcheck:** `api_smoke` — POST eventu czatu → potem GET znajduje go po treści.

---

## 2. Frontend (`desktop/src/renderer`)

### ✅ M9-F1 [P0] `ArtifactContext` + typ „artefakt" + most `window.grok`  — M
- **Cel:** wspólny stan artefaktów dla wszystkich trybów.
- **Zakres:** React context (typy lustrzane do backendu), stan „pending send"; metody w preload/
  `window.grok`: `listHistory`, `searchHistory`, `getArtifact`, `getArtifactContent`. Buduj na
  istniejących prymitywach UI (Tailwind v4, `components/ui/`), nie nowy CSS per-komponent.
- **DoD:** dowolny tryb rejestruje wytworzony artefakt; kontekst trzyma stan w sesji.
- **Test:** Vitest (`desktop/test/`) — reduktor/util stanu artefaktu (czyste funkcje).

### ✅ M9-F2 [P0] Wzorzec „Send to…"  — M
- **Cel:** jedno kliknięcie przenosi artefakt do innego trybu z preloadowanym wejściem.
- **Zakres:** menu na każdym artefakcie (obraz/wideo/plik/wiadomość/kod): **Send to → Chat / Code /
  Image / Describe**. Cel otwiera się z artefaktem jako wejściem (przez B4). To usystematyzowanie
  Twojego „Opisz obraz" ze zrzutu — z ad-hoc załącznika w powtarzalny wzorzec.
- **DoD:** generacja obrazu → „Describe" → czat otwarty z obrazem jako wejściem vision.
- **Test:** Vitest — akcja send-to mapuje `artifact → payload` celu.

### ✅ M9-F3 [P0] Jedna przeszukiwalna historia (przebudowa History)  — M
- **Cel:** zakładka History pokazuje wszystkie tryby z pełnotekstowym szukaniem.
- **Zakres:** czyta `GET /history` z polem szukania + filtry (mode, project, data). Klik wpisu →
  skok do trybu-źródła / podgląd artefaktu.
- **DoD:** wpisanie frazy filtruje w poprzek trybów; klik otwiera element.
- **Test:** Vitest — util stanu zapytania/filtrów.

### ✅ M9-F4 [P1] Pipeline załączników (drag&drop + podgląd)  — M
- **Cel:** jeden komponent załącznika dla czatu/agenta/obrazu (wejście) i „send-to".
- **Zakres:** wspólny „chip"/podgląd artefaktu; drag&drop pliku lub artefaktu (np. z History) →
  staje się wejściem. Reużycie w „Send to…".
- **DoD:** przeciągnięcie obrazu z History do composera czatu → załączony jako wejście.
- **Test:** Vitest — normalizacja modelu załącznika.

### ✅ M9-F5 [P1] Paleta komend (Ctrl/Cmd-K)  — S/M
- **Cel:** klawiaturowy skok do trybu/akcji/artefaktu — natychmiastowa spójność UX.
- **Zakres:** rejestr komend: nawigacja do trybów, ostatnie artefakty, szukaj w historii, szybkie
  akcje (New chat, New project). Buduj na `components/ui/`.
- **DoD:** Ctrl-K otwiera; wpisywanie znajduje tryby/komendy/ostatnie artefakty; Enter wykonuje.
- **Test:** Vitest — util filtrowania/rankingu komend.

### ✅ M9-F6 [P1] Przełącznik projektu  — S
- **Cel:** tworzenie/zmiana projektu scope'ująca historię i artefakty.
- **Zakres:** UI tworzenia/wyboru projektu (na bazie `recent_workspaces`); zmiana odświeża History
  i listy artefaktów.
- **DoD:** zmiana projektu aktualizuje History + artefakty.
- **Test:** Vitest — stan projektu.

---

## 3. Kolejność i zależności

```
B1 (magazyn)  ──►  B2 (zdarzenia)  ──►  B3 (REST)  ──►  B6 (most czatu)
   │                                      │
   └──► B4 (send-to bus)                  └──► B5 (projekt)

F1 (context)  ──►  F2 (Send to…)
   │           ──►  F3 (History)
   │           ──►  F4 (załączniki)
   └──────────────► F5 (paleta), F6 (projekt)
```

- **Najpierw fundament:** `B1` + `F1` (bez nich reszta wisi).
- **Pierwszy widoczny „wow":** `B1→B2→B3→F1→F2→F3` = artefakty przepływają i wszystko jest w jednej,
  przeszukiwalnej historii. To już jest „hub".
- `B4` odblokowuje vision/document w czacie z artefaktu (spina się z M10).
- `F4/F5/F6` to dopieszczenie spójności — ważne, ale po działającym przepływie.

## 4. Definicja ukończenia M9 (całość)

1. Wygenerowany obraz pojawia się w **jednej historii**, jest **przeszukiwalny** po treści/promptcie,
   i da się go jednym kliknięciem **wysłać do czatu jako wejście vision**.
2. Wiadomość czatu, generacja media i transkrypt głosu trafiają do tej samej historii.
3. **Ctrl-K** przenosi mnie do dowolnego trybu/akcji/ostatniego artefaktu.
4. Przełączenie **projektu** zawęża historię i artefakty.
5. Nowe trasy są **fail-closed na tokenie**; magazyn nie dotyka `grok_config.json`; ścieżki działają
   też pod IS_FROZEN.
6. `history_check.py` + rozszerzony `api_smoke.py` + testy Vitest przechodzą; hardening M1/M5–M6 bez regresji.

## 5. Otwarte pytania techniczne

- **FTS5 dostępne w Twoim buildzie Pythona?** Zwykle tak (domyślnie w CPython), ale zweryfikuj w venv
  sidecara (`sqlite3` + `SELECT * FROM sqlite_master`); plan B: `LIKE` + indeks tokenów.
- **Retencja/rozmiar bazy** — limit historii / czyszczenie miniatur? (decyzja na potem, ale zarezerwuj
  pole `created_at` pod retencję).
- **Czy `History` ma podmieniać źródło czatu już teraz**, czy zostaje most addytywny (M9-B6) do czasu
  osobnej decyzji o jedynym źródle prawdy?
