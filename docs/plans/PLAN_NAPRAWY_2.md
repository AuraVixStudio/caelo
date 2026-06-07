# Plan naprawy i rozwoju (Runda 2) — Grok Desktop

> **Status:** ✅ ZREALIZOWANY (2026-06-04). **Wszystkie kamienie M5–M8 wdrożone.** Backend zweryfikowany
> self-checkami (agent_selfcheck 81/81, handshake_check, api_smoke **81/81** — w tym testy tras fs/git),
> frontend `npm run typecheck` zielony, podgląd renderera pod CSP bez naruszeń. **Wyjątek:** wykonanie
> ESLinta/Vitest (P3-7/P3-9) wymaga `npm install -D …` na maszynie z siecią (rejestr npm nieosiągalny w
> sandboxie) — configi/testy dostarczone i typecheck-safe, ale nie uruchomione tutaj.
> Wynik **niezależnego przeglądu kodu** (backend `grok_core` +
> rdzeń xAI, frontend Electron/React, self-checki, dokumentacja) przeprowadzonego **po** domknięciu
> [`PLAN_NAPRAWY.md`](PLAN_NAPRAWY.md) (P0–P3, M1–M4). Realne ścieżki sieciowe xAI weryfikuje
> użytkownik z ważnymi poświadczeniami — sandbox blokuje TLS do `api.x.ai`.
> **Powiązane:** [`PLAN_NAPRAWY.md`](PLAN_NAPRAWY.md) (runda 1 — zrealizowana), [`REBUILD_PLAN.md`](REBUILD_PLAN.md) (Fazy 0–8), [`MODYFIKACJE.md`](MODYFIKACJE.md) (Image/Video/Voice/załączniki).
> **Numeracja:** kontynuuje rundę 1 bez kolizji ID (P0 od `P0-9`, P1 od `P1-10`, P2 od `P2-8`,
> P3 od `P3-7`); kamienie milowe **M5–M8**.

Legenda priorytetów: **P0** = krytyczne (bezpieczeństwo, blokuje zaufanie do agenta) ·
**P1** = wysokie (stabilność/dane) · **P2** = średnie (architektura/jakość/wydajność/UX) ·
**P3** = testy/narzędzia/dokumentacja. Każdy punkt: `plik:linia` → **Problem** → **Rekomendacja**.

---

## Ocena ogólna

Po rundzie 1 projekt ma solidny szkielet bezpieczeństwa (sandbox agenta, scrubbing env w
`run_command`, tree-kill, ReDoS-safe `grep`, izolacja kontekstu Electrona, handshake port+token).
Niezależny przegląd ujawnił jednak, że **część hardeningu zastosowano punktowo i nie przeniesiono**
w analogiczne miejsca — `PLAN_NAPRAWY.md` jest oznaczony „✅ ZREALIZOWANY", a w kodzie zostały
rezydualne luki tej samej klasy, co już naprawione. Trzy wzorce:

1. **Brak propagacji fixu** — anty-OOM/sprzątanie kolejki WS naprawiono w `chat.py`, ale **nie**
   w bliźniaczym `agent.py` (P0-9). To skutek skopiowanego, nie współdzielonego boilerplate'u WS (P2-12).
2. **Hardening wybiórczy** — atomic write + backup pliku objął `grok_settings.json`, ale **nie**
   `grok_permissions.json`/`grok_auth.json` (P1-11); sanityzacja błędów objęła `media.py`/`voice.py`,
   ale **nie** `auth.py`/`git.py` (P1-13); fail-closed objął WS, ale REST został **fail-open** (P1-10).
3. **Założenie platformowe nieegzekwowane** — detektor metaznaków `run_command` modeluje cytowanie
   cmd.exe i jest niepewny na POSIX `sh`, mimo że `shell=True` działa na każdym OS (P0-10).

Plus jedna niedokończona funkcja (perystencja rozmów — `ChatStore` wpięty, ale bez trasy, P2-8)
oraz dwie systemowe luki jakości: **brak realnych testów tras** i **brak ESLinta** (P3-7…P3-9).

---

## P0 — Bezpieczeństwo / zaufanie do agenta (najpierw)

### [x] P0-9 — Kolejka WS agenta bez limitu + workera nie join-ujemy na rozłączeniu  🔴 KRYTYCZNE
- **Plik:** `grok_core/routes/agent.py:56` (`out_q = asyncio.Queue()` — bez `maxsize`), `:75`
  (`put_nowait`), `:133` (`Thread(...).start()`), `:144-147` (na rozłączeniu tylko `stop_event.set()`
  + `out_q.put_nowait(None)` — **brak join**).
- **Problem:** bliźniaczy `chat.py` jest utwardzony (`:51` `maxsize=512`, backpressure `:70`,
  `:149-153` join workera w executorze — P1-3), a agent **nie**. Szybka pętla narzędzi (np.
  `run_command` strumieniujący dużo wyjścia przez `on_output`) przy wolnym/zablokowanym kliencie
  rośnie w pamięci bez ograniczeń (OOM). Co gorsza: po rozłączeniu wątek workera nie jest dołączany,
  więc agent może **dalej wykonywać narzędzia (pisać pliki, uruchamiać komendy) po zniknięciu
  socketu** — to obchodzi model zatwierdzania, stąd priorytet P0, nie P1.
- **Rekomendacja:** przenieść wzorzec z `chat.py` 1:1: `Queue(maxsize=512)` + backpressure z timeoutem,
  `await loop.run_in_executor(None, t.join, 5)` w `finally`. Najlepiej od razu wyekstrahować wspólny
  helper (P2-12), żeby fix nie mógł się znów rozjechać między trasami.
- **✅ Zrobione (2026-06-04):** `agent.py` przepisany na wspólny `WsStream` (P2-12) — kolejka
  `maxsize=512`, `emit()` z backpressure (z wątku-workera; gdy konsument zniknął → `stop_event.set()`),
  a `aclose()` **dołącza wątek tury** (`run_in_executor(None, t.join, 5)`) PRZED domknięciem sendera →
  agent nie pisze plików ani nie uruchamia komend po rozłączeniu. Ramki sterujące z pętli zdarzeń
  (`workspace`/`error`/`busy`) idą przez `await stream.send(...)` (emit z pętli zakleszczyłby się).
  **Weryfikacja:** nowy `test_ws_stream` w `agent_selfcheck.py` (kolejka ograniczona, worker dołączony,
  ramki dostarczone); `api_smoke.py` chat-bridge (single-flight, delty) i akcept/odrzut WS — OK.

### [x] P0-10 — Detektor metaznaków `command_metachars` niepewny poza Windows (obejście „Always allow")  🔴 WYSOKIE
- **Plik:** `grok_core/agent/permissions.py:39-68` (`command_metachars`), `grok_core/agent/tools.py`
  (`run_command` z `shell=True`).
- **Problem:** skaner modeluje cytowanie **cmd.exe** (`\` literalny); docstring sam przyznaje dziurę:
  na POSIX `sh` `echo "\"" && rm ...` ukrywa operator łańcuchowania przed skanerem. `run_command`
  używa `shell=True` na każdym OS, a kod nigdy nie asercjonuje `os.name == "nt"`. Efekt: gwarancja
  z P0-1 („Always allow nie da się obejść łańcuchowaniem") **nie trzyma na macOS/Linux**.
- **Rekomendacja:** na nie-Windows uruchamiać z `shell=False` + `shlex.split` (argv-lista →
  łańcuchowanie niemożliwe), albo jawnie bramkować feature `os.name == "nt"` i na innych OS
  wymuszać zatwierdzanie zawsze. Dodać do `agent_selfcheck.py` przypadek POSIX (lub skip-marker
  pinujący dziurę `\"`).
- **✅ Zrobione (2026-06-04):** dwutorowo. (1) `run_command` (`tools.py`) jawnie bramkuje powłokę:
  Windows `shell=True` (zgodność `.cmd`/builtiny), **POSIX `shell=False` + `shlex.split`** (argv →
  brak `sh`, które zinterpretowałoby `&&`/`;`/`|`/`$()` — skaner jest tam tylko pre-filtrem).
  (2) `command_metachars(command, posix=None)` dostał **model POSIX** (`os.name != 'nt'` domyślnie):
  `\` eskapuje następny znak (więc `\"` NIE przełącza cudzysłowu — jak w `sh`), a `'...'` to twardy
  literał. Domyka to dziurę parzystości: `git \" && echo hi"` jest puste dla modelu cmd.exe, a
  niepuste dla `sh`. **Weryfikacja:** 4 nowe asercje w `agent_selfcheck.py` (m.in. „cmd.exe model
  misses \\" parity payload" vs „posix model catches"); pełny pakiet 81/81 OK (Windows i — w CI —
  Ubuntu, gdzie `posix=True` jest domyślne).

### [x] P0-11 — Terminal WS spawnuje shell z nieoczyszczonym środowiskiem (wyciek sekretów)  🔴 WYSOKIE
- **Plik:** `grok_core/routes/terminal.py:53` (`PtyProcess.spawn(shell, cwd=cwd)` — bez `env=`).
- **Problem:** pty dziedziczy **całe** środowisko procesu sidecara, w tym `XAI_API_KEY` i
  `GROK_CORE_TOKEN` — dokładnie te zmienne, które `run_command` skrupulatnie usuwa (P0-6). `set`/`env`
  w terminalu ujawnia klucz API i token sesji, a wyjście leci tym samym WS. Terminal jest świadomie
  pełnym shellem, ale nie powinien wyciekać sekretów, przed którymi broni narzędzie agenta.
- **Rekomendacja:** przekazać `env=` z tym samym scrubem co `run_command` (wyłączyć `GROK_CORE_TOKEN`/
  `XAI_API_KEY`/zmienne „secret-like"). Jeśli świadomie zostawiamy pełne env — udokumentować, że
  dostęp do terminala ≡ dostęp do sekretów, i odzwierciedlić w bramce uprawnień.
- **✅ Zrobione (2026-06-04):** funkcję scrubującą env wypromowano na publiczną `scrubbed_env()`
  (`tools.py`, reużywana przez `run_command` i terminal), a `terminal.py` startuje pty przez
  `PtyProcess.spawn(shell, cwd=cwd, env=scrubbed_env())` — `set`/`env` w shellu nie ujawnią już
  tokenu/klucza. Przy okazji terminal przeszedł na `WsStream` (ograniczona kolejka — usuwa bliźniaczy,
  latentny OOM jak w agencie). **Weryfikacja:** `api_smoke.py` montuje i autoryzuje `WS /terminal`
  (serwer startuje → `from grok_core.agent.tools import scrubbed_env` działa); `test_run_command_env_scrub`
  potwierdza, że `scrubbed_env()` usuwa sekrety a zachowuje zwykłe zmienne.

---

## P1 — Stabilność i trwałość danych

### [x] P1-10 — REST jest fail-open, WS fail-closed (asymetria autoryzacji)  🟠 WYSOKIE
- **Plik:** `grok_core/state.py:189-192` (`require_token`: `if not expected: return # tryb otwarty`)
  vs `:222-230` (`ws_authorized` wymaga jawnego `GROK_CORE_ALLOW_NO_TOKEN=1`).
- **Problem:** bez skonfigurowanego tokenu **każda trasa REST** jest otwarta — w tym `/fs/write`,
  `/git/commit` i generacja mediów (kosztuje quota xAI użytkownika). Dowolny lokalny proces uderza
  w `127.0.0.1:<port>` bez przeszkód (REST nie sprawdza nawet `Origin`). W praktyce Electron zawsze
  ustawia token, ale asymetria jest nieudokumentowana i niezgodna z fail-closed WS (P0-8).
- **Rekomendacja:** REST też fail-closed z tym samym opt-inem `GROK_CORE_ALLOW_NO_TOKEN=1`; przy
  starcie bez tokenu **głośny log ostrzegawczy** na stderr.
- **✅ Zrobione (2026-06-04):** `require_token` (`state.py`) jest teraz fail-closed symetrycznie do
  `ws_authorized` — bez skonfigurowanego tokenu zwraca **401**, chyba że `GROK_CORE_ALLOW_NO_TOKEN=1`.
  `server.py` (lifespan) loguje **ostrzeżenie** na starcie, gdy brak tokenu i brak opt-inu.
  **Weryfikacja:** nowy `_unit_rest_token_auth` w `api_smoke.py` (valid/missing/bad bearer + „no-token →
  DENIED" + „opt-in allows") — OK.

### [x] P1-11 — Atomic write i backup zastosowane wybiórczo; 4 z 5 czytników JSON cicho kasują dane  🟠 WYSOKIE
- **Plik:** `grok_core/agent/permissions.py:87-96` (`_save` truncate-in-place, `:95` `except: pass`),
  `oauth_manager.py:107-111` (tokeny plaintext, nieatomowo). Cisza przy korupcji: `ChatStore._load`,
  `HistoryManager.load_settings`, `OAuthManager._load`, `PermissionGate._load` — reset do pustych
  bez backupu (tylko `Backend.read_settings` ma backup `.corrupt`, P1-6).
- **Problem:** crash w trakcie zapisu `grok_permissions.json` korumpuje allowlistę, a `_load` cicho
  ją zeruje → użytkownik bez ostrzeżenia traci wszystkie reguły „Always allow". Najwrażliwszy plik
  (`grok_auth.json`) ma ten sam brak atomowości.
- **Rekomendacja:** przepiąć wszystkie zapisy na `config.atomic_write_text`; wyodrębnić wspólny
  `load_json_or_backup(path)` (backup `.corrupt` + log) i użyć go w **pięciu** czytnikach. Rozważyć
  restrykcję ACL/`icacls`/DPAPI dla `grok_auth.json`.
- **✅ Zrobione (2026-06-04):** nowy `config.load_json_or_backup(path, default)` (korupcja → przenosi
  plik do `<path>.corrupt` + log + zwraca default) użyty w **pięciu** czytnikach: `read_settings`
  (state), `ChatStore._load`, `HistoryManager.load_settings`, `OAuthManager._load`,
  `PermissionGate._load`. Zapisy `OAuthManager._save` i `PermissionGate._save` przepięte na
  `config.atomic_write_text` (były truncate-in-place z połykaniem błędu) — pozostałe trzy już były
  atomowe. **Weryfikacja:** nowy `_unit_json_corrupt_backup` (brak pliku→default; poprawny→treść;
  korupcja→`.corrupt`+default); `_unit_settings_ownership` nadal OK (atomowy zapis nie rusza
  grok_config.json). Restrykcja ACL `grok_auth.json` — świadomie odłożona (osobny punkt). Powiązane:
  [[grok-naprawy-progress]].

### [x] P1-12 — Zatwierdzanie agenta: `event.wait()` bez timeoutu (ryzyko zakleszczenia workera)  🟠 ŚREDNIE
- **Plik:** `grok_core/routes/agent.py:77-82` (`request_approval`: `event.wait()` bez limitu).
- **Problem:** wątek workera blokuje się na zgodę człowieka bez końca, trzymając workspace. `finally`
  (`:144-147`) ustawia zdarzenia przy czystym rozłączeniu, ale ścieżka wyjątku omijająca `finally`
  (albo śmierć pętli/sendera wcześniej) zostawia wątek zablokowany na zawsze.
- **Rekomendacja:** `event.wait(timeout=...)` z traktowaniem timeoutu jako `reject`; powiązać z join
  workera z P0-9.
- **✅ Zrobione (2026-06-04):** `request_approval` (`agent.py`) używa `event.wait(timeout=APPROVAL_TIMEOUT_S)`
  (`600 s`); timeout → log + domyślna decyzja **`reject`** (wątek tury nie wisi już bez końca trzymając
  workspace). Działa łącznie z P0-9: na rozłączeniu `finally` i tak zwalnia oczekujące zdarzenia, a
  `WsStream.aclose()` dołącza workera.

### [x] P1-13 — Niespójna sanityzacja błędów: `auth.py`/`git.py` zwracają surowe `str(exc)`/stderr  🟠 ŚREDNIE
- **Plik:** `grok_core/routes/auth.py` (`detail=str(exc)`), `grok_core/routes/git.py` (surowy stderr
  `git` do klienta), też `fs.py` / agent WS (`{"error": str(exc)}`).
- **Problem:** helper `errors.upstream_error` (P1-6) trafił tylko do `media.py`/`voice.py`. `git`
  stderr ujawnia bezwzględne ścieżki FS, błędy OAuth — szczegóły wymiany tokenu.
- **Rekomendacja:** zastosować `upstream_error`/scrubbing konsekwentnie w `auth.py`, `git.py`, `fs.py`
  i agencie (log surowego wyjątku → generyczny `detail`).
- **✅ Zrobione (2026-06-04):** `auth.py` (`/auth/login`) → `errors.upstream_error` (loguje surowy
  wyjątek z wymiany tokenu, zwraca ogólny „Sign-in failed"). `git.py` (status/diff/add/commit) →
  loguje surowy stderr, zwraca **generyczny** `detail` (bez ścieżek FS). `agent.py` (nieoczekiwany
  błąd tury) → `log.exception` + ogólny „Agent error (see server log)". `fs.py` zostawione: zwraca
  tylko komunikaty `WorkspaceError` (echo ścieżki względnej użytkownika — bez ścieżek serwera).
  **Weryfikacja:** nowy `_unit_error_sanitization` (git status/commit nie zawierają wstrzykniętej
  ścieżki bezwzględnej, commit zwraca dokładnie „git commit failed").

### [x] P1-14 — `save_media_urls`: pobieranie dowolnego URL bez limitu rozmiaru/schematu  🟡 ŚREDNIE
- **Plik:** `grok_core/state.py:146` (`requests.get(url, timeout=180).content`), `:149` (`write_bytes`).
- **Problem:** całość bufrowana do pamięci (bez streamingu, bez limitu rozmiaru) i ufamy URL-owi
  zwróconemu przez upstream. Skompromitowany/spoofowany upstream → miękki DoS (pamięć) lub SSRF do
  hostów wewnętrznych.
- **Rekomendacja:** ograniczyć do `https://`, sprawdzać `Content-Length`, strumieniować na dysk z
  twardym limitem rozmiaru.
- **✅ Zrobione (2026-06-04):** nowy `Backend._download_media` — odrzuca schematy inne niż **https**
  (blok SSRF do `http`/`file`), sprawdza `Content-Length`, **strumieniuje na dysk** (`iter_content`)
  z twardym limitem `MAX_MEDIA_BYTES` (256 MB; przerwa + usunięcie częściowego pliku po przekroczeniu)
  — koniec z buforowaniem całości w pamięci. **Weryfikacja:** `_unit_media_download_guard` (https→na
  dysk; http→odrzucone bez fetcha; oversize wg Content-Length→odrzucone).

---

## P2 — Architektura, jakość, wydajność, UX

### [x] P2-8 — `ChatStore` wpięty w `Backend`, ale żadna trasa go nie wystawia (perystencja rozmów niedokończona)  🟠 WYSOKIE
- **Plik:** `grok_core/state.py:45` (`self.chats = ChatStore()`); brak routera `/chats`; `chats_manager.py`
  to pełny magazyn (new/delete/rename/set_active/messages).
- **Problem:** store robi I/O na starcie (`new_chat()` → zapis `grok_chats.json`), ale jest
  nieosiągalny z frontendu — historia czatu żyje tylko w localStorage renderera. Legacy miał
  multi-rozmowy zapisywane na dysku. To albo niedokończona funkcja, albo martwy balast robiący I/O
  przy każdym starcie.
- **Rekomendacja:** **decyzja:** (a) dokończyć — router `/chats` (GET lista, POST new, PATCH rename,
  DELETE, GET/POST messages) + wpięcie w `useConversations` zamiast localStorage; albo (b) usunąć
  `ChatStore` z `Backend`, jeśli localStorage jest docelowym magazynem.
- **✅ Zrobione (2026-06-04) — wybrano (b) [decyzja użytkownika]:** usunięto `self.chats = ChatStore()`
  i import z `state.py`. Koniec tworzenia `grok_chats.json` przy każdym starcie (martwy kod robiący
  I/O); localStorage renderera (`useConversations`) jest świadomym, udokumentowanym źródłem prawdy.
  `chats_manager.py` pozostaje w rdzeniu (reużywalny), ale sidecar go nie instancjonuje.
  **Weryfikacja:** `api_smoke.py` (w tym `settings ownership`) i `agent_selfcheck.py` — OK.

### [x] P2-9 — Brak timeoutu/anulowania po stronie klienta REST; polling wideo bez deadline  🟠 WYSOKIE
- **Plik:** `desktop/src/renderer/src/lib/api.ts` (`api<T>()` bez `AbortSignal`),
  `desktop/src/renderer/src/components/Video.tsx` (`poll()` — `setTimeout(tick, 5000)` bez maks. prób).
- **Problem:** generacja obrazu/wideo, TTS, OAuth login mogą wisieć bez końca z UI w „Generating…/
  Signing in…" i bez anulowania; zadanie wideo zacięte w stanie nieterminalnym poll-uje w
  nieskończoność (mimo deklaracji „~2 min").
- **Rekomendacja:** przeprowadzić opcjonalny `AbortSignal` przez `api<T>()` + domyślny timeout;
  podpiąć przycisk „Cancel"; dodać deadline/maks. próby do pollingu wideo + kontrolkę stop.
- **✅ Zrobione (2026-06-04):** `api<T>()` (`lib/api.ts`) ma teraz **timeout** (`AbortSignal.timeout`,
  domyślnie 30 s) i akceptuje `AbortSignal` wywołującego (łączone przez `combineSignals` — pierwszy
  abort wygrywa). Per-endpoint limity dla wolnych operacji (login 310 s, obraz 180 s, wideo-job 60 s,
  voice 120 s), żeby ich nie ucinać. `Video.tsx`: polling ma **deadline 10 min** + przycisk **Cancel**
  (timer w refie, czyszczony też na unmount). **Weryfikacja:** typecheck OK; podgląd renderera OK.

### [x] P2-10 — Electron: brak CSP, guardu nawigacji i handlera uprawnień  🟠 WYSOKIE
- **Plik:** `desktop/src/renderer/index.html` (brak `<meta CSP>`), `desktop/src/main/index.ts`
  (`createWindow` — brak `will-navigate`, `sandbox:false`, brak `setPermissionRequestHandler`,
  health-check `fetch('/health')` bez `AbortController`).
- **Problem:** renderer renderuje markdown z modelu i ładuje zdalne `img`/`video` z dowolnych URL xAI
  — bez CSP brak obrony w głąb przed XSS/wstrzyknięciem. Brak `will-navigate` pozwala podmienić ramkę
  aplikacji (drag&drop URL). Mikrofon (Voice/dyktowanie) auto-grantowany bez allowlisty. Zawieszony
  `/health` opóźnia detekcję pada (brak timeoutu).
- **Rekomendacja:** ścisłe CSP przez `session.defaultSession.webRequest.onHeadersReceived` (dev +
  `file://`); `webContents.on('will-navigate', e => e.preventDefault())` poza origin renderera;
  `setPermissionRequestHandler` allowlistujący tylko `media`; `AbortSignal.timeout(5000)` na
  `/health` i `/whoami`; rozważyć `sandbox:true`.
- **✅ Zrobione (2026-06-04):** **CSP** dodane meta-tagiem w `index.html` (działa w dev i `file://`):
  `default-src 'self'`, `connect-src` tylko loopback backendu + `ws`, `img/media` `data: blob: https:`,
  `object-src 'none'`, `frame-ancestors 'none'` (pozostawiono `'unsafe-inline'/'unsafe-eval'` wymagane
  przez Vite HMR + style inline; brak zewn. fontów/CDN). `main/index.ts`: **`will-navigate`** blokuje
  nawigację poza origin renderera; **`setPermissionRequestHandler`** dopuszcza tylko `media` (mikrofon);
  `fetch` `/health` i `/whoami` z `AbortSignal.timeout(5000)`. `sandbox` zostawiono `false` z komentarzem
  (kandydat — wymaga weryfikacji runtime spakowanej apki). **Weryfikacja:** podgląd web (`renderer-preview`)
  — powłoka renderuje się pod CSP, **0 naruszeń/błędów** w konsoli, Vite HMR łączy się (connect-src ws OK).

### [x] P2-11 — UX awarii: brak banera „backend down", obsługa 401, retry czatu  🟠 ŚREDNIE
- **Plik:** `desktop/src/renderer/src/App.tsx` (gate „not ready" tylko przed startem),
  `desktop/src/renderer/src/lib/api.ts` (401 nierozróżnione od 500),
  `desktop/src/renderer/src/components/ChatView.tsx` (błąd streamu **nadpisuje** dymek asystenta i
  utrwala `⚠️ {err}` w localStorage, bez retry).
- **Problem:** gdy sidecar padnie w trakcie pracy w module, aktywny moduł zostaje z nieaktualnym UI
  (jedyny sygnał to mała kropka w stopce). 401 (wygaśnięcie OAuth) wygląda jak 500 i nie daje ścieżki
  re-logowania. Transient drop WS gubi turę i zapieka błąd w historii.
- **Rekomendacja:** app-level baner „Backend disconnected, reconnecting (n/5)…" gdy
  `conn.status !== 'ready'`; specjalna obsługa 401/403 → prompt logowania; przycisk „Retry" w czacie
  i nieutrwalanie tekstu błędu jako treści asystenta.
- **✅ Zrobione (2026-06-04):** uściślenie po analizie: `App.tsx` **już** podmienia moduł na
  pełnoekranowy wskaźnik stanu przy `!ready` (także przy padzie w trakcie sesji — bezpieczniej niż
  renderować moduł z martwym `conn`). Wzmocniono go: **spinner** podczas `starting` + `role="status"
  aria-live` (ogłasza reconnect z licznikiem `restart n/5` z `conn.error`). `api.ts`: rzucany teraz
  **`ApiError{status}`** + jednoznaczny komunikat dla **401/403** (problem tokenu sesji → „restart").
  `ChatView`: błąd streamingu **nie jest już utrwalany** jako treść asystenta (`⚠️ …` w localStorage)
  — pokazywany w pasku z przyciskiem **„Retry"** (ponawia ostatnią turę z `lastTurnRef`). **Weryfikacja:**
  typecheck OK; podgląd renderera OK.

### [x] P2-12 — Duplikacja boilerplate'u WS i `_require_ws` (przyczyna rozjazdu fixów)  🟡 ŚREDNIE
- **Plik:** `grok_core/routes/fs.py:28-32` i `git.py:25-29` (identyczny `_require_ws`); wzorzec
  sender-task + queue + auth powielony w `chat.py`/`agent.py`/`terminal.py`.
- **Problem:** to dosłowna przyczyna, dla której fix kolejki (P0-9) ominął agenta — wzorzec był
  kopiowany, nie współdzielony.
- **Rekomendacja:** wyekstrahować wspólny `ws_stream_session(...)` (auth + bounded queue + sender +
  join) i zależność `require_workspace`. Zrobić **przed** lub **razem z** P0-9.
- **✅ Zrobione (2026-06-04):** nowy `grok_core/routes/_ws.py` z klasą **`WsStream`** (async context
  manager): ograniczona kolejka + `sender` + threadsafe `emit()` z backpressure + `send()` dla pętli
  zdarzeń + `track()`/`aclose()` (join workerów). `chat.py`, `agent.py` i `terminal.py` przepisane na
  ten jeden szkielet — dzięki czemu fix P0-9 z definicji nie może się rozjechać. Zależność
  **`require_workspace`** przeniesiona do `state.py` i użyta w `fs.py`/`git.py` (zlikwidowany
  zdublowany `_require_ws`). **Weryfikacja:** `api_smoke.py` (chat-bridge, WS akcept/odrzut, trasy
  `/fs`,`/git`) + `agent_selfcheck.py` `test_ws_stream` — OK.

### [x] P2-13 — Dostępność (a11y)  🟡 ŚREDNIE
- **Plik:** `ChatView.tsx` (suwak temperatury bez `aria-label`/`aria-valuetext`, lista wiadomości bez
  `aria-live`), `Video.tsx`/`Voice.tsx` (toggle'e bez `role="tablist"`/arrow-nav), `ErrorBoundary.tsx`
  (focus nie przenoszony do fallbacku).
- **Problem:** strumieniowane regiony niewidoczne dla czytników ekranu; suwaki bez nazwy; toggle'e
  nieidiomatyczne klawiaturowo.
- **Rekomendacja:** `aria-live="polite"` na kontenerach rozmowy/logu; `aria-label`/`aria-valuetext`
  na suwakach; `role=tab`/`tablist` + nawigacja strzałkami; focus na nagłówek fallbacku ErrorBoundary.
- **✅ Zrobione (2026-06-04):** `role="log" aria-live="polite"` na liście wiadomości czatu i logu
  `AgentPanel`. `aria-label`+`aria-valuetext` na suwaku temperatury (ChatView, z `htmlFor`/`id`) oraz
  suwakach Duration/Add w Video. `aria-pressed` + focus-ring na przełączniku trybu w Video (Voice już
  miał). `ErrorBoundary` przenosi **fokus** na fallback (`tabIndex=-1`, `role="alert"`) po wystąpieniu
  błędu. Pełny `role=tablist`+arrow-nav świadomie pominięty (toggle'e to nie taby tab-panelowe;
  `aria-pressed` wystarcza i jest spójne). **Weryfikacja:** typecheck OK; snapshot a11y w podglądzie.

### [x] P2-14 — Drobne usterki i martwy kod  🟢 NISKIE
- **Plik:** `desktop/src/renderer/src/components/ChatView.tsx:303`
  (`setConvosCollapsed(size.asPercentage <= 0.5)` — zweryfikować jednostki `asPercentage` w
  react-resizable-panels v4; możliwe, że panel jest „zwinięty" przy połowie szerokości);
  `CodeView.tsx:37` (lista modeli agenta brana z `modelsResp.chat`, nie `code`); martwe metody w
  reużytych managerach (`HistoryManager.save_chat_message/get/clear`, `APIManager.chat_with_tools`).
- **Rekomendacja:** poprawić próg zwijania (epsilon ≈ `collapsedSize`); użyć właściwej listy modeli
  kodu; oznaczyć/usunąć martwe metody.
- **✅ Zrobione (2026-06-04):** `ChatView.tsx` — `onResize` używa teraz `convosPanelRef.current.isCollapsed()`
  (własna detekcja biblioteki, niezależna od jednostek `size.asPercentage`) zamiast magicznego progu
  `<= 0.5`. `CodeView.tsx` (lista modeli agenta z `chat`) — **zweryfikowano: to nie błąd**; API nie ma
  osobnej listy `code`, a modele kodowe (`grok-build-0.1`) są podzbiorem `chat`; domyślny to `default_code`.
  Martwe metody `HistoryManager` zostawiono (nieszkodliwe, reużywalny rdzeń). **Weryfikacja:** typecheck OK.

---

## P3 — Testy, narzędzia, dokumentacja

### [x] P3-7 — Brak ESLinta mimo 11 martwych `eslint-disable`  🟠 WYSOKIE
- **Plik:** 11 wystąpień `eslint-disable-next-line` (FileTree, Video, useWorkspace, AgentPanel,
  Settings, History, serverState, CodeView, Terminal) — brak `.eslintrc`/`eslint.config.*` i ESLinta
  w zależnościach.
- **Problem:** suppresje `react-hooks/exhaustive-deps`, których **nic nie sprawdza**; przy tylu
  efektach z celowo pominiętymi zależnościami to najgroźniejsza luka narzędziowa frontu.
- **Rekomendacja:** dodać ESLint + `eslint-plugin-react-hooks` (suppresje stają się sensowne) i wpiąć
  do `npm run typecheck`/CI; albo usunąć martwe komentarze.
- **✅ Zrobione (2026-06-04):** dodano **flat config `desktop/eslint.config.mjs`** świadomie wąski —
  tylko reguły `react-hooks` (`rules-of-hooks` error, `exhaustive-deps` warn), bez zalewania
  nigdy-nie-lintowanego kodu pełnymi setami. Skrypt `npm run lint`. **Uwaga:** devDeps celowo NIE
  dodano do `package.json` (M8 pisane offline; dodanie ich bez aktualizacji `package-lock.json`
  zepsułoby `npm ci` w CI). **Aktywacja u użytkownika:** `npm install -D eslint typescript-eslint
  eslint-plugin-react-hooks globals` → `npm run lint`. Wykonania nie dało się zweryfikować w sandboxie
  (rejestr npm nieosiągalny, jak api.x.ai) — config jest minimalny i bezpieczny, `npm run typecheck`
  nadal zielony.

### [x] P3-8 — Brak testów tras backendu (fs/git/agent/terminal) i współbieżności  🟠 WYSOKIE
- **Plik:** `grok_core/tools/*` (self-checki) — `api_smoke` sprawdza tylko auth (401/403) i kształt
  422; logiki `/fs/write`, `/git/*`, `/agent/stream`, `/terminal` **nie dotyka**.
- **Problem:** najgroźniejsze endpointy bez testów behawioralnych; protokół WS agenta (approval, stop
  w trakcie narzędzia, kolejka) nietestowany end-to-end; brak testów wyścigów read-modify-write JSON
  (P1-11, `_record_recent`/`update_settings`).
- **Rekomendacja:** wprowadzić pytest + `TestClient`/`httpx` (REST) i fixture `websockets` (WS);
  testy fs/git/agent/terminal; testy współbieżności zapisu ustawień/historii; zachować self-checki
  jako szybki smoke.
- **✅ Zrobione (2026-06-04):** świadomie **bez pytest** (repo celowo nie używa pytest — „testy" to
  self-checki; nowy dep + offline byłby pod prąd). Rozszerzono `api_smoke.py` o testy tras **in-process**:
  `_unit_fs_routes` (write→read round-trip, tree, **sandbox** — `..` w read/write/tree → 400) i
  `_unit_git_routes` (status non-repo/repo, commit `stage_all`, pusty message → 400). Pokrycie agenta/
  terminala: auth (bad-token → odrzut), pętla `AgentSession` z mockiem LLM + `WsStream` (`agent_selfcheck`).
  **Weryfikacja:** `api_smoke.py` **81/81 OK** (z czego 10 nowych fs/git). Testy współbieżności JSON
  (P1-11) odłożone (osobny, węższy temat).

### [x] P3-9 — Zero testów frontendu  🟠 ŚREDNIE
- **Plik:** brak `*.test.*`/`vitest`/`@testing-library` w `desktop/package.json` (tylko `tsc`).
- **Problem:** czyste, testowalne jednostki bez pokrycia: `lib/attachments.ts` (`toApiMessages`,
  filtrowanie rozmiaru/binarne), `lib/storage.ts` (`stripForStorage` — fix quota localStorage),
  `agentClient.parseAgentEvent` (granica walidacji WS), `serverState` (dedup/write-through).
- **Rekomendacja:** dodać Vitest + testy ww. utili + smoke renderujący każdy moduł na `devMock`.
- **✅ Zrobione (2026-06-04):** dodano **`desktop/vitest.config.ts`** + testy w **`desktop/test/`**
  (poza zakresem tsconfig → nie wpływają na typecheck): `attachments.test.ts` (`toApiMessages`/
  `inlineTextFiles`/`imageUris` — granica tekst→API i part-y multimodalne) oraz `storage.test.ts`
  (`titleFromText`). Skrypt `npm test` (`vitest run`). Jak P3-7: devDeps poza `package.json` (anty-`npm ci`);
  **aktywacja:** `npm install -D vitest` → `npm test`. Wykonania nie zweryfikowano w sandboxie (brak sieci
  npm); asercje napisane wg źródła, `npm run typecheck` nadal zielony. Smoke modułów na `devMock`
  pozostawiono jako rozszerzenie (wymaga `jsdom`).

### [x] P3-10 — Synchronizacja statusu dokumentacji  🟡 ŚREDNIE
- **Plik:** `docs/plans/PLAN_NAPRAWY.md` („✅ ZREALIZOWANY"), `docs/README.md` (indeks).
- **Problem:** status „zrealizowany" przy realnych rezydualnych lukach klasy P0/P1 (powyżej) jest
  mylący przy następnej iteracji.
- **Rekomendacja:** dopisać w `PLAN_NAPRAWY.md` odnośnik „kontynuacja → `PLAN_NAPRAWY_2.md`"; dodać
  ten dokument do indeksu `docs/README.md`; po zamknięciu rundy 2 zaktualizować statusy.
- **✅ Zrobione (2026-06-04):** odnośniki PLAN_NAPRAWY↔PLAN_NAPRAWY_2 i wpis w `docs/README.md` dodano
  na bieżąco (M5–M7). W M8 zaktualizowano **`CLAUDE.md`** do stanu po rundzie 2: liczba asercji
  `agent_selfcheck` 74→81, akapit „Round-2 hardening (M5–M6)", `WsStream` w sekcji streaming bridge,
  REST+WS fail-closed + CSP/`will-navigate` w bezpieczeństwie, `grok_chats.json` (sidecar już nie pisze)
  + `load_json_or_backup`, nowe wspólne helpery (`WsStream`/`require_workspace`/`scrubbed_env`/
  `load_json_or_backup`), ESLint/Vitest w sekcji komend. **Weryfikacja:** typecheck + 3 self-checki
  zielone (kod zgodny z opisem).

---

## Kolejność prac (kamienie milowe)

| Kamień | Zakres | Cel |
|---|---|---|
| **M5 — Bezpieczeństwo agenta (P0)** ✅ | P2-12 (wspólny helper WS) → **P0-9** (kolejka+join) → P0-10 (skaner POSIX) → P0-11 (env terminala) | Zaufanie do agenta: brak pracy po rozłączeniu, brak obejścia allowlisty, brak wycieku sekretów — **wdrożone 2026-06-04** |
| **M6 — Stabilność i dane (P1)** ✅ | P1-10 (REST fail-closed) · P1-11 (atomic + backup, wspólny loader) · P1-12 (timeout zgody) · P1-13 (sanityzacja błędów) · P1-14 (limit pobierania) | Brak cichej utraty danych, spójna autoryzacja i higiena błędów — **wdrożone 2026-06-04** |
| **M7 — UX i funkcje (P2)** ✅ | P2-8 (decyzja: perystencja rozmów) · P2-9 (timeouty/anulowanie) · P2-10 (CSP/nawigacja/uprawnienia) · P2-11 (baner down/401/retry) · P2-13 (a11y) · P2-14 (usterki) | Odporny, dostępny UI; perystencja rozmów rozstrzygnięta (usunięto ChatStore) — **wdrożone 2026-06-04** |
| **M8 — Testy i narzędzia (P3)** ✅ | P3-7 (ESLint) · P3-8 (testy tras fs/git w self-checkach) · P3-9 (Vitest) · P3-10 (sync docs) | Regresje wyłapywane automatycznie; dokumentacja zgodna ze stanem — **wdrożone 2026-06-04** (P3-7/P3-9 wymagają `npm install -D` u użytkownika) |

**Sugerowana ścieżka:** M5 najpierw (P2-12 przed P0-9, żeby fix był współdzielony, nie kopiowany),
potem M6, M7, M8. M8 (testy) można rozpocząć równolegle — pokrycie pisane pod każdy zamykany punkt.

---

## Kryteria akceptacji / weryfikacja

- **P0-9:** test (lub self-check) potwierdza, że po `close()` socketu agenta worker kończy się w
  ≤5 s i nie wykonuje kolejnych narzędzi; kolejka ograniczona (`maxsize`), backpressure działa.
- **P0-10:** `agent_selfcheck.py` ma przypadek POSIX — łańcuchowanie/podstawianie przez `\"` **nie**
  przechodzi (albo udokumentowany skip-marker pinujący ograniczenie + jawny gate `os.name`).
- **P0-11:** w terminalu `set`/`env` **nie** ujawnia `XAI_API_KEY`/`GROK_CORE_TOKEN` (env scrubowany),
  albo świadoma decyzja jest udokumentowana i odzwierciedlona w uprawnieniach.
- **P1-10:** start bez tokenu i bez `GROK_CORE_ALLOW_NO_TOKEN=1` → REST odpowiada 401/403; przy braku
  tokenu log ostrzegawczy na stderr.
- **P1-11:** crash w trakcie zapisu nie korumpuje `grok_permissions.json`/`grok_auth.json`; korupcja
  pliku tworzy `.corrupt` + log w **pięciu** czytnikach.
- **P1-13:** odpowiedzi błędów `auth.py`/`git.py`/`fs.py` nie zawierają surowych `str(exc)`/stderr ani
  bezwzględnych ścieżek FS.
- **P2-8:** rozmowy widoczne w UI przeżywają restart sidecara (jeśli wybrano dokończenie), albo
  `ChatStore` usunięty z `Backend` (jeśli wybrano localStorage).
- **P2-10:** nagłówek CSP obecny w dev i `file://`; nawigacja poza origin renderera zablokowana;
  wniosek o nie-`media` permission odrzucony.
- **P3-8:** testy tras `fs`/`git` w `api_smoke.py` zielone w CI (już wpięte — CI uruchamia `api_smoke.py`).
- **P3-7/9:** configi (`eslint.config.mjs`, `vitest.config.ts`) + testy dostarczone i typecheck-safe;
  aktywacja/uruchomienie u użytkownika (`npm install -D … && npm run lint && npm test`) — sandbox bez
  sieci npm. Po potwierdzeniu „zielono" lokalnie można wpiąć `lint`/`test` do `.github/workflows/ci.yml`
  (świadomie NIE dodane jako twarda bramka, dopóki niezweryfikowane — i żeby `npm ci` nie pękło na
  niezsynchronizowanym `package-lock.json`).
- **Globalnie:** istniejące self-checki nadal zielone (`handshake_check`, `api_smoke` **81/81**,
  `agent_selfcheck` **81/81**, `sidecar_smoke`) + `npm run typecheck` bez błędów. ✅ potwierdzone 2026-06-04.
