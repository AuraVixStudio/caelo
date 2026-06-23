# PLAN_NAPRAWY_4.md — runda napraw #4 (po ANALIZA_PROGRAMU_2026-06-10)

> **Źródło:** [`docs/plans/ANALIZA_PROGRAMU_2026-06-10.md`](zrealizowane/ANALIZA_PROGRAMU_2026-06-10.md).
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

> **Stan 2026-06-17: Faza B DOMKNIĘTA** — kroki 1–6 ✅ (podpisany release `v0.1.0` opublikowany).
> Jedyna pozostałość: upublicznienie repo (odłożone) → od tego zależy auto-update end-user.
> Pełny runbook + notki sesji: [`PLAN_FAZA_B_RUNBOOK.md`](zrealizowane/PLAN_FAZA_B_RUNBOOK.md).

1. ✅ **ROAD-3.6-a** `[S]` — **ZROBIONE 2026-06-17:** remote `AuraVixStudio/caelo` (prywatny),
   wypchnięto `m15-oss-crossplatform` + `main`, **CI na `main` zielone**. + przepisanie historii git
   (`git-filter-repo`, 74 commity → autor `AuraVix Studio`, usunięte `Co-authored-by:`).
2. ✅ **ROAD-3.6-d** `[S]` — **ZROBIONE** (commit `664e713`, Krok 0): fix kosztu `video/edit|extend`
   + stawki per-model w [`genjobs.py`](../../caelo_core/genjobs.py); `estimate_cost` czyste.
3. ✅ **ROAD-3.6-e** `[S]` — **ZROBIONE** (commit `664e713`, Krok 0): `files/` → `.gitignore`,
   `docs/guides/USER_GUIDE.md` + `docs/README.md` zacommitowane.
4. ✅ **ROAD-3.6-b** `[S]` — **SKAN CZYSTY 2026-06-17:** gitleaks 8.30.1 → `74 commits, 0 leaks`.
   ⏸️ **Public ODŁOŻONE** (decyzja usera — repo pozostaje prywatne; bramka „scan-before-public" spełniona).
5. ✅ **ROAD-3.6-f** `[S]` — **ZROBIONE 2026-06-17:** `pytest caelo_core/tests` → `13 passed`
   (krok już w CI). ⚠️ pułapka: `Scripts\pip.exe` `Fatal error in launcher` → `python.exe -m pip`.
6. ✅ **ROAD-TOP2 / ROAD-3.6-c** `[S/M + M]` — **ZROBIONE 2026-06-17:** `electron-updater` w locku +
   podpis SimplySign (`certificateSha1`, cert AuraVix Studio) powłoki Electron, instalatora i sidecara.
   Release **`v0.1.0`**: podpisany `Caelo-Setup-0.1.0.exe` + `.blockmap` + `latest.yml`.
   ⏸️ Auto-update dla end-userów zależy od public repo (electron-updater + prywatne repo bez auth).

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
| ✅ **S31-c** | `state.py` lazy props | klasowy `_lazy_lock=RLock` + helper `_lazy()` double-checked dla genjobs/hooks/commands/subagents/memory/packages; mcp/skills/lsp rebuild pod lockiem | smoke_core `_unit_lazy_init_race` (16 wątków → 1) | M |
| ✅ **S31-a** | `genjobs.py:191/269/294` + `backend_media.py:49` | `cancel()` + `_run_one` re-czytają status **pod lockiem** (atomowe QUEUED→RUNNING); `_run_image_job` honoruje `cancel.is_set()` przed/po POST | genjobs_check (image cancel PASS) | M |
| ✅ **S31-b** | `genjobs.py:227` | `clear_finished()` — snapshot+prune dictów `_cancel`/`_finished` pod `self._lock` | genjobs_check `_unit_clear_keeps_active` | S |
| ✅ **S34-a** | `mcp/manager.py` `start_server` | zbiór `_starting` pod lockiem (idempotencja sid), `srv.start()` poza lockiem w `try/finally` | mcp_check `test_concurrent_start` (Barrier, licznik=1) | M |
| ✅ **S34-b** | `lsp/manager.py` `_ensure` | całe `_ensure`/restart/shutdown pod `RLock` (check-and-create atomowe) | lsp_check `test_concurrent_ensure` | M |
| ✅ **3.3-b** | `team.py` `new_worktree_path` | ścieżka `run-{pid}-{uuid}-{seq}/{agent_id}` — koniec kolizji między równoległymi `TeamManager` | agent_selfcheck `test_worktree_path_isolation` | S |
| ✅ **3.3-c** | `team.py` (`run`/`_finalize_worktree`/`_run_concurrent`) | subagent po timeout/stop **nie rejestruje merge** (`_cleanup_worktree`); osierocone wątki oznaczone `timeout` w raporcie | agent_selfcheck `test_team_timeout_no_late_merge` | M |
| ✅ **3.3-d** | `roles.py` `RoleRegistry` | `_lock=RLock` wokół read/write (`_save` pod lockiem — koniec „dictionary changed size") | agent_selfcheck `test_role_registry_thread_safety` | S(P3) |
| ✅ **S31-m** | `history_manager.py` | `RLock` wokół mutacja+`_persist` (wołane z workerów genjobs+czatu) — bez lost-update | smoke_core `_unit_history_manager_concurrency` (8 wątków) | S |
| ✅ **RMW settings** | `state.py` `update_settings` | klasowy `_settings_lock=RLock` wokół read-modify-write `caelo_settings.json` | smoke_core `_unit_settings_ownership` | S |

### D.2 Odzysk / zbyt szerokie `except` (chronią przed utratą danych, same ją powodują)

| ID | Plik:linia | Naprawa | Test | Eff |
|---|---|---|---|---|
| ✅ **S31-d** | `history_store.py` `_connect_or_backup` | helper `_is_corruption()`: tylko `malformed`/`not a database`/`encrypted`/integrity → `.corrupt`; `OperationalError("locked"/"I-O")` re-raise | history_check `test_open_error_classification` | S |
| ✅ **S31-e** | `config.py` `load_json_or_backup` | `except OSError` → default **bez** ruszania pliku; korupcja = tylko `ValueError` | smoke_core `_unit_json_corrupt_backup` (OSError) | S |
| ✅ **S31-f** | `oauth_manager.py` `login` | `print()`→`log.info` (stderr) — kontrakt „stdout=handshake" | smoke_core `_unit_oauth_recovery` (brak `print(`) | S |
| ✅ **S31-g** | `oauth_manager.py` | `Lock`→`RLock`; mutacje tokenów (login/logout) pod lockiem; **backoff** po nieudanym refreshu (`_refresh_fail_until`) | smoke_core `_unit_oauth_recovery` (backoff) | M |

### D.3 Bezpieczeństwo / limity routów i agenta

| ID | Plik:linia | Naprawa | Test | Eff |
|---|---|---|---|---|
| ✅ **P2-3.2-b** | `system.py` + nowy `media_paths.py` | walidacja `output-dir` (istniejący katalog, nie-root) przed `set_save_path`; `media_bases()` odrzuca bazę=root (DiD) | smoke_routes `_unit_fs_routes` (root→400 + konsument) | M |
| ✅ **P2-3.2-e** | `errors.py` + `chat.py`/`voice.py`(×2)/`agent.py` | `errors.masked_error(exc,public)`; ramki WS `{"type":"error"}` maskują surowy `str(exc)` jak REST | smoke_chat (sentinel `api.x.ai` nie wycieka) | M |
| ✅ **P2-3.2-d** | `validation.py` + `chat.py`, `voice.py` | `validate_ws_messages` (MAX 400 / 200 KB / data-URI); WS waliduje jak REST, błąd = ramka, pętla trwa | smoke_chat (oversize → error, brak `done`) | M |
| ✅ **3.3-a** | `tools.py` `read_file` + `workspace.py` | `READ_FILE_MAX_BYTES`(16 MB) cap; `Workspace.resolve` odrzuca `CON/PRN/AUX/NUL/COM*/LPT*` (komponenty przed `resolve()`) | agent_selfcheck `test_device_and_read_cap` | M |
| ✅ **3.3-g** | `tools.py` `web_fetch` | `_resolve_blocked` (getaddrinfo → IP) pre-flight i po redirect, fail-closed — koniec DNS-rebindingu | agent_selfcheck `test_web_fetch_dns_rebinding` | M |
| ✅ **S31-j** | `backend_media.py:173` | `_download_media`: `allow_redirects=False` + odrzucenie 30x + re-walidacja `urlparse(r.url).scheme=='https'` | genjobs_check `_unit_media_redirect_guard` | S |
| ✅ **S31-l** | `hooks.py` | `_matches_blocking` **fail-closed** na timeout/błąd regexa; domknięte wzorce `git push -f`/`rd /s`/`del /f` | agent_selfcheck `test_hooks` (S31-l) | M |
| ✅ **P2-3.2-a** | `agent_api.py` | `PUT /agent/caelo-md` egzekwuje `MAX_CAELO_MD_BYTES` (`Field(max_length)` + check bajtów UTF-8) | smoke_routes `_unit_fs_routes` (P2-3.2-a) | S |
| ✅ **P2-3.2-c** | `fs.py` | `GET /fs/read` cap `MAX_FS_READ_BYTES` (413) — koniec OOM na wielkim pliku | smoke_routes `_unit_fs_routes` (413) | S |
| ✅ **S34-c** | `packages/manager.py` + `Marketplace.tsx` + `api.ts` | TOCTOU karty zgody: `inspect_from_url` zwraca `fetched_b64`; GUI instaluje **te bajty** (`data_b64`), nie re-fetch URL | packages_check `test_inspect_install_same_bytes` | M |

### D.4 Poprawność / dane (P3 backendu)

| ID | Plik:linia | Naprawa | Test | Eff |
|---|---|---|---|---|
| ✅ **S31-i** | `responses_client.py` | `usage` **sumowane** przez tury pętli; ostatnia iteracja `max_tool_iters` **nie** wykonuje narzędzi „w próżnię" (break przed egzekucją) | smoke_chat `_unit_responses_mcp_loop` (S31-i) | M |
| ✅ **S31-h** | `state.py` `is_authenticated` | `= active_auth_source()!='none'` (respektuje twardy przełącznik) | smoke_core `_unit_settings_ownership` (S31-h) | S |
| ✅ **S31-k** | `state.py` `delete_project` + nowy `media_paths.py` | kasuje też **pliki** mediów przez wspólny sandbox `media_bases/within` (+ root-guard P2-3.2-b) | history_check `test_delete_project_files` | M |
| ✅ **3.3-e** | `runner.py` `run_turn` | flaga `ran` — `record_event` w `finally` pomija turę bez workspace (koniec pustych „code" eventów) | headless_check `test_no_workspace_no_event` | S |
| ✅ **3.3-f** | `tools.py` `run_command` | reconcyliacja etykiety `[timeout]` z `returncode==0` — koniec fałszywego timeoutu (`[stopped]` zostaje) | agent_selfcheck `test_run_command_no_false_timeout` | S |
| ✅ **P3-3.2-f** | `_ws.py` | **bez zmian** (inwariant trzyma) — dopisany komentarz krzyżowy (NIE podnosić `JOIN` ponad `EMIT`) | — (no-change) | S |
| ✅ **S34-e** | — (already-fixed) | dopisana asercja: `bypass` NIE omija `pre_tool`/`block-dangerous-commands` | agent_selfcheck `test_hooks` (S34-e) | S |

**Domknięcie Fazy D — ✅ ZROBIONE (2026-06-12):** cała runda P2/P3 wdrożona i zielona.
- **Backend:** 12 suit standalone OK + **`api_smoke` ZIELONY (322 PASS)**. Nowe testy
  regresyjne dla każdego znaleziska (genjobs cancel/clear/redirect, lazy-init race, auth,
  delete_project files, recovery except, oauth backoff, HistoryManager concurrency, device/
  read-cap, web_fetch DNS, hooks fail-closed, 5× route, responses usage, runner, MCP/LSP/Role
  concurrency, team worktree/late-merge, packages TOCTOU).
- **Frontend:** `npm test` **197/197**, `typecheck` czysty, `lint` bez nowych ostrzeżeń.
- **Nowy moduł:** `caelo_core/media_paths.py` (wspólny sandbox media-bases dla S31-k + P2-3.2-b).
- **Uwaga:** `oauth print→log` (S31-f) i wąskie `except` (S31-d/e) zmieniają **root-moduły**
  (`oauth_manager.py`/`config.py`/`history_manager.py`) — to fixy logiki, nie restrukturyzacja
  (zgodne z regułą CLAUDE.md).

---

## Faza E — Frontend P2/P3 (sekcja 3.5) + wspólny kanał błędów

**Najpierw** wspólny prymityw błędów (ROAD-4.1-d), bo absorbuje 3 pozycje:

#### ✅ ROAD-4.1-d + S35-e/h/j — Jeden toast/status-line `[M]` — ZROBIONE
Nowy `components/ui/Toast.tsx` (`ToastProvider`+`useToast`, no-op bez providera; wpięty w
`App.tsx`). Przepięte przez niego: **S35-e** (`useWorkspace` saveActive/openFile/selectWorkspace),
**S35-j** (`useDictation` odmowa mikrofonu / błąd STT — koniec 2× `catch{}`), **S35-h**
(`fileToAttachment` → wynik rozróżnialny `{ok|reason}`, `useAttachments` pokazuje pominięte
pliki z powodem). Testy: `Toast.test.tsx`, `useWorkspaceToast.test.tsx`, `useDictationToast.test.tsx`,
`attachmentsFile.test.tsx` (9 PASS).

Pozostałe S35 (niezależne):

| ID | Plik:linia | Naprawa | Test | Eff |
|---|---|---|---|---|
| ✅ **S35-a** | `serverState.ts` | pure `mergeSettings` — write-through cache dla WSZYSTKICH pól odpowiedzi (effort/search/voice) | serverState.test.ts | S |
| ✅ **S35-c** | `useTts.ts` | epoka `reqRef` — dwa szybkie „Read aloud" = ostatni wygrywa (koniec 2 audio) | useTts.test.tsx (play 1×) | S |
| ✅ **S35-d** | `Terminal.tsx` | `ResizeObserver` (refit przy separatorze), initial `resize` na `onopen`, live theme przez `term.options.theme` (bez recreate WS) | sourceGuards.test.ts | M |
| ✅ **S35-f** | `main/index.ts` | zepsuty handshake JSON → `clearSupervisionTimers`+`killCoreForRestart` (jak `verifyConnection`) — koniec osieroconego sidecara | sourceGuards.test.ts | S |
| ✅ **S35-i** | `ChatView.tsx`, `AgentPanel.tsx` + nowy `useStickToBottom.ts` | stick-to-bottom + „Jump to bottom"; **zachowany** wymuszony scroll karty approval (`status==='awaiting'`) | stickToBottom.test.ts (`isNearBottom`) | M |
| ✅ **S35-k** | `CodeEditor.tsx` | `useMemo(() => langFor(path), [path])` (langFor wyeksportowany) — koniec rekonfiguracji CM6 na każdy znak | components/CodeEditor.test.tsx | S |
| ✅ **S35-l** | `api.ts` `streamChat` | `stop()` w CONNECTING zamyka socket + guard w `onopen` — koniec tury mimo Stop (agentClient: WS trwały, nie auto-wysyła tury → bez zmian) | streamChat.test.ts | S |
| ✅ **S35-b** | `Settings.tsx` | `text-warning`→`text-warn` (token istnieje) | styleTokens.test.ts | S |
| ✅ **S35-g** | `useConversations.ts` | **domknięte w P1-I** (`saveError` czyszczone na sukces; `setActiveId` poza updaterem) | useConversations.test.tsx | S |
| ✅ **S35-m** | `CommandPalette.tsx`, `Extensions.tsx`, `AgentPanel.tsx`, `ChatView.tsx` | A11y: CommandPalette `combobox/listbox/option`+`aria-activedescendant`+focus-trap; Extensions `tablist/tab/tabpanel`+roving tabindex+strzałki; dropdowny slash/@ `listbox/option` | CommandPalette.test.tsx + Extensions.test.tsx (role) | M(P3) |

---

## Faza F — Drobne P3 / higiena (sekcja 3.4 minor)

| ID | Plik:linia | Naprawa | Test | Eff |
|---|---|---|---|---|
| ✅ **S34-d** | `sandbox/wrap.py` + nowy `routes/sandbox.py` + `Extensions.tsx` | `sandbox_availability()` + `GET /sandbox/status`; UI: „OS sandbox unavailable on Windows…" gdy profil≠off i niedostępny; `wrap()` bez zmian | sandbox_check `test_availability` | M |
| ✅ **S34-f-1** | `mcp/client.py` + `lsp/client.py` | cap linii stdout MCP (`readline(limit)`+resync) + clamp `Content-Length` w LSP | mcp_check + lsp_check (cap defined) | S |
| ✅ **S34-f-2** | `lsp/client.py` `stop()` | okno `wait(STOP_EXIT_WAIT_S)` przed `_tree_kill` (jak MCP) | lsp_check | S |
| ✅ **S34-f-3** | `lsp/manager.py` `_ensure` | reset `_restarts` po stabilnym biegu (`_STABLE_RUN_S`, nie „każdy start") | lsp_check `test_restart_budget_resets` | S |
| ✅ **S34-f-4** | `sandbox/wrap.py` (bwrap+seatbelt) | `--tmpfs /tmp` w strict (bwrap) + allow `/tmp`+`/private/tmp` w seatbelt | sandbox_check (`--tmpfs` w argv) | S |
| ✅ **S34-f-5** | `packages/manager.py` + `hooks.py` | `datetime.now(timezone.utc)` — sortowalne, forensyka audytu | packages_check (tz-aware) | S |

**Domknięcie Faz E + F — ✅ ZROBIONE (2026-06-12):**
- **Faza E (frontend P2/P3):** wspólny `components/ui/Toast` (wpięty w `App.tsx`, no-op bez
  providera) zlikwidował klasę cichych porażek (Ctrl+S/mikrofon/STT/załączniki); `mergeSettings`
  write-through; `useTts` epoka; `CodeEditor` useMemo; `streamChat.stop()` w CONNECTING; Terminal
  ResizeObserver+initial-resize+live-theme; bad-handshake→restart; wspólny `useStickToBottom`
  (+„Jump to bottom", zachowany scroll karty approval); A11y (CommandPalette combobox/listbox,
  Extensions tablist/tab/tabpanel, dropdowny listbox/option).
- **Faza F (backend minor):** `sandbox_availability()`+`GET /sandbox/status`+notka w Extensions
  (S34-d); cap linii MCP (`readline(limit)`) + clamp Content-Length LSP; okno czystego exitu LSP;
  reset budżetu restartów po stabilnym biegu; `--tmpfs /tmp` w strict; tz-aware timestampy.
- **Testy:** front **224/224** (+27), typecheck czysty, lint bez nowych ostrzeżeń (2 istniejące
  w `Image.tsx`/`Video.tsx`). Backend 12 suit + **api_smoke 322 PASS**. Nowe pliki: `Toast.tsx`,
  `useStickToBottom.ts`, `routes/sandbox.py` + 9 plików testów front.

---

## Faza G — Nowe funkcje wg TOP-10 (po stabilizacji)

Zaczynać od pozycji `S` (gotowa infrastruktura). Każda z **definicją „done"** z analizy.

| # | Funkcja | Eff | Reuse / DoD | Zależności |
|---|---|---|---|---|
| ✅ **TOP1** | `web_search` jako narzędzie agenta — **ZROBIONE** | S | reuse live-search z `responses_client` (`tools.web_search` + `WEB_SEARCH_TOOL`); READONLY, własna wczesna ścieżka jak `lsp`/`delegate` (świadomie **nie** w `permissions.READONLY`, by nie pompować `ALL_FILE_TOOLS`/`PARENT_FILE_TOOLS`); flaga `WEB_SEARCH_ENABLED` (domyślnie ON), reklamowane tylko orkiestratorowi; zwraca syntezę + listę „Sources" (cytowania). Test: `agent_selfcheck` `test_web_search` (13 asercji) | — |
| ✅ **TOP3** | Widżet planu/TODO agenta — **ZROBIONE** | S | narzędzie `update_plan` (META/READONLY, własna ścieżka jak `delegate`, advertowane orkiestratorowi) → ramka `plan` (WsStream) → live `PlanWidget` w `AgentPanel` (przypięty u góry; pending/in_progress/completed; auto-reset na nową turę/sesję; wiersz narzędzia stłumiony). `tools.normalize_plan`/`plan_summary` (pure). Testy: `agent_selfcheck` `test_plan_widget` (11) + `agentPlan.test.ts` (4) | — |
| 🟡 **TOP2** | Auto-update + code signing — **🤖-część zrobiona** | S/M+M | auto-update (electron-updater + feed GitHub Releases) wpięty już w M15-8; 2026-06-13 dodano: guard `release.yml` (`--publish never`+artifact — CI nie wypchnie niepodpisanego), szablon podpisu SimplySign w `electron-builder.yml`, bramkowany podpis sidecara w `build_sidecar.ps1` (+BOM). **👤-reszta** (cert SimplySign CN/Thumbprint, remote, lokalny podpisany release) → [`PLAN_FAZA_B_RUNBOOK.md`](zrealizowane/PLAN_FAZA_B_RUNBOOK.md) Krok 6 | ROAD-3.6-a |
| ✅ **TOP4** | Katalog MCP one-click — **ZROBIONE** | S/M | kurowany `mcp/catalog.py` (7 serwerów: filesystem/memory/sequential-thinking/everything/github/playwright/brave-search) → `GET /mcp/catalog`; UI „Catalog" w `McpServers.tsx` (one-click + inputy ścieżka/token, podgląd komendy = consent). „Install" reużywa `POST /mcp` z `enabled=False` (**install ≠ autostart**); start = osobna, potwierdzana akcja. Testy: `mcp_check` `test_catalog` (5) + `api_smoke` (route, niezasłonięty przez `/{sid}`) + `mcpCatalog.test.ts` (5) | M16/M14 |
| ✅ **TOP5** | Artefakty HTML/SVG (sandbox iframe) — **ZROBIONE** (mermaid odłożony) | M | `lib/artifacts.ts` (`buildArtifactSrcDoc`: wstrzyknięty CSP + auto-resize + wrap SVG) + `ArtifactFrame.tsx` (iframe `sandbox="allow-scripts"` BEZ `same-origin` → opaque origin; toggle Preview/Code); `Markdown.tsx` routuje bloki ```html```/```svg``` → artefakt. Bezpieczeństwo: brak dostępu do rodzica/tokenu, CSP blokuje sieć/skrypty zewn./formularze. **Mermaid odłożony** (CSP blokuje skrypt z CDN, a bundlowanie = `npm install mermaid`). Testy: `artifacts.test.ts` (5) + `Markdown.test.tsx` (+4 integ.) | — |
| ✅ **TOP6** | Recenzja PR przez `gh` — **ZROBIONE** | M | wbudowana komenda `/pr` (review PR przez `gh pr view`/`gh pr diff`; findings z `file:line`) + skill `pr-review` (multi-agent: `delegate` reviewerów po obszarach → konsolidacja → opcjonalny post). Odczyt i publikacja (`gh pr review`) idą przez `run_command` → **bramka zatwierdzania** (mutacje gated). Pułapka udokumentowana: scrubbed env (P0-6) strippuje `GH_TOKEN` → wymaga `gh auth login`. Testy: `api_smoke` `_unit_commands_skills` (2). ⚠️ realny `gh` u usera | `gh` u usera |
| ⬜ **TOP7** | Rewind/edycja wiadomości czatu | M | lokalny `useConversations`; **po P1-H i P1-I** | P1-H, P1-I |
| ⬜ **TOP8** | Inline Ctrl-K w CodeMirror | M | CM6 decoration API; przy okazji `langFor` useMemo (S35-k) | — |
| ⬜ **TOP9** | Auto-pamięć użytkownika | M | M19-B8 embeddings/`memory.py` istnieją; brak ekstrakcji+UI (opt-in!) | M19-B8 |
| ⬜ **TOP10** | Lokalne background-agents + powiadomienia | M+S | headless B1 + kolejka genjobs + worktree M17 + Notification API; powiadomienia to szybki sub-win | B1/M17 |

**Postęp Fazy G (2026-06-13):** ✅ **TOP1** wdrożone i zielone — `config.WEB_SEARCH_ENABLED`
(domyślnie ON, `CAELO_WEB_SEARCH=0` wyłącza), `tools.web_search` (reuse `responses_client`
live-search, synteza + „Sources"), `session.WEB_SEARCH_TOOL` + `_handle_web_search` (READONLY,
bez bramki, tylko orkiestrator), ikona w `AgentPanel.tsx`. Weryfikacja: `agent_selfcheck`
(`test_web_search`, 13 asercji) · `headless_check` · `lsp_check` · `api_smoke` **OK** · front
`typecheck` czysty, `lint` bez nowych ostrzeżeń. ⚠️ Realny live-search xAI potwierdza user
(sandbox blokuje `api.x.ai`).

🟡 **TOP2** (= Faza B Krok 6) — **część asystenta zrobiona** (2026-06-13): auto-update był już
wpięty (M15-8), doszły guard `release.yml` (`--publish never` — CI nie wypchnie niepodpisanego
buildu), szablon podpisu SimplySign w `electron-builder.yml`, bramkowany podpis sidecara w
`build_sidecar.ps1` (+UTF-8 BOM dla PS 5.1). YAML/PS zwalidowane. **👤-reszta** (cert SimplySign,
remote ROAD-3.6-a, lokalny podpisany release) wg [`PLAN_FAZA_B_RUNBOOK.md`](zrealizowane/PLAN_FAZA_B_RUNBOOK.md)
Krok 6.

✅ **TOP3** — **ZROBIONE** (2026-06-13): narzędzie `update_plan` (live checklist jak TodoWrite,
META/READONLY, bez bramki) emituje ramkę `plan` renderowaną jako przypięty `PlanWidget` w
`AgentPanel` (status pending/in_progress/completed, auto-reset na nową turę/sesję). Walidacja:
`agent_selfcheck` `test_plan_widget` (11) · front `agentPlan.test.ts` (4) · typecheck/lint czyste ·
`api_smoke`/`headless_check` OK. ⚠️ Wizualny render w trakcie realnego przebiegu agenta potwierdza
user (sandbox blokuje xAI/Electron).

✅ **TOP4** — **ZROBIONE** (2026-06-13): kurowany katalog MCP (`caelo_core/mcp/catalog.py`, 7 serwerów)
serwowany przez `GET /mcp/catalog`; sekcja „Catalog" w `McpServers.tsx` dodaje serwer jednym
kliknięciem (z inputami ścieżki/klucza + podglądem komendy = consent), reużywając `POST /mcp` z
`enabled=False` — **install ≠ autostart** (start to osobna, potwierdzana akcja). Walidacja: `mcp_check`
`test_catalog` (5; install-disabled) · `api_smoke` (route niezasłonięty przez `/{sid}`) · front
`mcpCatalog.test.ts` (5) · typecheck/lint czyste. ⚠️ Realna instalacja/start serwera npx potwierdza
user (sandbox blokuje sieć/exec).

✅ **TOP5** — **ZROBIONE (HTML+SVG)** (2026-06-13): bloki ```html```/```svg``` z modelu renderują
się jako artefakt w SANDBOXOWANYM iframe (`ArtifactFrame` + `lib/artifacts.buildArtifactSrcDoc`),
z toggle Preview/Code i auto-resize. Bezpieczeństwo: `sandbox="allow-scripts"` bez `same-origin`
(opaque origin — brak dostępu do tokenu/rodzica) + wstrzyknięty CSP (blokuje sieć/skrypty zewn.).
Walidacja: `artifacts.test.ts` (5) + `Markdown.test.tsx` (+4 integ.: iframe/sandbox/CSP/toggle) ·
typecheck/lint czyste. ⚠️ **Mermaid odłożony** (CSP blokuje CDN; bundlowanie wymaga `npm install
mermaid` — psułoby `npm ci`/typecheck bez instalacji). ⚠️ Wizualny render potwierdza user (devMock
nie mockuje strumienia czatu → artefakt nieobserwowalny w `preview:web`).

✅ **TOP6** — **ZROBIONE** (2026-06-13): wbudowana komenda `/pr` (recenzja PR z GitHuba przez
`gh pr view`/`gh pr diff` → findings z `file:line`) + skill `pr-review` (multi-agent: `delegate`
reviewerów → konsolidacja → opcjonalny `gh pr review`). Wszystkie wywołania `gh` (odczyt i
publikacja recenzji) idą przez `run_command` → bramkę zatwierdzania (mutacje gated). Komenda
auto-pojawia się w composerze (fetch `/commands`), skill auto-podchwycony (glob `skills/builtin/`).
Udokumentowana pułapka: scrubbed env (P0-6) strippuje `GH_TOKEN`/`GITHUB_TOKEN` → `gh` musi być
uwierzytelniony przez `gh auth login` (config/keyring), nie zmienną env. Walidacja: `api_smoke`
`_unit_commands_skills` (2 asercje: komenda + skill) · RESULT OK. ⚠️ Realny przebieg `gh` potwierdza
user (sandbox blokuje sieć/exec; `gh` u usera).

🔧 **Fix LIVE — reasoning_effort zależny od modelu** (2026-06-13, z testów usera): tryby Low/Med/High
dawały „Agent error" na `grok-build-0.1` (tylko Auto działał). Diagnoza (docs.x.ai): `reasoning_effort`
wspierają tylko niektóre modele (grok-4.3, grok-4.20-*reasoning); grok-4/grok-build/grok-3 zwracają 4xx.
Naprawa: oba klienty (`agent/llm.py` chat/completions + `responses_client.py` /responses) **ponawiają raz
BEZ pola na 400/422** — effort jest best-effort, tura nie pada na modelu bez wsparcia. UI: `lib/modelCaps.
modelSupportsEffort` + ostrzeżenie w `EffortSelect` (trigger warn + nota „ignores reasoning effort"), żeby
user wiedział przy wyborze modelu. Testy: `agent_selfcheck` (fallback 4xx) · front `modelCaps.test.ts` (4) +
`EffortSelect.test.tsx` (3). Pozostałe TOP-7…10 + ROAD-4.2-a do zrobienia.

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
