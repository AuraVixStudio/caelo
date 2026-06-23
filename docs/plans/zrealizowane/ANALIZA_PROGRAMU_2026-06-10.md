# ANALIZA_PROGRAMU_2026-06-10.md — gruntowny przegląd Caelo Desktop

> **Cel:** niezależna, całościowa analiza programu po M19–M22: realne błędy, obszary do
> udoskonalenia i luki funkcjonalne na tle podobnych narzędzi (Claude Code, Cursor, Cline,
> Codex, Gemini CLI, Zed, ChatGPT/Claude Desktop, Aider…).
>
> **Metodologia (2026-06-10):**
> 1. **Testy:** frontend `typecheck + lint + vitest` (✅ 191/191) · backendowe self-checki
>    uruchomione standalone — 13 suit (pytest niedostępny w venv: instalację `requirements-dev`
>    blokuje sieć z TLS-interception; suity mają własne `main()`). Wynik: **12/13 zielone,
>    `api_smoke` FAIL** — zdiagnozowany niżej (B-1/B-2).
> 2. **Rewizja kodu w 5 obszarach** (silnik agenta · rdzeń backendu · routy API ·
>    podsystemy rozszerzalności · frontend Electron/React) — każde znalezisko z `plik:linia`;
>    pozycje, których nie dało się w pełni potwierdzić, oznaczone „do weryfikacji".
> 3. **Analiza porównawcza** funkcji konkurencji — z wiedzy do **stycznia 2026**
>    (sieć w sandboksie zablokowana); nowości II–VI 2026 nieuwzględnione.
>
> **Konwencja priorytetów:** P1 = realny defekt bezpieczeństwa/poprawności/danych do naprawy
> przed publikacją · P2 = realny, ale ograniczony skutkiem/prawdopodobieństwem · P3 = drobne/UX.

---

## 0. Streszczenie

Projekt jest w **bardzo dobrej kondycji jak na jednoosobowe utrzymanie**: wcześniejsze rundy
hardeningowe (P0-1…P0-8, M5–M6, M18) **faktycznie trzymają** — rewizja celowo szukała obejść
metaznaków, sandboxa ścieżek (UNC, `\\?\`, drive-relative), wycieków env i balansu historii
i **nie znalazła regresji** w tych mechanizmach. Testowalność (13 suit + RTL + E2E), dokumentacja
i przygotowanie OSS (Apache-2.0, NOTICE, CLA, gitleaks, CI 3×OS) są ponadprzeciętne.

Najważniejsze ustalenia tej analizy:

1. **Cztery nowe P1 w kodzie** — wszystkie w *nowszych* warstwach, które ominęły wzorce
   utwardzone w starszych modułach:
   - path traversal przez **id sesji agenta** (odczyt/nadpis/usunięcie dowolnego `*.json`,
     w tym `caelo_auth.json`),
   - **obejście reguł `deny`** przez `grep`/`glob` (egzekucja na argumentach, nie na wynikach),
   - **LSP: short-reads** psują ramkowanie Content-Length (ginące diagnostyki/odpowiedzi),
   - **GenJob: data-URI w `params`** persistowane i zwracane w całości — u realnego użytkownika
     `GET /genjobs` = **82 MB JSON na każdy tick pollingu** (potwierdzone na żywo; to też
     przyczyna FAIL-a `api_smoke`).
2. **`api_smoke` chodzi po realnym `DATA_DIR` użytkownika** — test padł na prawdziwych danych,
   a linia dalej wykonałby destrukcyjne `DELETE /genjobs` na realnej liście zadań. Self-checki
   wymagają izolacji katalogu danych.
3. **Frontend ma klasę błędów „na szwach"** (reconnect, unmount, przełączanie rozmów):
   martwe linki markdown, `busy` po padzie sidecara, „Retry" piszący do złej rozmowy,
   debounce gubiący niedopisane rozmowy, wyścig mikrofonu.
4. **Proces wciąż jest największym ryzykiem** (zgodnie ze SWOT 2026-06-07): repo **nie ma
   remote** — CI nigdy nie wykonało ani jednego biegu, a jedyna kopia kodu żyje na jednym
   dysku; sekcje LIVE **D/F/G/H/I/J/K** pozostają niezweryfikowane.
5. Na tle konkurencji największe luki to: web-search w agencie, widżet planu/TODO, auto-update
   + podpisywanie binarek, katalog MCP one-click, artefakty HTML/mermaid w czacie, recenzja
   PR-ów przez `gh`, rewind/edycja rozmowy, inline Ctrl-K w edytorze (pełna lista w §4).

**Rekomendowana kolejność:** P1 z §2 (kilka małych, punktowych poprawek) → izolacja
self-checków (B-2) → publikacja (remote + pierwszy bieg CI + signing/auto-update) →
dokończenie weryfikacji LIVE → wyścigi P2 → nowe funkcje wg TOP-10 (§4.3).

---

## 1. Wyniki weryfikacji automatycznej

| Obszar | Wynik | Uwagi |
|---|---|---|
| `npm run typecheck` (node+web) | ✅ | |
| `npm run lint` (ESLint react-hooks) | ✅ | |
| `npm test` (Vitest) | ✅ 191/191 (25 plików) | |
| Self-checki backendu (13 suit standalone) | 🟡 12/13 | `handshake`, `agent_selfcheck`, `history`, `genjobs`, `mcp`, `packages`, `headless`, `acp`, `lsp`, `sandbox`, `embeddings`, `crossplatform` — zielone |
| `api_smoke` | ❌ FAIL (powtarzalny) | `ConnectionResetError` przy `GET /genjobs` — diagnoza: B-1 + B-2 poniżej |
| pytest w venv | ⚠ brak | `requirements-dev` nieinstalowalne w sieci z TLS-interception (znana pułapka); suity odpalone przez własne `main()` |

### B-1 (P1) — `GET /genjobs` zwraca pełne `params` z data-URI: 82 MB na request

**Zdiagnozowane na żywo.** W realnej bazie (`caelo_history.db`, dev `DATA_DIR` = korzeń repo)
leży 16 zadań generacji z testów LIVE C1–C7; ich `params` zawierają pełne base64 data-URI
obrazów/wideo — **łącznie 82,2 MB**. `GenJob.to_dict()` ([genjobs.py:105](../../../caelo_core/genjobs.py))
zwraca `params` w całości, a [routes/genjobs.py:127](../../../caelo_core/routes/genjobs.py) serializuje
je dla całej listy. Pomiar: `curl` pobiera 82 236 538 bajtów; klienci `urllib`/`Invoke-WebRequest`
dostają **reset połączenia w trakcie ciała** (stąd FAIL `api_smoke` na tej maszynie). Renderer
**polluje** `/genjobs` w trakcie aktywnego zadania — każdy tick to dziesiątki MB.

Dodatkowo (rewizja rdzenia): `upsert_gen_job` robi `INSERT OR REPLACE` **pełnego wiersza przy
każdej zmianie statusu** (queued→running→done = ≥3 zapisy wielomegabajtowego wiersza pod
globalnym lockiem) — baza puchnie i blokuje inne zapisy.

**Naprawa:** nie trzymać blobów w `params` (zapis do pliku tymczasowego / artefaktu i
referencja) **albo** przynajmniej strip/skrót data-URI w `to_dict()` dla listy (pełne `params`
tylko wewnętrznie dla egzekutora i `retry`).

### B-2 (P1) — self-checki chodzą po realnym `DATA_DIR` użytkownika

[`_smoke_common.py` / `api_smoke.py:80-87`](../../../caelo_core/tools/api_smoke.py) spawnuje sidecar
z `cwd=REPO_DIR` i odziedziczonym env — a w dev `config.DATA_DIR` **zawsze** = korzeń repo
(brak env-override w [config.py:50](../../../config.py)). Skutki: (a) test padł na realnych danych
(B-1); (b) linia dalej (`smoke_media.py:410`) wykonałby **`DELETE /genjobs` na realnej liście
zadań użytkownika** — przed utratą danych uratował go wyłącznie wcześniejszy crash; (c) wyniki
self-checków zależą od zawartości prywatnej bazy (niedeterminizm).

**Naprawa:** dodać `CAELO_CORE_DATA_DIR` (env-override w `config.py`, honorowany przed
`IS_FROZEN`-logiką) i ustawiać go w `_smoke_common` na katalog tymczasowy. Przy okazji CI
przestanie zależeć od czystości workspace.

---

## 2. Błędy — P1 (napraw przed publikacją)

### Bezpieczeństwo / poprawność (backend)

| # | Znalezisko | Lokalizacja | Opis / naprawa |
|---|---|---|---|
| P1-A | **Path traversal w id sesji agenta** | [agent/sessions.py:37](../../../caelo_core/agent/sessions.py) + [routes/sessions.py](../../../caelo_core/routes/sessions.py) + [routes/agent.py:173](../../../caelo_core/routes/agent.py) + headless `-s/-r` | `session_path(sid)` nie sanityzuje `sid`. REST: segment URL nie przepuści `/`, ale **`\` na Windows tak** (`sid="..\..\caelo_auth"` → `DATA_DIR/caelo_auth.json`); WS przyjmuje `{"type":"session","id":…}` z surowego JSON (slashe przechodzą). Skutek: token-gated **odczyt** (`GET`), **usunięcie** (`DELETE`) i — najgroźniejsze — **nadpisanie** dowolnego `*.json` (po `resume_session` kolejna tura persistuje sesję pod spreparowaną ścieżką, np. do `caelo_settings.json`). Naprawa: walidacja `^[A-Za-z0-9_-]{1,64}$` w `session_path`/`load`/`save`/`delete` (wzorzec `_NAME_RX` już istnieje w skills). |
| P1-B | **Reguły `deny` nie chronią treści przed `grep`/`glob`** | [agent/permission_rules.py:147](../../../caelo_core/agent/permission_rules.py) + [agent/tools.py:227](../../../caelo_core/agent/tools.py) | `targets_for_tool` mapuje `grep`→`(Grep, path)` i `glob`→`(Read, pattern)` — reguła oceniana na **argumentach**, nie na **wynikach**. `deny Read(secret/**)` nie powstrzyma `grep("API_KEY", path=".")`, który zwróci modelowi dopasowane linie z `secret/`. Deklarowana twarda bariera „deny>allow" jest dla narzędzi przeszukujących obchodzialna. Naprawa: filtrować każdą trafioną ścieżkę wyników grep/glob przez `evaluate_rules("read_file", {"path": rel})`. |
| P1-C | **LSP: short-reads psują ramkowanie Content-Length** | [lsp/client.py:177](../../../caelo_core/lsp/client.py) | `FileIO.read(n)` na pipe (`bufsize=0`) może zwrócić mniej niż `n` bajtów; większe ciała (diagnostyki, `hover` dużego pliku) przychodzą obcięte → `json.loads` pada → wiadomość znika (ciche gubienie `publishDiagnostics`, timeouty `_request` po 15 s). Naprawa: pętla doczytująca do `length` bajtów. |
| P1-D | **GenJob: data-URI w `params`** | §1 B-1 | jw. |
| P1-E | **Self-checki na realnym `DATA_DIR`** | §1 B-2 | jw. |

### Frontend (defekty widoczne dla użytkownika / grożące utratą danych)

| # | Znalezisko | Lokalizacja | Opis / naprawa |
|---|---|---|---|
| P1-F | **Martwe linki w odpowiedziach modelu** | [Markdown.tsx:39-66](../../../desktop/src/renderer/src/components/Markdown.tsx) + [main/index.ts:397](../../../desktop/src/main/index.ts) | `Markdown` nie nadpisuje `<a>` → klik = nawigacja top-level, którą `will-navigate` blokuje. Każdy link z markdownu modelu nic nie robi (cytowania działają, bo mają jawnie `target="_blank"`). Naprawa: `components={{ a: … target="_blank" rel="noreferrer" }}`. |
| P1-G | **`busy` nie resetuje się po padzie WS** | [AgentPanel.tsx:222,358-373](../../../desktop/src/renderer/src/components/code/AgentPanel.tsx) | Po crash/restarcie sidecara composer agenta zostaje zablokowany (tylko „Stop") do przeładowania. Naprawa: reset `busy` + wpis „connection lost" w `onClose`. |
| P1-H | **„Retry" pisze do złej rozmowy** | [ChatView.tsx:394,524-541,967-979](../../../desktop/src/renderer/src/components/ChatView.tsx) | `error`/`lastTurnRef` nie są czyszczone przy zmianie `activeId` — pasek błędu z rozmowy A widać w B, a „Retry" streamuje odpowiedź (z historią A) do rozmowy B. |
| P1-I | **Debounce zapisu rozmów gubi dane** | [useConversations.ts:42-50](../../../desktop/src/renderer/src/lib/useConversations.ts) | Zapis localStorage z debounce 800 ms, a cleanup robi `clearTimeout` (kasuje oczekujący zapis); delty streamingu stale resetują timer. Przełączenie modułu (lazy unmount) / zamknięcie apki = utrata całej tury. Naprawa: flush synchroniczny w cleanup (+ docelowo zapis per-rozmowa / IndexedDB). |
| P1-J | **Wyścig `MicCapture.start()/stop()`** | [audioStream.ts:80-119](../../../desktop/src/renderer/src/lib/audioStream.ts) | Guard „stop ubiegł start" jest po `addModule`, ale nie po `await getUserMedia` — szybki toggle Talk/Live zostawia **włączony track mikrofonu** bez referencji (wskaźnik nagrywania do restartu). Naprawa: flaga `stopped` sprawdzana po każdym await. |

---

## 3. Błędy — P2 (realne, ograniczone skutkiem) i ważniejsze P3

### 3.1 Rdzeń backendu (wyścigi wątków + zbyt szerokie `except`)

Dwa powtarzalne wzorce: **wyścigi na szwach „async serwer + workery"** (dotąd maskowane przez
jednego użytkownika) i **ścieżki odzysku traktujące błąd I/O jak korupcję** (same mogą
spowodować utratę danych, przed którą chronią).

- **genjobs.py:191-204 vs 269-292** — TOCTOU `cancel()`↔worker: zadanie anulowane może zostać
  „wskrzeszone" (cancelled→running→done; egzekutor obrazu nie sprawdza `cancel_event`).
- **genjobs.py:227-237** — `clear_finished()` bez locka wypruwa eventy świeżo zasubmitowanego
  joba → jego `cancel()`/`wait()` przestają działać.
- **state.py:378-386** — leniwa inicjalizacja `Backend.genjobs` (i `mcp/hooks/commands/skills/
  packages/memory`) bez locka; dwa równoległe requesty mogą zbudować **dwa** managery, a
  `_reap_stale()` drugiego oznaczy aktywne zadania pierwszego jako `failed("interrupted")`.
  Ujednolicić z double-checked lockiem z `history_store.get_store()`.
- **history_store.py:182-201** — `except sqlite3.DatabaseError` łapie też `OperationalError`
  („database is locked" — np. druga instancja sidecara w dev) → zdrowa baza wędruje do
  `.corrupt`, user widzi „zniknęła historia".
- **config.py:244-265** — `load_json_or_backup`: `except Exception` obejmuje `OSError`
  (np. antywirus trzymający plik) → plik niesłusznie do `.corrupt`. Korupcja = tylko
  `ValueError/JSONDecodeError`; `OSError` → default bez ruszania pliku.
- **oauth_manager.py:164** — `print()` na **stdout** w `login()` łamie kontrakt „stdout =
  wyłącznie handshake" (Electron parsuje ten strumień).
- **oauth_manager.py:124-130,219-273** — `login()/logout()/_fetch_userinfo()` mutują tokeny
  poza `self._lock`; wyścig refresh↔login może zgubić zrotowany refresh_token (trwałe
  wylogowanie). **:291-302 (do weryfikacji)** — brak backoffu po nieudanym refreshu: każde
  wywołanie ponawia sieciowy refresh pod lockiem (30 s) — „wszystko muli".
- **state.py:321-322** — `is_authenticated()` ignoruje twardy przełącznik `auth_source`
  (`/auth/status.authenticated` potrafi kłamać przy `oauth` bez logowania); powinno być
  pochodną `_resolve_auth()`.
- **responses_client.py:386-389** — `usage` **nadpisywane** per tura pętli narzędzi — licznik
  tokenów w czacie z tool-callami zaniżony; sumować pola. **:410-441** — ostatnia iteracja
  `max_tool_iters` wykonuje narzędzia „w próżnię" (skutki uboczne — np. wygenerowany obraz —
  których model już nie zobaczy).
- **backend_media.py:178-196** — guard https-only omijany redirectem (https→http);
  `allow_redirects=False` lub walidacja `r.url`.
- **state.py:614-632** — `delete_project` kasuje **rekordy** artefaktów, ale zostawia pliki
  mediów na dysku (niespójne z `DELETE /artifacts/{id}`); udokumentować albo sprzątać.
- **hooks.py:204-213** — hook `block-dangerous-commands` jest **fail-open** przy timeoutcie
  regexa; luki wzorców: `git push -f`, `rd /s`, `del /f`.
- **history_manager.py:23-39** — `HistoryManager` niethread-safe, wołany z workerów genjobs
  i czatu (lost-update wpisów historii).

### 3.2 Routy API

- **agent_api.py:71-83** — `PUT /agent/caelo-md` nie egzekwuje `MAX_CAELO_MD_BYTES`
  (GET deklaruje limit, PUT przyjmuje dowolny rozmiar).
- **system.py:32-35** — `PUT /config/output-dir` bez walidacji; ścieżka staje się „dozwoloną
  bazą" `_media_bases()` → poszerza sandbox `GET/DELETE /artifacts/{id}` (np. na `C:\`).
- **fs.py:99-107** — `GET /fs/read` bez capa rozmiaru (`read_text` całego pliku → OOM).
- **chat.py:242 / voice.py:266** — `messages[]` z WS bez limitu liczby/rozmiaru (REST ma
  limity z `validation.py`, kanały WS nie).
- **chat.py:213-214, voice.py:322, agent.py:138** — ramka `{"type":"error"}` niesie surowy
  `str(exc)` (w tym treść błędu xAI/URL-e z `requests`) — REST maskuje przez
  `upstream_error()`, WS nie; ujednolicić.
- **_ws.py:82-92 (do weryfikacji)** — `EMIT_TIMEOUT_S(30) > JOIN_TIMEOUT_S(5)`: worker
  zablokowany w `emit()` może wisieć ~25 s po `aclose()` (inwariant „brak pracy po
  rozłączeniu" trzyma; kosmetyka zasobów).
- Pozytywnie: **token fail-closed potwierdzony na wszystkich routach i 6 WS**; sandbox ścieżek
  `/fs`, `/git`, `/collections`, `/artifacts` solidny; `validation.py` szczelne dla mediów.

### 3.3 Silnik agenta

- **tools.py:164-179** — `read_file` bez capa rozmiaru (czyta cały plik mimo `offset/limit`;
  brak `stop_flag`); na Windows `read_file("CON")` przechodzi sandbox i **wiesza wątek**
  nieprzerywalnie (urządzenia `CON/PRN/AUX/NUL/COM*/LPT*` odrzucać w `Workspace.resolve`).
- **team.py:428-450** — ścieżki worktree (`worktrees/run{N}/{agent_id}`) liczone per-instancja
  `TeamManager` → **kolizje katalogów** między równoległymi przebiegami (WS + headless / dwa
  okna); dodać PID/UUID do nazwy.
- **team.py:534-536** — `join(timeout=2)` po monitorze: subagent tkwiący w `requests.post`
  (timeout 600 s) **przeżywa** `team.run()` i może dorzucić merge po `team_done`.
- **roles.py:431-446** — `RoleRegistry` bez locka (czytany z wątków subagentów, pisany z REST).
- **runner.py:179-206** — `record_event` w `finally` wykonuje się też przy braku workspace
  (pusty event „code" w historii).
- **tools.py:468-503** — wyścig timera vs normalne zakończenie `run_command`: rzadki fałszywy
  `[timeout]` w komunikacie mimo exit 0.
- **tools.py:550-603** — `web_fetch` bez allowlisty blokuje tylko **literalne** prywatne IP —
  nazwa hosta wskazująca na 10.x/169.254.x przechodzi (DNS rebinding); rozwiązywać hosta
  i sprawdzać IP po rozwiązaniu.
- Pozytywnie: P0-1…P0-8 bez regresji; UNC/`\\?\`/drive-relative poprawnie odrzucane; balans
  historii (synthetic tool results) działa.

### 3.4 Podsystemy rozszerzalności

- **mcp/manager.py:272-287** — `start_server` zwalnia lock przed blokującym `srv.start()` →
  dwa równoległe POST-y startują **ten sam** serwer dwa razy; pierwszy klient (z żywym
  podprocesem) zostaje osierocony do `shutdown()`. Flaga „starting" / per-sid lock.
- **lsp/manager.py:47-71** — `_ensure` bez locka → analogiczny podwójny spawn serwera LSP
  przy współbieżnych subagentach.
- **packages/manager.py:660-668** — **TOCTOU karty zgody**: `inspect_from_url` i
  `install_from_url` pobierają URL **dwukrotnie**; `integrity` jest samoodnosząca (manifest
  niesie hash własnego payloadu), więc serwer może podmienić pakiet między inspekcją a
  instalacją. Instalować z bajtów pobranych przy inspekcji.
- **sandbox/wrap.py:116-119** — na Windows profil ≠ `off` daje **cichy no-op** (tylko log na
  stderr); na podstawowej platformie projektu user może zakładać izolację, której nie ma —
  pokazać „OS sandbox unavailable on Windows" w UI.
- **headless (do weryfikacji)** — potwierdzić, że `--permission-mode bypass` NIE omija ścieżki
  hooków `pre_tool` (`block-dangerous-commands`).
- Drobne: brak limitu długości linii stdout MCP (zjedzenie pamięci przez zepsuty serwer);
  LSP `stop()` tree-killuje bez okna na czyste `exit`; `_restarts` LSP bez resetu po stabilnym
  działaniu; bwrap `strict` bez `--tmpfs /tmp` (kompilatory/git padną); naiwne `datetime.now()`
  w rejestrze pakietów/audycie.

### 3.5 Frontend (P2/P3)

- **serverState.ts:163-176** — write-through cache aktualizuje tylko 4 pola; zapis
  `chat_search_mode`/`effort`/`voice` cofa się w UI po remount (serwer ma dobrą wartość).
- **Settings.tsx:230** — klasa `text-warning` nie istnieje (token to `text-warn`) — ostrzeżenie
  bez koloru.
- **useTts.ts:32-58** — dwa szybkie „Read aloud" → dwa audio grają naraz.
- **Terminal.tsx:12-93** — brak `ResizeObserver` (separator paneli nie refituje), motyw nie
  przebarwia żywego terminala, brak initial resize (pty startuje 80×24).
- **useWorkspace.ts:94-110** — nieudany **Ctrl+S** jest cichy (user myśli, że zapisał);
  podobnie `openFile`/`selectWorkspace`.
- **main/index.ts:249-252** — zepsuty JSON handshake'u → stan `error` bez kill/restartu
  (watchdog patrzy tylko na `starting`).
- **useConversations.ts:44-48** — `saveError` („storage is full") nigdy nie znika po sukcesie;
  **:68-75** — side-effect w updaterze `setConvos` (StrictMode-unsafe).
- **attachments.ts:32-51** — pliki za duże/binarne odsiewane **bez komunikatu**.
- **ChatView.tsx:447 / AgentPanel.tsx:250** — bezwarunkowy auto-scroll (brak „stick-to-bottom
  tylko przy dole" + przycisku „Jump to bottom").
- **useDictation.ts:43-63** — odmowa mikrofonu / błąd STT całkowicie ciche (`catch {}` ×2).
- **CodeEditor.tsx:27-35** — `langFor(path)` bez `useMemo` → rekonfiguracja rozszerzeń
  CodeMirror przy każdym znaku.
- **api.ts:1291-1299** — `stop()` w stanie CONNECTING gubi ramkę i nie zamyka socketu.
- **A11y (P3):** CommandPalette bez focus-trapa/`listbox` (Popover robi to wzorowo — przenieść
  wzorzec); taby Extensions bez ról ARIA; dropdowny slash/@ bez `listbox/option`.

### 3.6 Higiena repo (stan na 2026-06-10)

- **Brak `git remote`** — CI (ci.yml/cla.yml/release.yml) nigdy nie wykonało żadnego biegu;
  **jedyna kopia kodu na jednym dysku** (ryzyko nie-software'owe, ale największe).
- Niezacommitowane: `caelo_core/genjobs.py` (stawki per-model — poprawne; jeden zgrzyt: koszt
  `video/edit` liczony z `params.duration`=6 s, choć edycja zachowuje długość źródła — szacunek
  przekłamany dla dłuższych wideo), `docs/guides/USER_GUIDE.md`, nieotrackowany `files/`
  (brand-pack — zdecydować: do `assets/brand/` czy `.gitignore`).
- pytest nieobecny w venv (pułapka TLS) — `0.4` z PLAN_WERYFIKACJI_LIVE wciąż otwarte.

---

## 4. Obszary do udoskonalenia i porównanie z podobnymi programami

### 4.1 Udoskonalenia inżynieryjne (z rewizji, poza błędami)

1. **Współbieżność jako temat rundy:** jeden wzorzec lazy-init z lockiem (jak
   `history_store.get_store()`), lock w `RoleRegistry`/`LspManager`/`McpManager.start`,
   RMW-lock na `caelo_settings.json`, kolejka zamiast wątku-per-zdarzenie w
   `_maybe_index_memory`.
2. **Wydajność gorących ścieżek:** cache `_resolve_auth` (dziś czyta settings z dysku przy
   każdym wywołaniu API), kNN poza lockiem magazynu, `compute_changes` porównujące najpierw
   `os.stat` zamiast czytać całe drzewa, `glob` z przycinaniem `dirnames` (nie wchodzić w
   `node_modules`), memoizacja `EntryView` w AgentPanel.
3. **Odporność:** retry przejściowych błędów `poll_video_status` (pojedynczy timeout failuje
   płatne zadanie wideo), `fsync` przed `os.replace` dla `caelo_auth.json`/`caelo_settings.json`,
   `Backend.shutdown()` domykający genjobs/history_store (czysty checkpoint WAL), tolerancja
   wieloliniowych `data:` w parserach SSE.
4. **Spójny kanał błędów w UI:** dziś trzy style (pasek w ChatView — wzorcowo, `pushInfo`
   w AgentPanel, cisza w useWorkspace/useDictation). Wspólny toast/status-line zlikwiduje
   klasę „cichych porażek".
5. **API:** `total` w odpowiedziach paginowanych (dziś `count`=len strony), `total_cost`
   z `SELECT SUM` (dziś z bieżącej strony), rozróżnienie 4xx (packages `_err` mapuje wszystko
   na 400, w tym tamper).
6. **`/genjobs` przez WS-push** zamiast pollingu — hook `GenJobManager.on_update` już istnieje
   i jest nieużyty.

### 4.2 Luki funkcjonalne na tle konkurencji

(Pełna analiza porównawcza: Claude Code, Cursor, Windsurf, Cline/Roo, Codex, Gemini CLI,
Aider, Zed, ChatGPT/Claude Desktop, LM Studio/Jan/Msty; wiedza do I 2026. S/M/L = złożoność.)

**Agent:** web_search jako narzędzie (S — live search już jest w `responses_client`, tylko
ekspozycja w `tools.py`); widżet planu/TODO jak TodoWrite (S); lokalne background-agents
(M — składanka headless B1 + kolejka genjobs + worktree M17 + powiadomienia systemowe);
zbiorczy przegląd zmian per-hunk (M — uogólnienie MergeStore na głównego agenta; domyka
⬜ F5 z M13); mapa repo / indeks kodu (M/L — embeddingi są, ale po zdarzeniach, nie po kodzie);
pętla test-and-fix (S/M — hooki post_tool + zwrotka do historii); obrazy w composerze agenta
(S/M — wizja jest w czacie, brak w WS agenta); `.caeloignore` (S); weryfikacja wizualna
frontendu przez Playwright MCP z katalogu (M).

**Czat/hub:** artefakty HTML/mermaid/SVG w sandboxowanym iframe (M — największy efekt „wow");
rewind/edycja wiadomości + regeneracja (M — dane lokalne w `useConversations`); auto-pamięć
użytkownika (M — embeddingi + store już są, brakuje ekstrakcji + UI); tryb Deep Research
(M — orkiestracja istniejących klocków; Grok ma to natywnie, hub Groka nie); porównanie modeli
side-by-side (S/M); **inni dostawcy LLM / modele lokalne** (M/L — strategicznie najważniejsze
długoterminowo wobec ryzyka single-provider xAI; `base_url`-override w cienkim
`responses_client` jest realny); globalne quick-ask okno (S/M); kontekst z ekranu (M).

**Git/GitHub:** recenzja PR przez `gh` (M — `gh` załatwia auth/API, `/review` już jest);
panel Git: commit UI/historia/blame w CodeMirror (M); opcjonalny auto-commit edycji agenta
na shadow-branchu à la Aider (S/M — git-worktree B12 już jest).

**Edytor:** inline Ctrl-K na zaznaczeniu z diff-em w miejscu (M — CodeMirror 6 ma API
dekoracji; sztandarowa funkcja Cursora); tab-autocomplete FIM (L — **xAI nie ma publicznego
endpointu FIM**, stan I 2026 — realne dopiero z modelem lokalnym); multi-root workspace
(L — dotyka serca sandboxa P0, ostrożnie).

**Platforma/dystrybucja (warunki sensownej publikacji):** auto-update (S/M — electron-updater
+ GitHub Releases); **podpisywanie binarek** (M — SmartScreen/AV vs PyInstaller; Azure Trusted
Signing); crash-reporting opt-in (S/M — przy single-maintainer to jedyne „QA w terenie");
onboarding first-run (S/M); konfigurowalne skróty + ściąga „?" (S); powiadomienia systemowe
(S — approval/koniec długiego runu); i18n w tym PL (M/L); a11y (M — łatwo się wyróżnić).

**Głos/media (Caelo mocne):** guzik „read aloud" przy wiadomości (S); domknięcie pętli
galeria → dalsza edycja konwersacyjna w czacie (S).

### 4.3 TOP-10 wg stosunku wartość/koszt

| # | Funkcja | Złożoność | Dlaczego |
|---|---|---|---|
| 1 | web_search w agencie | S | infrastruktura już jest; największa codzienna luka vs Claude Code/Gemini CLI |
| 2 | auto-update + code signing | S/M + M | warunek publikacji (priorytet wg SWOT); bez tego każdy release = tarcie + alerty AV |
| 3 | widżet planu/TODO agenta | S | mały koszt, duży skok zaufania przy długich przebiegach |
| 4 | katalog MCP one-click | S/M | maszyneria M16 gotowa; mnożnik (odblokowuje Playwright-MCP itd.) |
| 5 | artefakty HTML/mermaid/SVG w czacie | M | największy efekt „wow" dla huba; CSP przygotowane |
| 6 | recenzja PR przez `gh` | M | trend 2025/26 (Codex review, Bugbot); `/review` + `run_command` już są |
| 7 | rewind/edycja wiadomości czatu | M | standard każdego klienta czatu; zmiana odizolowana w rendererze |
| 8 | inline Ctrl-K w CodeMirror | M | najszybsza pętla edycji — wyróżnik Cursora |
| 9 | auto-pamięć użytkownika | M | personalizacja jak ChatGPT/Grok; embeddingi + store już istnieją |
| 10 | lokalne background-agents + powiadomienia | M + S | „fire-and-forget" ze składanki istniejących klocków |

**Tuż za podium:** pętla test-and-fix (S/M), `.caeloignore` (S), inni dostawcy LLM (M/L,
strategicznie #1 długoterminowo), onboarding (S/M). **Świadomie nie teraz:** tab-autocomplete
(brak FIM u xAI), multi-root (serce sandboxa), chmurowe agent-runnery (XL, sprzeczne z
local-first).

---

## 5. Rekomendowana kolejność działań

1. **Runda naprawcza P1 (1-2 dni):** walidacja `sid` (P1-A) · deny na wynikach grep/glob
   (P1-B) · pętla doczytująca LSP (P1-C) · strip data-URI z `GenJob.params`/listy (P1-D) ·
   `CAELO_CORE_DATA_DIR` + izolacja smoke (P1-E) · pięć frontendowych P1-F…J. Wszystkie są
   punktowe, bez zmian architektury. Po naprawie: re-run wszystkich suit + dopisać asercje
   regresyjne (traversal sid do `api_smoke`, short-read do `lsp_check`, izolacja do
   `_smoke_common`).
2. **Publikacja (wg SWOT — największe ryzyko):** remote na GitHub → pierwszy realny bieg CI
   (gitleaks na pełnej historii PRZED upublicznieniem!) → release z signing/auto-update (F1/F2
   z §4.2). Sama obecność remote zdejmuje ryzyko jedynej kopii na jednym dysku.
3. **Dokończenie weryfikacji LIVE:** sekcje D (głos), F (subagenci), G (MCP/headless/ACP/LSP),
   H (funkcje-widma — decyzja włącz/usuń), I (pakiety), J (cross-platform), K (terminal)
   z `PLAN_WERYFIKACJI_LIVE.md`.
   > **Aktualizacja (2026-06-19):** D/F/H/I + G-rdzeń (G1–G3/G5/G6) **zaliczone na żywo**; zostają tylko
   > G4/G7 (remote-MCP/ACP), J (mac/Linux), K (terminal). Aktualny stan: `PLAN_WERYFIKACJI_LIVE.md` (tabela wyników).
4. **Runda P2 „współbieżność i odzysk":** wyścigi genjobs/OAuth/lazy-init/RoleRegistry/MCP/LSP
   + zawężenie `except` w `load_json_or_backup`/`history_store` + maskowanie błędów WS +
   limity (`/fs/read`, `caelo-md`, `messages[]`, output-dir).
5. **Nowe funkcje wg TOP-10** (§4.3), zaczynając od pozycji S (web_search w agencie, plan
   widget, powiadomienia, read-aloud przy wiadomości).

---

*Analiza wykonana 2026-06-10 (Claude Code, rewizja wieloagentowa + testy). Pozycje „do
weryfikacji" wymagają potwierdzenia przed naprawą. Numeracja P1-A…J jest lokalna dla tego
dokumentu (nie koliduje z P0-1…P3-14 z rund napraw).*
