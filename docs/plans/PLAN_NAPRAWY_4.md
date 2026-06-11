# PLAN_NAPRAWY_4.md — runda napraw #4 (po ANALIZA_PROGRAMU_2026-06-10)

> **Źródło:** [`docs/plans/ANALIZA_PROGRAMU_2026-06-10.md`](ANALIZA_PROGRAMU_2026-06-10.md).
> **Cel:** zamienić znaleziska analizy w wykonywalny, fazowy plan z dokładnymi `plik:linia`,
> krokami naprawy i **asercjami regresyjnymi** dla każdej pozycji.
> **Data:** 2026-06-11. **Gałąź robocza:** `m15-oss-crossplatform` (nie na `main`).
>
> **Weryfikacja przed planowaniem (16 agentów, każdy czytał *aktualny* kod):**
> wszystkie **84 znaleziska** przeszły rewizję na żywym drzewie (linie z analizy mogły się
> przesunąć; `caelo_core/genjobs.py` ma niezacommitowane zmiany; pozycje „do weryfikacji"
> potwierdzono). Wynik:
>
> | Priorytet | confirmed | partially | already-fixed | razem |
> |---|---|---|---|---|
> | **P1** | 10 | 0 | 0 | **10** |
> | **P2** | 39 | 2 | 1 | **42** |
> | **P3** | 31 | 1 | 0 | **32** |
> | **Razem** | 80 | 3 | 1 | **84** |
>
> Numeracja `P1-A…J` / `S31-*` / `P2-3.2-*` / `3.3-*` / `S34-*` / `S35-*` / `ROAD-*` jest
> lokalna dla tej rundy i zgodna z analizą; nie koliduje z `P0-1…P3-14` z rund 1–3.

---

## 0. Najważniejsze korekty względem analizy (efekt weryfikacji)

Analiza w kilku miejscach proponowała naprawę niepełną lub ryzykowną. **To są wiążące
poprawki dla wykonawcy** — nie implementuj „wprost z analizy" tam, gdzie poniżej jest inaczej:

1. **P1-A (traversal sid):** NIE waliduj przez *podnoszenie wyjątku* w `session_path()` —
   `load()` nie ma `try` wokół niego (→ 500), a headless `_resolve_session` woła
   `_session_path(...).exists()` (→ crash). **Zachowaj `session_path()` czyste** i waliduj
   per-funkcja: `load→{}`, `delete→False`, `save→no-op`. `_SID_RX` **skopiuj** literał
   z `skills/manager.py` (sessions.py jest celowo bez zależności — nie importuj skills).
2. **P1-B (deny na grep/glob):** NIE zmieniaj `targets_for_tool` (tani deny na argumentach
   ma zostać). Filtr nakładaj **na wynikach** w `grep`/`glob`/`list_dir`. Dla `list_dir`
   przeciekiem jest **nazwa wpisu** — `Read(secret/**)` NIE złapie gołego segmentu `secret`
   (matcher segmentowy), więc filtruj po własnej ścieżce wpisu i **udokumentuj**, że ukrycie
   katalogu wymaga reguły `Read(<dir>)`; nie rozszerzaj matchera. `grep` filtruj **per-plik**
   (taniej niż per-linia).
3. **P1-C (LSP short-read):** dołóż obsługę **EOF** (`b''` → `break`, nie pętla w nieskończoność).
   Nagłówek przez `readline()` **nie** jest zagrożony. **Mock `_lsp_mock_server.py` ma ten sam
   bug** i MUSI zostać poprawiony + emitować duże ciało, żeby test w ogóle wymusił short-read.
4. **P1-D (data-URI):** wybieramy lżejszą opcję — strip w `to_dict()` dla odpowiedzi, pełne
   `params` zostają w bazie (retry ich potrzebuje). Osobno: nowa `update_gen_job_status()`
   (UPDATE tylko statusu/artefaktów) zamiast pełnego `INSERT OR REPLACE` przy każdej zmianie;
   `submit`/`_reap_stale` **zostają** na pełnym upsert (wiersz musi istnieć przed UPDATE).
5. **P1-E (DATA_DIR):** nie ma jednego „spawn-site w `_smoke_common`" — `Popen` jest w **3**
   miejscach (`api_smoke.py`, `handshake_check.py`, `sidecar_smoke.py`); wspólny jest tylko
   helper temp-dir+env. Dopisz komentarz, że `caelo_core.spec` i `main/index.ts` **NIE**
   ustawiają `CAELO_CORE_DATA_DIR` (produkcja bez zmian).
6. **P1-G (busy):** osobnego `onerror` **nie ma** — `AgentConnection` kieruje błąd przez
   `ws.close()`→`onClose`. Reset w `onClose` MUSI być pod `busyRef.current`, inaczej spamuje
   info na każdym (re)connecie.
7. **P1-H (Retry):** dodaj też reset `searchActivity`. Strumień „w locie" **nie** trafia do
   złej rozmowy (handlery domykają send-time `convo`) — nie ruszaj ścieżki streamingu.
8. **P1-I (debounce):** sam flush w cleanup **nie** pokrywa twardego zamknięcia okna Electron —
   dołóż `pagehide`/`beforeunload`. Przy okazji domknij 2 P3 z tego pliku (`saveError`,
   StrictMode `deleteChat`).
9. **P1-J (mikrofon):** flaga `stopped` jest konieczna (w chwili `stop()` `this.stream` jest
   jeszcze `null`, więc `stop()` nie ma czego zatrzymać); reset `stopped=false` na górze
   `start()` (wzorzec reuse instancji).
10. **S34-e (bypass vs hooki):** **już bezpieczne** (`already-fixed`) — `pre_tool` hooki są
    niezależne od trybu i poprzedzają pominięcie bramki; `--permission-mode bypass` NIE omija
    `block-dangerous-commands`. Jedyne działanie: dopisać asercję regresyjną.

---

## Faza A — Runda P1 (przed publikacją) · 10 pozycji, wszystkie punktowe

Brak zmian architektury. Po fazie: **re-run wszystkich suit** + dopisane asercje regresyjne.
Kolejność dowolna (pozycje niezależne); P1-D i P1-E są warunkiem zielonego `api_smoke`.

### Backend

#### ✅ P1-A — Path traversal przez `sid` sesji agenta `[S]` — ZROBIONE (headless_check: 8 nowych asercji PASS)
- **Plik:** [`caelo_core/agent/sessions.py:37`](../../caelo_core/agent/sessions.py) (sinki: `load:74`,
  `save:112`, `delete:168`, `load_history:100`); wejścia: `routes/sessions.py:32,42`,
  `routes/agent.py:176` (WS `{"type":"session","id":…}`), `runner.py:221` (`_persist_session`),
  `headless.py` `-s/-r/-c`.
- **Ryzyko:** token-gated **odczyt/usunięcie/nadpisanie** dowolnego `*.json` poza
  `DATA_DIR/sessions` (np. `caelo_settings.json`, `caelo_auth.json`) — `..\..\` na Windows
  wychodzi z katalogu; nadpis przez resume→`_persist_session`.
- **Naprawa:** dodać `_SID_RX = re.compile(r"^[A-Za-z0-9_-]{1,64}$")` + `valid_id()`;
  **`session_path()` zostaje czyste**, walidacja per-funkcja: `load→{}`, `delete→False`,
  `save→log+return`. REST/WS/headless dziedziczą (już zwracają 404/„not found" na pustce).
  `token_urlsafe(8)` = `[A-Za-z0-9_-]`, więc `{1,64}` nie odrzuca żadnego realnego id.
- **Test:** `tools/headless_check.py` — sentinel `caelo_settings.json` nietknięty po
  `save('..\\..\\caelo_settings', …)`; `load('../../caelo_auth')=={}`; `delete(...)==False`;
  poprawny id robi round-trip.

#### ✅ P1-B — Reguły `deny` nie chronią treści przed `grep`/`glob`/`list_dir` `[M]` — ZROBIONE (agent_selfcheck: 3 nowe asercje PASS; `rule_filter` w grep/glob/list_dir)
- **Plik:** [`permission_rules.py:147`](../../caelo_core/agent/permission_rules.py) (mapowanie),
  egzekucja [`session.py:560`](../../caelo_core/agent/session.py), executory
  [`tools.py:182,193,227`](../../caelo_core/agent/tools.py) (`grep` zwraca treść linii :269).
- **Ryzyko:** `deny Read(secret/**)` nie powstrzyma `grep("API_KEY", ".")` (zwraca dopasowane
  linie z `secret/`) ani `glob`/`list_dir` (nazwy). „deny>allow" obchodzialne dla narzędzi
  przeszukujących.
- **Naprawa:** w `session.py` zbudować **raz na wywołanie** domknięcie
  `deny_path = lambda rel: self.gate.evaluate_rules("read_file", {"path": rel})=="deny"`
  (tylko gdy `not ruleset.empty` i narzędzie z `{grep,glob,list_dir}`; inaczej `None` =
  zero kosztu). Przekazać jako `rule_filter` do `execute_tool`→executorów; `grep` filtruje
  **per-plik** (przed czytaniem), `glob`/`list_dir` po `rel` wyniku. **Nie ruszać**
  `targets_for_tool`. Udokumentować, że ukrycie katalogu w `list_dir` wymaga `Read(<dir>)`.
- **Test:** `tools/agent_selfcheck.py` `test_permission_rules` (fixtura `secret/k.txt`
  „TOPSECRET") — 3× check: grep nie zwraca treści/ścieżki, glob pomija ścieżkę, list_dir
  ukrywa wpis. Zaktualizować łączną liczbę checków.

#### ✅ P1-C — LSP: short-reads psują ramkowanie Content-Length `[S]` — ZROBIONE (lsp_check: 256 KB ciało PASS; mock też naprawiony)
- **Plik:** [`lsp/client.py:177`](../../caelo_core/lsp/client.py) (`out.read(length)` na pipe
  `bufsize=0`); ten sam bug w mocku [`tools/_lsp_mock_server.py:27`](../../caelo_core/tools/_lsp_mock_server.py).
- **Ryzyko:** duże ciała (diagnostyki, `hover`) obcięte → `json.loads` pada → ciche gubienie
  `publishDiagnostics`, timeouty `_request` po 15 s.
- **Naprawa:** `_read_exact(stream, n)` doczytujące do `n`, **`b''`→zwróć partial, caller robi
  `break`** (zachowuje „reader kończy na EOF"). Nagłówek (`readline()`) bez zmian. Poprawić mock
  **i** kazać mu emitować ciało >256 KB do testu.
- **Test:** `tools/lsp_check.py` `test_large_body_framing()` — `documentSymbol` z polem
  `pad="x"*262144`; assert pełna rekonstrukcja (`len(pad)==262144`). Bez fixu → timeout 15 s.

#### ✅ P1-D — GenJob: data-URI w `params` (82 MB na `GET /genjobs`) + write-amp `[M]` — ZROBIONE (genjobs_check: 5 nowych asercji PASS; `to_dict(full=)` + `update_gen_job_status`)
- **Plik:** [`genjobs.py:105`](../../caelo_core/genjobs.py) (`to_dict`), `:294`/`:301` (`_set`/
  `_persist`); [`routes/genjobs.py:127`](../../caelo_core/routes/genjobs.py) (lista +
  `:101/149/167/180`); [`history_store.py:678`](../../caelo_core/history_store.py)
  (`upsert_gen_job` = `INSERT OR REPLACE` pełnego wiersza przy każdej zmianie statusu).
- **Ryzyko:** `GET /genjobs` = dziesiątki MB na tick pollingu → reset połączenia → **FAIL
  `api_smoke`**; baza puchnie pod lockiem.
- **Naprawa:** `to_dict(full=False)` — domyślnie strip kluczy `images/image/video` z `data:`
  na placeholder `<data-uri N bytes omitted>`; `full=True` (executor/retry) bez zmian. Wszystkie
  route'y już wołają `to_dict()` bezarg → automatycznie chude. Retry czyta pełny wiersz z bazy
  (`from_row`) — bez zmian. Write-amp: nowa `update_gen_job_status()` (UPDATE statusu/
  `artifact_ids`/`error`/`updated_at`); `_set`→`_persist_status`; `submit`/`_reap_stale`
  zostają na pełnym upsert.
- **Test:** `tools/genjobs_check.py` `_unit_blob_stripping` — lista bez pól >1 KB; `full=True`
  zwraca realne bajty; `retry` zachowuje oryginalny ref; po stanie terminalnym `params` w bazie
  nietknięte.

#### ✅ P1-E — Self-checki na realnym `DATA_DIR` użytkownika (grożą `DELETE /genjobs`) `[S]` — ZROBIONE (`api_smoke` znów ZIELONY; izolacja 3× spawn + override config; bonus: naprawiona izolacja OAuth w `_unit_settings_ownership`)
- **Plik:** [`config.py:50`](../../config.py) (brak env-override); spawn z `cwd=REPO_DIR`:
  `tools/api_smoke.py:82`, `tools/handshake_check.py:58`, `tools/sidecar_smoke.py:65`;
  destrukcja `tools/smoke_media.py:412` (`DELETE /genjobs`).
- **Naprawa:** w `config.py` `CAELO_CORE_DATA_DIR` env-override **przed** gałęzią `IS_FROZEN`
  (wszystkie stałe pochodne dziedziczą). Helper `_isolated_env(token)` w `_smoke_common.py`
  (`mkdtemp` + env) wstrzykiwany w **3** miejscach `Popen`; `rmtree` w `finally`. Komentarz:
  spec/Electron NIE ustawiają tej zmiennej.
- **Test:** `smoke_core.py` `_unit_data_dir_override` — `reload(config)` po ustawieniu env →
  `config.DATA_DIR==tmp and SETTINGS_FILE.parent==tmp`; w `api_smoke.main()` assert, że żywy
  sidecar nie używa `REPO_DIR`.

### Frontend

#### ✅ P1-F — Martwe linki w markdownie modelu `[S]` — ZROBIONE (Markdown.test.tsx PASS)
- **Plik:** [`Markdown.tsx:42`](../../desktop/src/renderer/src/components/Markdown.tsx) (brak
  override `a`); blokada [`main/index.ts:397`](../../desktop/src/main/index.ts) `will-navigate`.
- **Naprawa:** dodać `components={{ a: ({children,...rest}) => <a {...rest} target="_blank"
  rel="noreferrer">{children}</a> }}`. `target=_blank` → `setWindowOpenHandler`→`shell.openExternal`
  (ta sama ścieżka co działające cytowania); bez nowego IPC, bez zmian w main.
- **Test:** nowy `desktop/test/components/Markdown.test.tsx` — render `[example](https://…)`,
  assert `href`+`target=_blank`+`rel~=noreferrer`.

#### ✅ P1-G — `busy` nie resetuje się po padzie WS agenta `[S]` — ZROBIONE (busyRef+onClose reset; agentClient.test.ts pilnuje funnela onerror→close→onClose)
- **Plik:** [`AgentPanel.tsx:218`](../../desktop/src/renderer/src/components/code/AgentPanel.tsx)
  (`onClose`), reset busy tylko na done/stopped/error (`:358`); `agentClient.ts:253` (`onclose`).
- **Naprawa:** `busyRef` lustrzany do `busy`; w `onClose` jeśli `busyRef.current`: `setBusy(false)`
  + wyczyść `curAssistant`/plan + `pushInfo('Connection to the agent was lost…','warn')`. Guard na
  `busyRef` (inaczej spam przy reconnect). Bez `onError` (błędy idą przez `onClose`).
- **Test:** `AgentPanelRecovery.test.tsx` — stub WebSocket; po `triggerClose()` w stanie busy:
  znika „Stop", wraca „Send", widać komunikat.

#### ✅ P1-H — „Retry" pisze do złej rozmowy `[S]` — ZROBIONE (efekt resetu error/searchActivity/lastTurnRef na zmianę activeId; useConversations.test.tsx pilnuje scoping patchActive)
- **Plik:** [`ChatView.tsx`](../../desktop/src/renderer/src/components/ChatView.tsx) `error:372`,
  `lastTurnRef:394`, retry `:594`, pasek `:967`.
- **Naprawa:** jeden efekt `useEffect(() => { setError(null); setSearchActivity(null);
  lastTurnRef.current=null }, [convo.activeId])`. **Nie** ruszać ścieżki streamingu (in-flight
  jest poprawny).
- **Test:** `ChatView.test.tsx` — po `onError('boom')` widać pasek+Retry; po zmianie `activeId`
  pasek i Retry znikają.

#### ✅ P1-I — Debounce zapisu rozmów gubi ostatnią turę `[S]` — ZROBIONE (flush-on-unmount + pagehide/beforeunload; +saveError clear +deleteChat StrictMode; useConversations.test.tsx PASS)
- **Plik:** [`useConversations.ts:42`](../../desktop/src/renderer/src/lib/useConversations.ts)
  (cleanup robi `clearTimeout` bez flush); `saveError` nieczyszczone `:46`; `deleteChat` `:68`.
- **Naprawa:** wydzielić `flush()` (z gałęzią `setSaveError(null)` na sukces); cleanup =
  `clearTimeout(t); flush()`; dodać `pagehide`/`beforeunload` → `saveConversations(convos)`
  (cleanup efektu nie odpala się przy twardym zamknięciu okna). Domknąć 2 P3: `saveError`
  czyszczone na sukces; `deleteChat` — `setActiveId` **poza** updaterem `setConvos` (StrictMode).
- **Test:** `useConversations.test.tsx` (`renderHook`) — `patchActive(...)` bez upływu 800 ms,
  `unmount()`, assert `localStorage` ma „unsaved turn".

#### ✅ P1-J — Wyścig `MicCapture.start()/stop()` zostawia żywy mikrofon `[S]` — ZROBIONE (flaga `stopped` na obu await; voice.test.ts wyścig PASS)
- **Plik:** [`audioStream.ts:80`](../../desktop/src/renderer/src/lib/audioStream.ts) — guard po
  `addModule`, **brak** po `await getUserMedia`.
- **Naprawa:** pole `stopped`; `stop()` ustawia `stopped=true` jako 1. instrukcja; po
  `getUserMedia` jeśli `stopped` → zatrzymaj świeże tracki + `stream=null` + `return false`;
  reset `stopped=false` na górze `start()` (reuse instancji).
- **Test:** `desktop/test/voice.test.ts` — stub `getUserMedia` (deferred) + `AudioContext` spy;
  `start()`→`stop()`→resolve; assert `start()===false`, track.stop wołany 1×, `AudioContext`
  nigdy nie zbudowany.

**Domknięcie Fazy A — ✅ ZROBIONE (2026-06-11):** wszystkie 10×P1 wdrożone i zielone.
- **Backend (13 suit standalone, venv bez pytest — TLS):** `handshake · agent_selfcheck ·
  history · genjobs · mcp 36/36 · packages 48/48 · headless · acp · lsp · sandbox 29/29 ·
  embeddings 11/11 · crossplatform 23/23 · api_smoke` — **wszystkie OK**. **`api_smoke` znów
  ZIELONY** (był FAIL — B-1/B-2 zamknięte).
- **Frontend:** `npm test` **197/197**, `npm run typecheck` czysty, `npm run lint` bez nowych
  ostrzeżeń (2 istniejące w `Image.tsx`/`Video.tsx`, nietknięte).
- **Dopisane asercje regresyjne:** traversal `sid` (headless_check ×8), deny-na-wynikach grep/
  glob/list_dir (agent_selfcheck ×3), short-read LSP 256 KB (lsp_check + mock), strip blobów +
  write-amp (genjobs_check ×5), override `DATA_DIR` + izolacja OAuth (smoke_core/api_smoke),
  oraz 5× front (Markdown, agentClient funnel, useConversations flush+scoping, voice/MicCapture
  race).
- **Uwaga:** `caelo_core/genjobs.py` ma teraz zmiany P1-D obok niezacommitowanych stawek
  per-model — do zacommitowania razem z fixem kosztu `video/edit` w **Fazie B** (ROAD-3.6-d).

---

## Faza B — Publikacja (wg SWOT największe ryzyko) · ściśle uporządkowana

Kolejność jest **własnością bezpieczeństwa** (scan-before-public nieprzekraczalny).

1. ⬜ **ROAD-3.6-a** `[S]` — utworzyć **remote** (prywatny) na GitHub, wypchnąć
   `m15-oss-crossplatform` + `main`. **Sama obecność remote zdejmuje ryzyko jedynej kopii na
   jednym dysku.** Pierwszy realny bieg `ci.yml` (3×OS), naprawić środowiskowe zgrzyty.
2. ⬜ **ROAD-3.6-d** `[S]` — zacommitować niezacommitowane stawki per-model w
   [`genjobs.py`](../../caelo_core/genjobs.py) **razem z fixem** kosztu `video/edit|extend`
   (`:74` używa `duration=6` bezwarunkowo; dla edit/extend wynik zachowuje długość źródła).
   Test: `genjobs_check` — `estimate_cost('video','edit',{źródło>6s})` ≠ `rate*6`.
   Zostawić `estimate_cost` czyste (bez importu `api_manager`/`state`).
3. ⬜ **ROAD-3.6-e** `[S]` — zdecydować los `files/` (→ `assets/brand/` zgodnie z
   `caelo-brand-assets`, lub `.gitignore`); zacommitować `docs/guides/USER_GUIDE.md` +
   `docs/README.md`.
4. ⬜ **ROAD-3.6-b** `[S]` — **gitleaks na PEŁNEJ historii** (wszystkie commity/gałęzie) PRZED
   upublicznieniem. Znaleziska → `filter-repo` + rotacja sekretu. Public dopiero po czystym wyniku.
5. ⬜ **ROAD-3.6-f** `[S]` — `pip install -r requirements-dev.txt` w venv (na maszynie usera /
   z zaufanym CA korpo — pułapka TLS) → `pytest caelo_core/tests -v` zielone; wpiąć krok pytest
   w CI. Domyka `0.4` z `PLAN_WERYFIKACJI_LIVE`.
6. ⬜ **ROAD-TOP2 / ROAD-3.6-c** `[S/M + M]` — `electron-updater` + GitHub Releases jako kanał
   aktualizacji; **podpisywanie** powłoki Electron i exe sidecara (kandydat: Azure Trusted
   Signing); sekrety w `release.yml`. DoD: podpisany instalator oferuje auto-update, SmartScreen
   nie ostrzega. **Zależność:** po ROAD-3.6-a.

---

## Faza C — Dokończenie weryfikacji LIVE

Z [`PLAN_WERYFIKACJI_LIVE.md`](PLAN_WERYFIKACJI_LIVE.md) (sandbox blokuje xAI/exec — robi user):
sekcje **D** (głos), **F** (subagenci), **G** (MCP/headless/ACP/LSP), **H** (funkcje-widma —
decyzja włącz/usuń), **I** (pakiety), **J** (cross-platform), **K** (terminal). Pozycje
oznaczone niżej `needs-live-check` (np. realny short-read LSP, realny DNS-rebinding `web_fetch`)
potwierdzić przy okazji właściwej sekcji.

---

## Faza D — Runda P2 „współbieżność i odzysk" (backend)

Dwa motywy z analizy: **wyścigi na szwach async+workery** i **ścieżki odzysku traktujące błąd
I/O jak korupcję**. Bazą jest jeden wzorzec lazy-init-z-lockiem (jak `history_store.get_store()`).

### D.1 Współbieżność (parasol: ROAD-4.1-a)

| ID | Plik:linia | Naprawa (1 zdanie) | Test | Eff |
|---|---|---|---|---|
| ⬜ **S31-c** | `state.py:378` (+`:180,343,389,475,486,496,516`) | `self._lazy_lock=RLock` + helper double-checked (jak `get_store()`) dla genjobs/mcp/hooks/commands/skills/packages/memory/lsp — **kluczowe**: drugi `GenJobManager._reap_stale` psuje zadania pierwszego | `smoke_core` `_unit_lazy_init_race` (16 wątków → 1 instancja) | M |
| ⬜ **S31-a** | `genjobs.py:191/269/294` + `backend_media.py:49` | `cancel()` re-czyta status **pod lockiem**; `_run_image_job` honoruje `cancel.is_set()` (przed i po blokującym POST) → `cancelled` zamiast `done` | `genjobs_check` `_unit_cancel` (executor blokujący) | M |
| ⬜ **S31-b** | `genjobs.py:227` | `clear_finished()` — sekcja prune dictów `_cancel`/`_finished` pod `self._lock` (serializacja vs `submit`) | `genjobs_check` `_unit_clear_race` | S |
| ⬜ **S34-a** | `mcp/manager.py:272` | `start_server`: zbiór `_starting` pod lockiem (idempotencja tego samego sid), `srv.start()` poza lockiem w `try/finally` | `mcp_check` `test_concurrent_start` (Barrier, licznik=1) | M |
| ⬜ **S34-b** | `lsp/manager.py:47` | `_ensure` cały pod `RLock` (check-and-create atomowe) — bez podwójnego spawnu przy równoległych subagentach | `lsp_check` `test_concurrent_ensure` | M |
| ⬜ **3.3-b** | `team.py:428` | ścieżka worktree `run-{pid}-{uuid}-{seq}/{agent_id}` — koniec kolizji między równoległymi `TeamManager` (dwa okna / WS+headless) | `agent_selfcheck` `test_worktree_path_isolation` (wspólny base) | S |
| ⬜ **3.3-c** | `team.py:534` (+`:153,220`) | subagent po timeout/stop **nie rejestruje merge** (`_cleanup_worktree`); osierocone wątki oznaczone `timeout` w raporcie; potwierdzić skończony `timeout` w `llm.stream_*` | `agent_selfcheck` `test_team_timeout_no_late_merge` | M |
| ⬜ **3.3-d** | `roles.py:386` | `RoleRegistry._lock=RLock` wokół read/write (`_save` pod lockiem — koniec „dictionary changed size") | `agent_selfcheck` `test_role_registry_thread_safety` | S(P3) |
| ⬜ **S31-m** | `history_manager.py:23` | `self._lock` wokół mutacja+`_persist` (wołane z workerów genjobs+czatu) — bez lost-update | `smoke_core` `_unit_history_manager_concurrency` | S |
| ⬜ **RMW settings** | `state.py:242` | lock read-modify-write na `caelo_settings.json` (`update_settings`) — w tej samej rundzie (nota cross-item §3.1) | dorzucić do `_unit_settings_ownership` | S |

### D.2 Odzysk / zbyt szerokie `except` (chronią przed utratą danych, same ją powodują)

| ID | Plik:linia | Naprawa | Test | Eff |
|---|---|---|---|---|
| ⬜ **S31-d** | `history_store.py:182` | wąsko: tylko `malformed`/`not a database`/`encrypted` → `.corrupt`; `OperationalError("database is locked")` re-raise (zdrowa baza nie ginie) | `history_check` `_unit_open_locked` | S |
| ⬜ **S31-e** | `config.py:244` | `except OSError` → default **bez** ruszania pliku; korupcja = tylko `ValueError/JSONDecodeError` | `smoke_core` `_unit_json_corrupt_backup` (OSError nie psuje) | S |
| ⬜ **S31-f** | `oauth_manager.py:164` | `print()`→`log.info` (stderr) — kontrakt „stdout=handshake" | `smoke_core` assert: brak stdout / `inspect.getsource` bez `print(` | S |
| ⬜ **S31-g** | `oauth_manager.py:124,219,291` | `Lock`→`RLock`; mutacje tokenów pod lockiem; **backoff** po nieudanym refreshu (`_refresh_fail_until`) | `smoke_core` `_unit_oauth_concurrency` (backoff: 2. wywołanie nie sieciuje) | M |

### D.3 Bezpieczeństwo / limity routów i agenta

| ID | Plik:linia | Naprawa | Test | Eff |
|---|---|---|---|---|
| ⬜ **P2-3.2-b** | `system.py:32` + `history.py:139` | walidacja `output-dir` (istniejący katalog, nie-root) **przed** `set_save_path`; `_media_bases()` odrzuca bazę=root (DiD) — zamyka poszerzanie sandboxa `/artifacts` na `C:\` | `smoke_routes` `_unit_history_routes` (root→400; konsument→403) | M |
| ⬜ **P2-3.2-e** | `chat.py:213`, `voice.py:185,321`, `agent.py:137` | nowy `errors.masked_error(exc,public)`; ramki WS `{"type":"error"}` maskują surowy `str(exc)` (URL-e `api.x.ai`/ścieżki) jak REST | `smoke_chat` (sentinel `api.x.ai` nie wycieka) | M |
| ⬜ **P2-3.2-d** | `validation.py` + `chat.py:242`, `voice.py:266` | `validate_ws_messages` (MAX 200 / 200 KB / re-use limitów URI); WS waliduje jak REST, błąd = ramka, pętla trwa | `smoke_chat` (oversize → error, brak `done`) | M |
| ⬜ **3.3-a** | `tools.py:164` + `workspace.py:24` | `read_file` cap `READ_FILE_MAX_BYTES` (~16 MB); `Workspace.resolve` odrzuca urządzenia `CON/PRN/AUX/NUL/COM*/LPT*` (na **komponentach przed** `resolve()`) — koniec wieszania wątku na `read_file("CON")` | `agent_selfcheck` device-name (gate `os.name=='nt'`) + cap rozmiaru | M |
| ⬜ **3.3-g** | `tools.py:511,550` | `web_fetch` rozwiązuje host (`getaddrinfo`) i sprawdza **wynikowe IP** (loopback/private/link-local) pre-flight i po redirect — koniec DNS-rebindingu (literalny filtr zostaje) | `agent_selfcheck` `test_web_fetch` (host→10.0.0.5 = `refused`) | M |
| ⬜ **S31-j** | `backend_media.py:173` | `_download_media`: `allow_redirects=False` **i** re-walidacja `urlparse(r.url).scheme=='https'` — koniec ominięcia https→http | `genjobs_check` (redirect→`ValueError`) | S |
| ⬜ **S31-l** | `hooks.py:204,56` | `block-dangerous-commands` **fail-closed** na timeout/błąd regexa; domknąć wzorce `git push -f`, `rd /s`, `del /f` | `agent_selfcheck` (fail-closed + 3 wzorce blokowane) | M |
| ⬜ **P2-3.2-a** | `agent_api.py:71` | `PUT /agent/caelo-md` egzekwuje `MAX_CAELO_MD_BYTES` (`Field(max_length=…)` + check bajtów) | `smoke_routes` `_unit_agent_api_routes` | S |
| ⬜ **P2-3.2-c** | `fs.py:99` | `GET /fs/read` cap rozmiaru (413) — koniec OOM na wielkim pliku | `smoke_routes` (oversize→413) | S |
| ⬜ **S34-c** | `packages/manager.py:660` + `Marketplace.tsx:199` | TOCTOU karty zgody: `inspect_from_url` zwraca `fetched_b64`; GUI instaluje **te bajty** (`data_b64`), nie re-fetch URL | `packages_check` `test_inspect_install_same_bytes` | M |

### D.4 Poprawność / dane (P3 backendu)

| ID | Plik:linia | Naprawa | Test | Eff |
|---|---|---|---|---|
| ⬜ **S31-i** | `responses_client.py:386,410` | `usage` **sumowane** przez tury pętli narzędzi; ostatnia iteracja `max_tool_iters` **nie** wykonuje narzędzi „w próżnię" (break przed egzekucją) | `smoke_chat` `_unit_responses_mcp_loop` | M |
| ⬜ **S31-h** | `state.py:321` | `is_authenticated()` = `active_auth_source()!='none'` (respektuje twardy przełącznik) | `smoke_core` (oczekiwany false przy `oauth` bez logowania) | S |
| ⬜ **S31-k** | `state.py:614` + `history.py:163` | `delete_project` kasuje też **pliki** mediów (przez wspólny sandbox media-bases; wydzielić `_media_bases/_within`) | `history_check` `_unit_delete_project_files` (anti-traversal) | M |
| ⬜ **3.3-e** | `runner.py:179` | flaga `ran` — `record_event` w `finally` pomija turę bez workspace (koniec pustych „code" eventów) | `headless_check` (brak eventu bez ws) | S |
| ⬜ **3.3-f** | `tools.py:452` | reconcyliacja etykiety `[timeout]` z `returncode==0` — koniec fałszywego timeoutu przy szybkim exit | `agent_selfcheck` `test_run_command_no_false_timeout` | S |
| ⬜ **P3-3.2-f** | `_ws.py:31` | **rekomendacja: bez zmian** (inwariant trzyma — kosmetyka zasobów); ewentualnie `_closing` skraca `emit()` na zamknięciu (NIE podnosić `JOIN` ponad `EMIT`) | tylko jeśli zmiana | S |
| ⬜ **S34-e** | — | **already-fixed**: dopisać asercję, że `bypass` nie omija `pre_tool`/`block-dangerous-commands` | `agent_selfcheck` (bypass + groźna komenda = block) | S |

---

## Faza E — Frontend P2/P3 (sekcja 3.5) + wspólny kanał błędów

**Najpierw** wspólny prymityw błędów (ROAD-4.1-d), bo absorbuje 3 pozycje:

#### ⬜ ROAD-4.1-d — Jeden toast/status-line `[M]`
Nowy `components/ui/Toast` (wzór: pasek z ChatView). Przepiąć przez niego: **S35-e**
(`useWorkspace` Ctrl+S/openFile/selectWorkspace cisza → `lastError`/`onError`), **S35-j**
(`useDictation` odmowa mikrofonu / błąd STT — 2× `catch{}`), **S35-h** (`attachments` —
odrzucone pliki z powodem `too-large|binary`). Likwiduje „klasę cichych porażek". Testy:
`useWorkspace.test.tsx`/`useDictation.test.tsx`/`attachments.test.ts` (jsdom) + render toastu.

Pozostałe S35 (niezależne):

| ID | Plik:linia | Naprawa | Test | Eff |
|---|---|---|---|---|
| ⬜ **S35-a** | `serverState.ts:163` | write-through cache dla wszystkich pól `SettingsPatch` (effort/search/voice) — koniec cofania po remount | `serverState.test.ts` (pure `mergeSettings`) | S |
| ⬜ **S35-c** | `useTts.ts:32` | epoka `reqRef` — dwa szybkie „Read aloud" = ostatni wygrywa (koniec 2 audio naraz) | `useTts.test.tsx` (play 1×) | S |
| ⬜ **S35-d** | `Terminal.tsx:8` | `ResizeObserver` (refit przy separatorze), initial `resize` na `onopen` (pty ≠ 80×24), live theme przez `term.options.theme` (bez recreate WS) | `termTheme` pure + grep `ResizeObserver`/`onopen…resize` | M |
| ⬜ **S35-f** | `main/index.ts:249` | zepsuty handshake JSON → `killCoreForRestart` (jak `verifyConnection:188`) + czyszczenie watchdoga; koniec osieroconego sidecara | extract `onHandshakeLine` + test `killSpy` | S |
| ⬜ **S35-i** | `ChatView.tsx:447`, `AgentPanel.tsx:250` | stick-to-bottom + „Jump to bottom" (wspólny `useStickToBottom`); **zachować** wymuszony scroll karty approval (commit 23b64c4) | `stickToBottom.test.ts` (`isNearBottom`) | M |
| ⬜ **S35-k** | `CodeEditor.tsx:9,31` | `useMemo(() => langFor(path), [path])` — koniec rekonfiguracji CM6 na każdy znak | `CodeEditor.test.tsx` (stała referencja przy zmianie value) | S |
| ⬜ **S35-l** | `api.ts:1291` (+`agentClient.ts`) | `stop()` w CONNECTING zamyka socket (`ws.close()`) + guard w `onopen` — koniec tury mimo Stop | `streamChat.test.ts` (close wołany, brak ramki `chat`) | S |
| ⬜ **S35-b** | `Settings.tsx:230` | `text-warning`→`text-warn` (token istnieje) | `styleTokens.test.ts` (grep) | S |
| ⬜ **S35-g** | `useConversations.ts:42,68` | (domknięte w **P1-I**) `saveError` czyszczone na sukces; `setActiveId` poza updaterem | w `useConversations.test.tsx` | S |
| ⬜ **S35-m** | `CommandPalette.tsx`, `Extensions.tsx`, `AgentPanel.tsx:764`, `ChatView.tsx:983` | A11y: focus-trap+`combobox/listbox` (port z `Popover`), taby `tablist/tab/tabpanel`, dropdowny slash/@ `listbox/option`+`aria-activedescendant` | `CommandPalette.test.tsx`/`Extensions.test.tsx` (role) | M(P3) |

---

## Faza F — Drobne P3 / higiena (sekcja 3.4 minor)

| ID | Plik:linia | Naprawa | Test | Eff |
|---|---|---|---|---|
| ⬜ **S34-d** | `sandbox/wrap.py:116` (+nowy `routes/sandbox.py`) | pokazać w UI „OS sandbox unavailable on Windows" (`sandbox_availability()` + `GET /sandbox/status`); zachowanie `wrap()` bez zmian (fail-open intencjonalny) | `sandbox_check` `test_availability` | M |
| ⬜ **S34-f-1** | `mcp/client.py:129` + `lsp/client.py:177` | cap długości linii stdout MCP (`MAX_MCP_LINE_BYTES`) + clamp absurdalnego `Content-Length` | `mcp_check`/`lsp_check` | S |
| ⬜ **S34-f-2** | `lsp/client.py:129` | `stop()` daje okno `wait(timeout=2)` przed `_tree_kill` (jak MCP) | `lsp_check` (czysty exit) | S |
| ⬜ **S34-f-3** | `lsp/manager.py:56` | reset `_restarts` po stabilnym biegu (próg czasu, nie „każdy start") — koniec trwałej śmierci serwera | `lsp_check` `test_restart_budget_resets` | S |
| ⬜ **S34-f-4** | `sandbox/wrap.py:65` + `profiles.py:81` | `--tmpfs /tmp` w strict (bwrap) + reguła `/tmp` w seatbelt — kompilatory/git działają pod strict | `sandbox_check` (`--tmpfs` w argv) | S |
| ⬜ **S34-f-5** | `packages/manager.py:133` + `hooks.py:261` | `datetime.now(timezone.utc)` — sortowalne, forensyka audytu | `packages_check` (tz-aware) | S |

---

## Faza G — Nowe funkcje wg TOP-10 (po stabilizacji)

Zaczynać od pozycji `S` (gotowa infrastruktura). Każda z **definicją „done"** z analizy.

| # | Funkcja | Eff | Reuse / DoD | Zależności |
|---|---|---|---|---|
| ⬜ **TOP1** | `web_search` jako narzędzie agenta | S | live-search z `responses_client` istnieje; eksponować w `tools.py` (READONLY, bez bramki) → agent dostaje cytowane wyniki | — |
| ⬜ **TOP3** | Widżet planu/TODO agenta | S | ramki `WsStream` + render `AgentPanel`; live checklist mid-run | — |
| ⬜ **TOP2** | Auto-update + code signing | S/M+M | = Faza B krok 6 (publikacja) | ROAD-3.6-a |
| ⬜ **TOP4** | Katalog MCP one-click | S/M | maszyneria M16 (inspect/install+consent) + `McpManager`; install ≠ autostart | M16/M14 |
| ⬜ **TOP5** | Artefakty HTML/mermaid/SVG (sandbox iframe) | M | CSP już jest; `Markdown.tsx` fenced→`ArtifactFrame`; pairuje z P1-F | — |
| ⬜ **TOP6** | Recenzja PR przez `gh` | M | `/review` + `run_command` + skill `pr-babysit`; mutacje przez bramkę | `gh` u usera |
| ⬜ **TOP7** | Rewind/edycja wiadomości czatu | M | lokalny `useConversations`; **po P1-H i P1-I** | P1-H, P1-I |
| ⬜ **TOP8** | Inline Ctrl-K w CodeMirror | M | CM6 decoration API; przy okazji `langFor` useMemo (S35-k) | — |
| ⬜ **TOP9** | Auto-pamięć użytkownika | M | M19-B8 embeddings/`memory.py` istnieją; brak ekstrakcji+UI (opt-in!) | M19-B8 |
| ⬜ **TOP10** | Lokalne background-agents + powiadomienia | M+S | headless B1 + kolejka genjobs + worktree M17 + Notification API; powiadomienia to szybki sub-win | B1/M17 |

**Strategicznie #1 długoterminowo (poza TOP-10):** ⬜ **ROAD-4.2-a** `[M/L]` — inni dostawcy
LLM / modele lokalne przez `base_url`-override w cienkim `responses_client` (mitygacja ryzyka
single-provider xAI; **nie** restrukturyzować root `api_manager.py`).
**Tuż za podium (ROAD-4.2-b):** pętla test-and-fix (post_tool), `.caeloignore`, onboarding.
**Świadomie NIE teraz:** tab-autocomplete (brak FIM u xAI), multi-root (serce sandboxa P0),
chmurowe agent-runnery (sprzeczne z local-first).

### Motywy inżynierskie 4.1 (przekrojowe, do wpięcia w fazy)
- ⬜ **4.1-a** współbieżność jako runda → **Faza D.1**.
- ⬜ **4.1-c** odporność: retry `poll_video_status` (1 timeout = utrata płatnego wideo), `fsync`
  przed `os.replace` dla `caelo_auth.json`/`caelo_settings.json`, `Backend.shutdown()` domyka
  genjobs/history_store (checkpoint WAL), tolerancja wieloliniowych `data:` w SSE. `[M]`
- ⬜ **4.1-b** wydajność gorących ścieżek: cache `_resolve_auth` (inwalidacja na zapis settings),
  kNN poza lockiem, `compute_changes` przez `os.stat`, prune `dirnames` w `glob`, memo `EntryView`. `[M]`
- ⬜ **4.1-e** API: realne `total` (COUNT), `total_cost` przez SUM, rozróżnienie 4xx w `packages._err`. `[S]`
- ⬜ **4.1-f** `/genjobs` przez WS-push (hook `on_update` istnieje, nieużyty) — **po P1-D**. `[M]`

---

## 5. Rekomendowana kolejność (skrót)

1. **Faza A** (P1, 1–2 dni) → zielone wszystkie suity + asercje regresyjne.
2. **Faza B** (publikacja): remote → 1. bieg CI → gitleaks pełnej historii **przed** public →
   signing/auto-update. Remote sam zdejmuje ryzyko jedynej kopii.
3. **Faza C** (LIVE D/F/G/H/I/J/K).
4. **Faza D** (P2 współbieżność + odzysk + limity/maskowanie WS + hardening).
5. **Faza E/F** (frontend P2/P3 + drobne).
6. **Faza G** (TOP-10, od pozycji `S`).

---

*Plan oparty o weryfikację wieloagentową 84 znalezisk z ANALIZA_PROGRAMU_2026-06-10.md
(16 agentów × aktualny kod, 2026-06-11). Sekcja §0 zawiera wiążące korekty tam, gdzie
weryfikacja poprawiła remediację z analizy. Pozycje `[S/M/L]` = złożoność; `⬜` = do zrobienia.*
