# PLAN_M13_AGENT_ZAUFANIE.md — Agent: zaufanie (rozpis zadań)

> Rozpis milestone'u **M13** z `PLAN_ROZBUDOWY.md`. Cel M13: zakładka Code przestaje być
> „straszna" — zanim ktoś puści agenta na realne repo, musi **widzieć i móc cofnąć** to,
> co agent robi. Cztery filary: **przeglądalne diffy**, **tryb planowania**,
> **checkpointy/undo** i **`GROK.md`** (auto-pamięć projektu).
>
> To „table stakes" dla parytetu z Claude Code/Codex — nie pełna platforma, tylko zaufanie.
> Tagi: **[P0]** krytyczne, **[P1]** ważne. Wysiłek: S≈dni, M≈1–2 tyg., L≈3–4 tyg.

---

## 0. Na czym budujemy (masz już 80% fundamentu)

- **`PermissionGate`** (`permissions.py`) — bramka mutacji już istnieje. Diffy **wpinają się w nią**,
  nie obok: zatwierdzenie niesie diff.
- **Podział READONLY / MUTATING** w `tools.py` — tryb planowania to po prostu sesja, w której
  dozwolone są tylko READONLY. Zero nowej klasyfikacji.
- **`atomic_write_text`** — checkpoint to warstwa wyżej nad atomowym zapisem, który już masz.
- **`Workspace.resolve`** — każdy restore/rollback przechodzi przez sandbox (brak ucieczki).
- **`WsStream`** + `{"type":"stop"}` + syntetyczne wyniki przerwanych `tool_calls` — strumień i
  balans historii już zrobione; dokładasz tylko nowe typy zdarzeń (diff/plan/checkpoint).
- **`agent_selfcheck.py`** (81 asercji) — rozszerzasz, nie piszesz testów od zera.

### Decyzje przekrojowe (przeczytaj przed kodowaniem)
- **Checkpoint = kopia śledzonych plików (bez zależności od git).** Przed pierwszą modyfikacją
  danej ścieżki kopiuj oryginał do `.grok/checkpoints/<session_id>/` + manifest. Undo = przywróć
  z manifestu (`atomic_write_text`), a pliki utworzone przez agenta — usuń. Cross-platform,
  działa też gdy workspace nie jest repo git. (Shadow-git jako późniejsza optymalizacja przy
  wielu plikach — patrz pytania.)
- **Undo jest per-sesja** w M13 (stos per-mutacja później).
- **Szczerość wobec `run_command`:** undo cofa tylko **edycje plików** przez narzędzia agenta.
  Komenda (`npm install`, generator) może zmienić rzeczy poza śledzeniem — oznaczaj takie sesje
  jako „undo częściowy" i komunikuj to w UI.
- **UI po angielsku** (konwencja repo): „Review changes", „Plan first", „Undo to checkpoint".
- **Spójność WS↔REST:** diff w zatwierdzeniu i endpointy checkpoint/undo działają tak samo z
  `/agent/stream` (WS) i z REST `/permissions`/`/agent` — jeden mechanizm, jak dziś allowlist.

---

## 1. Backend (`grok_core/agent`)

### M13-B1 [P0] Generowanie diffa przy mutacji  — M
- **Cel:** każda mutacja pliku niesie czytelny, ujednolicony diff do zatwierdzenia.
- **Zakres:** w `tools.py` (lub helper `agent/diff.py`) przed zastosowaniem `write_file`/`edit_file`
  policz unified diff (stara treść vs nowa). Nowy plik → diff jako same dodania; (ew. usunięcie →
  same usunięcia). Pliki binarne → bez diffa, znacznik „binary changed" + rozmiar. Diff trafia do
  `PermissionGate` jako część żądania zatwierdzenia.
- **DoD:** każda operacja mutująca plik produkuje unified diff dostępny w przepływie zatwierdzenia;
  nowy plik pokazany jako pełne dodania; binarny obsłużony bez wysypki.
- **Selfcheck:** `agent_selfcheck.py` — diff generowany dla `write`/`edit`, poprawny dla nowego pliku,
  binarny → znacznik zamiast diffa.

### M13-B2 [P0] Tryb planowania (plan mode)  — M
- **Cel:** agent najpierw proponuje plan, nic nie zmieniając.
- **Zakres:** flaga sesji `plan` w `session.py` → dozwolone tylko narzędzia READONLY (reuse podziału);
  MUTATING odrzucane z czytelnym komunikatem („blocked in plan mode"). Agent zwraca plan (kroki).
  Akcja „approve plan" → przełączenie sesji w tryb wykonania (te same narzędzia, bramka jak zwykle).
- **DoD:** w trybie plan `write`/`edit`/`run` są odmawiane; agent zwraca plan; po akceptacji sesja
  przechodzi w wykonanie; READONLY działa w obu trybach.
- **Selfcheck:** `agent_selfcheck` — MUTATING zablokowane w plan, dozwolone po przełączeniu;
  READONLY zawsze; plan nie tworzy checkpointu (bo nic nie zmienia).

### M13-B3 [P0] Checkpointy + undo  — M
- **Cel:** jednym kliknięciem wrócić do stanu sprzed sesji.
- **Zakres:** na starcie sesji utwórz checkpoint; przed pierwszą modyfikacją danej ścieżki kopiuj
  oryginał do `.grok/checkpoints/<session_id>/` + wpis w manifeście (ścieżka, hash, czy „utworzony").
  Undo: dla zmienionych — przywróć kopię (`atomic_write_text`); dla utworzonych — usuń. Wszystko przez
  `Workspace.resolve` (sandbox). Czyszczenie starych checkpointów (retencja).
- **DoD:** po sesji edytującej 3 pliki i tworzącej 1, „Undo" przywraca oryginały i usuwa utworzony;
  ścieżki nie wychodzą poza workspace.
- **Selfcheck:** `agent_selfcheck` — snapshot-przed-zapisem, poprawność restore (treść + usunięcie
  utworzonych), odrzucenie ścieżek spoza sandboxa, sesja z `run_command` oznaczona „undo częściowy".

### M13-B4 [P1] `GROK.md` — auto-pamięć projektu  — S
- **Cel:** stałe reguły projektu zawsze w kontekście agenta (odpowiednik CLAUDE.md/AGENTS.md).
- **Zakres:** na starcie sesji wczytaj `GROK.md` z (a) korzenia workspace i (b) globalnego `DATA_DIR`;
  wstrzyknij do system promptu (workspace dopisuje/nadpisuje globalny). UTF-8 + cap rozmiaru; brak
  pliku tolerowany.
- **DoD:** `GROK.md` w workspace wpływa na zachowanie agenta (np. „never touch /vendor").
- **Selfcheck:** `agent_selfcheck` — plik wczytany i wstrzyknięty, cap rozmiaru, brak pliku OK,
  workspace nadpisuje global.

### M13-B5 [P1] Spójne API: diff w zatwierdzeniu + checkpoint/undo  — S/M
- **Cel:** front ma jednolite wejście do nowych funkcji przez WS i REST.
- **Zakres:** żądanie zatwierdzenia (WS `/agent/stream`) niesie diff; REST `/permissions` analogicznie.
  Nowe trasy REST: `GET /agent/checkpoints`, `POST /agent/undo` (oraz event WS o utworzeniu checkpointu).
  Fail-closed token (P1-10); atomowe zapisy manifestu (jak `grok_permissions.json`, P1-11).
- **DoD:** undo działa z UI przez REST; modal zatwierdzenia dostaje diff przez WS; brak/zły token → 401.
- **Selfcheck:** `api_smoke.py` — trasy checkpoint/undo + enforcement tokenu; `agent_selfcheck` —
  manifest zapisywany atomowo.

---

## 2. Frontend (`desktop/src/renderer`)

### M13-F1 [P0] Modal zatwierdzenia z diffem  — L
- **Cel:** „Review changes" — kolorowy diff przed zastosowaniem.
- **Zakres:** rozbuduj istniejący UI zatwierdzenia (`PermissionGate` front) o render unified diff
  per plik z podświetleniem (**CodeMirror 6**, który już masz w `CodeEditor.tsx`); accept/reject
  per plik. „Always allow" zostaje. Pliki binarne → „binary changed", bez diffa.
- **DoD:** gdy agent chce edytować, modal pokazuje kolorowy diff; user akceptuje/odrzuca per plik.
- **Test:** Vitest (`desktop/test/`) — parsowanie diffa + zaznaczanie plików (czyste utile).

### M13-F2 [P0] Tryb planowania w UI  — M
- **Cel:** „Plan first" — zobacz plan zanim cokolwiek się zmieni.
- **Zakres:** przełącznik „Plan first"; plan renderowany jako checklista kroków; przycisk
  „Approve & run" przełącza w wykonanie; widoczna informacja, że mutacje są w planie wyłączone.
- **DoD:** włączenie Plan → agent zwraca plan → „Approve & run" go wykonuje.
- **Test:** Vitest — maszyna stanów plan→execute.

### M13-F3 [P0] Checkpointy + Undo w UI  — M
- **Cel:** widoczna oś checkpointów i jeden przycisk cofania.
- **Zakres:** lista/oś checkpointów sesji; „Undo to checkpoint"; wizualne potwierdzenie
  przywróconych/usuniętych plików; baner „partial undo" dla sesji z `run_command`.
- **DoD:** jedno kliknięcie przywraca stan; sesja z komendą jasno oznaczona jako częściowo cofalna.
- **Test:** Vitest — stan listy checkpointów.

### M13-F4 [P1] Edytor `GROK.md`  — S
- **Cel:** wygodna edycja reguł projektu.
- **Zakres:** podgląd/edycja `GROK.md` workspace (CodeMirror); zapis przez backend; podpowiedź, że
  zmiany wejdą od następnej sesji agenta.
- **DoD:** edycja + zapis → następna sesja podnosi reguły.
- **Test:** Vitest — minimalny (stan edytora/zapisu).

### M13-F5 [P1] Diff per hunk  — S/M
- **Cel:** ziarnistość — akceptuj część zmian w pliku, odrzuć resztę.
- **Zakres:** rozbuduj F1 z per-plik na per-hunk (zaznacz hunki → tylko zaznaczone trafiają do patcha).
- **DoD:** akceptuję część hunków, odrzucam resztę; zastosowane są tylko zaakceptowane.
- **Test:** Vitest — zaznaczenie hunków → wynikowy patch.

---

## 3. Kolejność i zależności

```
B1 (diff)  ──►  F1 (modal z diffem)  ──►  F5 (per-hunk)
B2 (plan)  ──►  F2 (plan w UI)
B3 (checkpoint/undo)  ──►  F3 (undo w UI)
B4 (GROK.md)  ──►  F4 (edytor)         [niezależne, tanie — można wpleść kiedykolwiek]
B5 (spójne API)  ── spina B1/B3 z WS+REST
```

- **Fundament + pierwszy „wow":** `B1→F1` (zatwierdzanie z diffem) i `B3→F3` (undo) — to one
  zdejmują strach: widzisz i cofasz to, co robi agent. To jest cały sens M13.
- `B2/F2` (plan) idzie równolegle — najtańsze ze wszystkich, bo masz już podział narzędzi.
- `B4/F4` (`GROK.md`) to mały, samodzielny kafelek — dobre na „rozgrzewkę" lub przerywnik.
- `F5` (per-hunk) to dopieszczenie F1 — wartościowe, ale po działającym diffie per-plik.

## 4. Definicja ukończenia M13 (całość)

1. Każda edycja agenta pokazuje **przeglądalny, kolorowy diff** przed zastosowaniem; accept/reject
   per plik (docelowo per hunk).
2. **Tryb planowania:** agent proponuje plan tylko z narzędziami READONLY; mutacje wyłączone do akceptacji.
3. **Undo** jednym kliknięciem przywraca pliki (i usuwa utworzone) do stanu sprzed sesji, sandbox-safe;
   sesje z `run_command` uczciwie oznaczone jako „undo częściowy".
4. **`GROK.md`** z workspace jest auto-wczytywany do kontekstu agenta.
5. WS i REST spójne; nowe trasy **fail-closed**; manifest zapisywany atomowo; `agent_selfcheck.py`
   rozszerzony; **81 dotychczasowych asercji M1/M5–M6 nadal przechodzi** (zero regresji hardeningu).

## 5. Otwarte pytania techniczne

- **Migracja modelu agenta na Responses API (M10-B1):** dziś agent prawdopodobnie woła
  `chat/completions` z `tools`; ten endpoint jest legacy. Ujednolicić ścieżkę agenta z
  `responses_client` z M10 — w ramach M13, czy osobno? (Rekomendacja: osobny, mały refactor po M10,
  by nie mieszać go z pracą nad zaufaniem.)
- **Checkpoint:** kopia plików (rekomendacja — bez zależności od git, cross-platform) vs shadow-git
  (`GIT_DIR` w `.grok/`, wydajniejsze przy wielu plikach, ale wymaga gita i nie brudzi repo usera).
  Można zacząć od kopii, dołożyć shadow-git gdy sesje robią się duże.
- **Ziarnistość undo:** per-sesja (M13) czy stos per-mutacja (później)? Stos = „cofnij ostatnią
  zmianę", ale więcej księgowania.
- **Skutki uboczne `run_command`:** undo plików ich nie cofnie. Czy w M13 wystarczy jasny baner
  „partial undo", czy chcesz później przechwytywać też zmiany plików robione przez komendy (trudne)?
- **Retencja checkpointów:** limit liczby/rozmiaru `.grok/checkpoints` + czyszczenie; dodać `.grok/`
  do sugerowanego `.gitignore` usera.
