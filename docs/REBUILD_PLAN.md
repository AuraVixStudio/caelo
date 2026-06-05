# Plan przebudowy: „AI Studio Pro" → desktopowa aplikacja Grok w stylu Claude Code / Codex

> **Status:** Fazy 0–8 WYKONANE (2026-06-03). Legacy customtkinter **USUNIĘTY z repo (2026-06-04)** —
> Faza 8 domknięta; stara apka zachowana jako kopia zewnętrzna (poza repo).
> **Data:** 2026-06-02 (utworzenie), 2026-06-03 (Fazy 0–8)
> **Dokument źródłowy decyzji:** ten plik jest źródłem prawdy dla **Faz 0–8** (poniżej — zapis historyczny).
>
> **Po Fazach 0–8** projekt rozwinął się o nadbudowę (moduł **Voice**, scalenie Generator+Edit → **Image**,
> **edycja/przedłużanie wideo**, załączniki w Chat/Code) oraz hardening — patrz
> **[`MODYFIKACJE.md`](MODYFIKACJE.md)** (żywa specyfikacja modułów Image/Video/Voice/załączniki)
> i **[`PLAN_NAPRAWY.md`](PLAN_NAPRAWY.md)** (P0–P3). Aktualny stan modułów/bibliotek/endpointów zebrano
> w **§13 „Faza 9"** na końcu. Uwaga: edytor to **CodeMirror 6**, nie Monaco (decyzja w §10f); UI to
> **Tailwind v4** (nie shadcn/Radix), a stan serwera trzyma własny lekki cache (nie zustand/react-query).

---

## 1. Cel

Przebudowa obecnej aplikacji (Python + customtkinter) na nowoczesną aplikację desktopową, która:

1. **Zachowuje wszystkie obecne moduły** — Chat, Generator, Edit, Video, History, Settings.
   *(W nadbudowie: Generator+Edit scalone w **Image**, dodano **Voice** — aktualny zestaw w §13.)*
2. **Dodaje agentowy moduł programistyczny** z dostępem do lokalnych plików (czytanie/edycja, uruchamianie poleceń, drzewo projektu, diff, zatwierdzanie zmian) — tak jak Claude Code i Codex.

---

## 2. Zatwierdzone decyzje

| Decyzja | Wybór | Status |
|---|---|---|
| Stack frontendu | **Electron + React/TypeScript** | ✅ potwierdzone |
| Stack backendu | **Python FastAPI (sidecar)** — reużycie obecnego kodu | ✅ potwierdzone |
| Repozytorium | **Monorepo + `git init`** (`/desktop` + `/grok_core`) | ✅ potwierdzone |
| Silnik agenta | **Własna pętla agenta** na xAI API (Grok) | ✅ potwierdzone |
| Domyślny model kodowania | **`grok-build-0.1`**, z **płynną/łatwą zmianą modelu jak w Claude** | ✅ potwierdzone |
| Uprawnienia | **Zatwierdzanie zmian** (diff/komenda przed zapisem/wykonaniem) | ✅ potwierdzone |
| UI modułu Code | **Pełny mini-IDE** (drzewo + edytor + terminal + git + czat agenta) | ✅ potwierdzone |
| Terminal | **pty po stronie Pythona (`pywinpty`)** — nie node-pty | ✅ potwierdzone |

**Kluczowa zasada migracji:** reużywamy dojrzały kod Pythona (OAuth PKCE, streaming UTF-8, function-calling, media) jako **backend**; w JS/TS budujemy tylko nowy frontend + powłokę Electron. Logiki xAI nie przepisujemy od zera.

---

## 3. Architektura docelowa

```
┌─────────────────────────── Electron (proces główny) ───────────────────────────┐
│  • okno, menu, tray, cykl życia sidecara, IPC, auto-update                       │
│  • spawnuje i nadzoruje Python backend (health-check + restart)                  │
│  • przekazuje do frontendu: port + token sesji (handshake)                       │
│                                                                                   │
│   ┌──────────── preload (contextBridge) ────────────┐                            │
│   │  bezpieczny most: ipc, ścieżki, dialogi systemowe │                          │
│   └───────────────────────────────────────────────────┘                         │
│   ┌──────────────── Renderer: React + TS ───────────────────────────────────┐   │
│   │  Routy/moduły: Chat | Code | Generator | Edit | Video | History | Settings│  │
│   │  Biblioteki: Tailwind+shadcn/Radix, Monaco (edytor+diff), xterm.js,       │  │
│   │              react-query, zustand (stan), websocket client                │  │
│   └──────────────────────────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────────────────────┘
                    │  HTTP (REST) + WebSocket (streaming)  — tylko 127.0.0.1 + token
                    ▼
┌─────────────────────── Python backend „grok-core" (FastAPI/uvicorn) ────────────┐
│  Reużycie:  api_manager · oauth_manager · chats_manager · history_manager · config│
│  Nowe:      agent/ (pętla + narzędzia + uprawnienia + sandbox + workspace)        │
│  API:       /chat /agent(ws) /fs /git /terminal(ws) /models /auth /images /video  │
│  Bezpieczeństwo: bind 127.0.0.1, losowy port, token, sandbox ścieżek              │
└───────────────────────────────────────────────────────────────────────────────┘
                    │
                    ▼  Bearer (OAuth/API key) — wyłącznie do api.x.ai
              xAI / Grok API
```

**Dlaczego Electron (a nie Tauri):** Monaco + xterm.js + ekosystem Node działają od ręki; pakowanie Python-sidecara pod Windows jest dojrzałe (electron-builder + NSIS); zespół jest Python-owy, nie Rust-owy.

---

## 4. Frontend (Electron + React + TypeScript)

- **Scaffold:** `electron-vite` (Vite + React + TS); `electron-builder` do pakowania.
- **Wygląd „Claude/Codex":** Tailwind + shadcn/ui (Radix). Ciemny motyw zgodny z obecnymi `COLORS` (Deep Navy `#0f1323`, Indigo `#6366f1`) — przeniesienie design tokenów z `config.py` do `tokens.ts`.
- **Nawigacja:** lewy rail z modułami (zamiast obecnego top-nav).
- **Stan:** zustand (UI/sesja) + react-query (REST) + klient WebSocket (streaming czatu i agenta).
- **Moduły portowane (zachowane):**
  - **Chat** — streaming, załączniki (obraz + plik tekstowy), system prompt, temperatura, wklejanie obrazu (Ctrl+V), regeneracja, edycja wiadomości, eksport `.md`, render markdown + podświetlanie kodu (natywnie: `react-markdown` + Shiki/Monaco zamiast ręcznego taggingu w `CTkTextbox`).
  - **Generator / Edit / Video** — formularze + galeria wyników; drag&drop natywny (HTML5); auto-zapis przez backend.
  - **History** — lista generacji z `history_manager`.
  - **Settings** — OAuth xAI, klucz API, folder wyjściowy, wybór modeli, zarządzanie uprawnieniami agenta i workspace.

---

## 5. Backend (Python „grok-core", FastAPI)

Refaktoryzacja istniejących plików w pakiet serwisowy — **bez przepisywania logiki xAI**:

```
grok_core/
  server.py          # FastAPI app, lifespan, auth-token middleware, bind 127.0.0.1
  api_manager.py     # (reuse) klient xAI: images/video/chat/chat_with_tools/list_models
  oauth_manager.py   # (reuse) OAuth PKCE — bez zmian; callback server jak dziś
  chats_manager.py   # (reuse) magazyn rozmów
  history_manager.py # (reuse) historia mediów
  config.py          # (reuse+rozszerz) ścieżki, modele, OAuth, NEW: workspace/permissions
  agent/             # NOWE — silnik kodowania (rozdz. 6)
  routes/
    chat.py  agent.py  fs.py  git.py  terminal.py  auth.py  media.py  models.py
```

**Endpointy (szkic):**
- `POST /auth/login`, `/auth/logout`, `GET /auth/status` → opakowanie `OAuthManager`.
- `GET /models` → `list_models()` z fallbackiem.
- `WS /chat/stream` → streaming czatu (`chat_completion_stream`) + tryb narzędziowy mediów.
- `POST /images/generate|edit`, `POST /video/jobs`, `GET /video/jobs/{id}` → media.
- `GET /fs/tree`, `/fs/read`, `POST /fs/write` (gated), `GET /git/status|diff`, `POST /git/commit`.
- `WS /agent/stream` → agent kodowania (rozdz. 6): wiadomości, delty modelu, zdarzenia tool-call, żądania zatwierdzenia + odpowiedzi.
- `WS /terminal` → interaktywny terminal (pty po stronie Pythona — `pywinpty`).

**Reguły z pamięci projektu (zachowane):** jawne dekodowanie SSE jako UTF-8; własność plików JSON (`grok_config.json` tylko dla `HistoryManager`, ustawienia → `grok_settings.json`, tokeny → `grok_auth.json`, rozmowy → `grok_chats.json`); `DATA_DIR` w `%LOCALAPPDATA%` gdy frozen; UI po angielsku.

---

## 6. Silnik agenta kodowania (serce przebudowy)

Wzorowany na obecnym `chat_with_tools` / `_worker_chat_tools` / `_exec_tool`, rozbudowany o pracę z plikami i model zatwierdzania.

### 6.1 Zestaw narzędzi (parytet z Claude Code / Codex)

| Narzędzie | Opis | Bramka uprawnień |
|---|---|---|
| `read_file(path, offset?, limit?)` | Odczyt pliku | nie |
| `list_dir(path)` | Zawartość katalogu | nie |
| `glob(pattern)` | Dopasowanie plików | nie |
| `grep(pattern, path?, flags)` | Szukanie treści (ripgrep, fallback Python) | nie |
| `write_file(path, content)` | Utworzenie/nadpisanie pliku | **tak — diff** |
| `edit_file(path, old, new, replace_all?)` | Dokładna podmiana stringa | **tak — diff** |
| `run_command(cmd, cwd?, timeout?)` | Powłoka, streaming wyjścia | **tak — komenda** |
| `git_status / git_diff / git_commit` | Operacje git (lub przez run_command) | commit: tak |

Definicje w formacie function-calling xAI (jak obecne `CHAT_TOOLS`).

### 6.2 Pętla agenta (`agent/loop.py`)

1. Złóż wiadomości (system prompt kodowania + historia + kontekst) i wyślij z `tools`.
2. **Streaming z tool-calls:** akumuluj delty treści i delty `tool_calls` (rozszerzenie obecnego `chat_with_tools`, który jest nie-streamingowy — konkretna zmiana w `api_manager`; zweryfikować wsparcie po stronie xAI).
3. Dla każdego `tool_call`: sandbox ścieżki → sprawdź uprawnienia → jeśli wymaga zgody, wyślij `approval_request` przez WS i **czekaj** na decyzję frontendu → wykonaj → dołącz wynik (`role: tool`).
4. Powtarzaj do braku tool-calls lub limitu iteracji; strumieniuj tekst do UI.
5. Lista zadań (TODO) i krótkie podsumowanie kroków (jak w Claude Code).

### 6.3 Uprawnienia i sandbox (`agent/permissions.py`, `agent/workspace.py`)

- **Workspace root:** użytkownik wybiera katalog projektu; wszystkie ścieżki rozwiązywane względem niego.
- **Sandbox:** odrzucamy ucieczki `..` poza workspace; operacje poza nim wymagają osobnej zgody.
- **Bramka zatwierdzania:** `write_file`/`edit_file` → liczymy **diff** i wysyłamy do UI (Accept / Reject / „Always allow for session"). `run_command` → pokazujemy komendę + cwd przed wykonaniem.
- **Allowlista sesji:** `grok_permissions.json` — komendy/wzorce dozwolone bez pytania.
- **Bezpieczeństwo procesu:** timeout poleceń, limit rozmiaru wyjścia, zabijanie procesu na Stop.

### 6.4 Wybór modelu — „jak w Claude"

- **Domyślny model kodowania: `grok-build-0.1`** (Grok Build).
- **Płynna zmiana modelu** dostępna bezpośrednio w nagłówku modułu Code (szybki picker/dropdown) — bez wchodzenia w Settings, z natychmiastowym skutkiem dla kolejnej tury.
- Osobne preferencje modelu dla **czatu** i dla **agenta kodowania**; wybór zapamiętywany (per aplikacja, opcjonalnie per workspace).
- Lista modeli z `/v1/models` (po OAuth/kluczu) z fallbackiem na `config.DEFAULT_CHAT_MODELS`.

---

## 7. Moduł „Code" — mini-IDE (UI)

> **Uwaga (po Fazie 5):** edytor i diff to faktycznie **CodeMirror 6**, nie Monaco — decyzja i powód
> w §10f. Poniższy szkic (z etapu planowania) mówi jeszcze o „Monaco editor"/„Monaco DiffEditor".

```
┌───────────┬──────────────────────────────────┬──────────────────────┐
│ Drzewo    │  Monaco editor (zakładki plików)  │  Czat agenta (Grok)  │
│ plików    │  + zakładka Diff/Review           │  • streaming         │
│ (workspace│                                    │  • lista zadań TODO  │
│  + git    │                                    │  • karty tool-call   │
│  badges)  ├──────────────────────────────────┤  • approval cards    │
│           │  Terminal (xterm.js) / log poleceń │    (Accept/Reject)   │
└───────────┴──────────────────────────────────┴──────────────────────┘
  Górny pasek: [Open Folder] [Branch ▾] [Model ▾ grok-build-0.1] [Permissions ▾]
```

- **Drzewo plików:** lazy-load, ikony typów, statusy git (M/A/D), `.gitignore`-aware, menu kontekstowe.
- **Edytor:** Monaco z podświetlaniem; ręczna edycja (zapis przez backend), zakładki, wyszukiwanie.
- **Panel diff/review:** Monaco DiffEditor — propozycje agenta przed zapisem, Accept/Reject per-plik i per-hunk.
- **Terminal:** xterm.js spięty z `WS /terminal` (pty po stronie Pythona). Wspólny mechanizm z `run_command`.
- **Czat agenta:** strumień odpowiedzi, karty wywołań narzędzi (z wynikami), karty zatwierdzeń, lista zadań, **szybki picker modelu** (domyślnie `grok-build-0.1`).
- **Git:** status, diff, stage, commit (panel + przez agenta).

---

## 8. Komunikacja front ↔ back i bezpieczeństwo

- Backend bind **wyłącznie `127.0.0.1`**, **losowy wolny port**, **token sesji** generowany przez proces główny Electron i wstrzykiwany do renderera (handshake).
- WebSocket dla strumieni (czat, agent, terminal); REST dla operacji żądanie/odpowiedź.
- Token Bearer xAI wysyłany **tylko do `api.x.ai`** (zasada z `oauth_manager`).
- Walidacja i sandbox każdej ścieżki w backendzie (nie ufamy frontendowi).

---

## 9. Pakowanie i dystrybucja

- **Sidecar Python:** PyInstaller w trybie **onedir** (szybszy start jako sidecar) → dołączony jako resource Electrona.
- **Electron:** electron-builder → **instalator NSIS** dla Windows (zastępuje obecny Inno Setup). Opcjonalnie portable.
- **Cykl życia:** proces główny spawnuje sidecar przy starcie, health-check, restart przy padzie, zabicie przy zamknięciu.
- **Dane:** nadal `%LOCALAPPDATA%\AI Studio Pro` (zgodnie z `config.DATA_DIR`).
- **Auto-update:** electron-updater (opcjonalnie, później). Podpisywanie kodu — do rozważenia.

---

## 10. Plan fazowy (roadmapa)

| Faza | Zakres | Efekt |
|---|---|---|
| ✅ **0. Spike/fundament** | Monorepo (`/desktop` Electron, `/grok_core` Python), `git init`, szkielet electron-vite, pusty FastAPI, handshake port+token, spawn sidecara. | **UKOŃCZONA (2026-06-03)** — szczegóły w sekcji „Status Fazy 0" poniżej. |
| ✅ **1. Ekstrakcja backendu** | Owinięcie managerów w FastAPI: `/auth`, `/models`, `/chat/stream` (WS), `/images`, `/video`. | **UKOŃCZONA (2026-06-03)** — szczegóły w sekcji „Status Fazy 1" poniżej. |
| ✅ **2. Frontend + Chat** | Powłoka UI (rail, motyw, tokeny), port modułu **Chat**. | **UKOŃCZONA (2026-06-03)** — szczegóły w sekcji „Status Fazy 2" poniżej. |
| ✅ **3. Media + reszta** | Port **Generator / Edit / Video / History / Settings** (OAuth, folder, wybór modeli). | **UKOŃCZONA (2026-06-03)** — szczegóły w sekcji „Status Fazy 3" poniżej. |
| ✅ **4. Silnik agenta (backend)** | `agent/`: narzędzia plikowe, pętla ze streamingiem tool-calls, sandbox, uprawnienia, `WS /agent/stream`, `WS /terminal` (pywinpty), `/fs`, `/git`. | **UKOŃCZONA (2026-06-03)** — szczegóły w sekcji „Status Fazy 4" poniżej. |
| ✅ **5. Moduł Code (UI)** | Drzewo plików, edytor (CodeMirror) + diff, xterm.js, czat agenta, karty zatwierdzeń, picker modelu. | **UKOŃCZONA (2026-06-03)** — szczegóły w sekcji „Status Fazy 5" poniżej. |
| ✅ **6. Uprawnienia/git/polish** | Karty approval (Accept/Reject/Always), allowlista sesji, panel git, recent workspaces, skróty. | **UKOŃCZONA (2026-06-03)** — szczegóły w sekcji „Status Fazy 6" poniżej. |
| ✅ **7. Pakowanie** | PyInstaller onedir sidecar + electron-builder NSIS, health-check/restart, smoke-testy. | **UKOŃCZONA (2026-06-03)** — szczegóły w sekcji „Status Fazy 7" poniżej. |
| ✅ **8. Wygaszenie starej apki** | customtkinter jako legacy/fallback, potem usunięcie. | **UKOŃCZONA** — demotacja do `archive/` (2026-06-03), **usunięcie z repo (2026-06-04)**; kopia zewnętrzna. Sekcja „Status Fazy 8" poniżej. |

---

## 10a. Status Fazy 0 — UKOŃCZONA (2026-06-03)

**Co powstało:**
- `git init` (gałąź `main`) + `.gitignore` rozszerzony o monorepo (node_modules, venv, out/dist).
- **`grok_core/`** — backend sidecar (FastAPI):
  - `server.py` — `create_app(token, port)`, `GET /health` (bez auth), `GET /whoami` (Bearer token),
  - `__main__.py` — `python -m grok_core`: wolny port na 127.0.0.1 + token z env, handshake na stdout
    (`__GROK_CORE_READY__ {"port","token","version"}`),
  - `requirements.txt`, `README.md`, `tools/handshake_check.py` (self-check), izolowany `.venv`.
- **`desktop/`** — powłoka Electron (electron-vite + React + TS):
  - `src/main/index.ts` — spawn sidecara, parsowanie handshake, weryfikacja `/whoami`, IPC, okno, kill przy quit,
  - `src/preload/index.ts` — `contextBridge` → `window.grok` (getCore + onCoreStatus),
  - `src/renderer/` — rail modułów (Chat/Code/Generator/Edit/Video/History/Settings) + panel statusu backendu
    z testem round-trip do `/whoami`,
  - `electron.vite.config.ts`, `tsconfig.*.json`, `README.md`.

**Zweryfikowane:**
- Backend end-to-end — `handshake_check.py` przeszedł **4/4** (handshake + `/health` 200 + `/whoami` z tokenem 200 / bez 401 / zły 403).
- Frontend — `npm run typecheck` ✅ (exit 0) i `npm run build` ✅ (main 4.6 kB, preload 0.57 kB, renderer 559 kB).
- Zależności: vite 7.3.5 + plugin-react 5.2 + electron-vite 5 + electron 42.3.2 + @swc/core 1 + React 19.
- **Uruchomienie GUI potwierdzone przez użytkownika** (`npm run dev`): okno wstaje, status **Connected**, port + token widoczne.
- **CORS** zweryfikowany: preflight `OPTIONS /whoami` → 200 (`access-control-allow-origin: *`, `allow-headers: authorization`).

**Decyzje/ustalenia techniczne:**
- Handshake: Electron generuje token sesji → przekazuje przez env `GROK_CORE_TOKEN`; Python wybiera wolny port i ogłasza go na stdout. Token Electrona jest autorytatywny.
- Wybór Pythona w main: `GROK_CORE_PYTHON` → `grok_core/.venv` → systemowy `python`.
- **CORS w backendzie** (`CORSMiddleware`, `allow_origins=["*"]`, bez credentials): renderer dev ma origin `http://localhost:5173`, więc bez CORS fetch z renderera dawał `Failed to fetch` (proces główny w Node nie podlega CORS). Bezpieczne: backend i tak lokalny + token Bearer.
- Handshake przez **lifespan** (nie `@app.on_event`) — usunięty `DeprecationWarning`.
- Legacy (customtkinter) **pozostaje w korzeniu repo** bez zmian aż do Fazy 8 (przenosiny ryzykowałyby ścieżki danych).

**Znane ograniczenia / do zrobienia ręcznie:**
- **Binarka Electron nie pobrała się automatycznie** (zainstalowany pakiet `electron@42.3.2` ma pusty `postinstall`). Aby uruchomić okno, jednorazowo:
  `cd desktop && node node_modules/electron/install.js`, potem `npm run dev`.
- **Wizualne potwierdzenie okna GUI** — po stronie użytkownika (pełnego Electron GUI nie da się odpalić headless w sandboxie; logika połączenia jest zweryfikowana po stronie Pythona i przez build).
- Instalacja `pip`/binarek w sandboxie wymaga `--trusted-host` (przechwytywanie TLS) — na maszynie użytkownika działa normalnie.

---

## 10b. Status Fazy 1 — UKOŃCZONA (2026-06-03)

**Podejście:** backend reużywa managery legacy **z korzenia repo** (bez przepisywania xAI). `grok_core/__init__.py` dokłada korzeń repo do `sys.path`, dzięki czemu `import config / api_manager / oauth_manager / chats_manager / history_manager` działa, a dane (JSON, OAuth) są **współdzielone** ze starą aplikacją (te same pliki w korzeniu).

**Co powstało (`grok_core/`):**
- `state.py` — klasa `Backend` (managery + `get_api_key` OAuth→klucz→`XAI_API_KEY`, `is_authenticated`, `list_chat_models`, `save_media_urls`) + zależności `get_backend` / `require_token` (token z `app.state.session_token`).
- `server.py` — montaż tras, `app.state` (token + backend w lifespan), wersja **0.1.0**.
- `routes/auth.py` — `GET /auth/status`, `POST /auth/login` (OAuth PKCE, blokujący → threadpool), `POST /auth/logout`.
- `routes/models.py` — `GET /models` (czat + wideo + `default_code=grok-build-0.1`, fallback z config).
- `routes/settings.py` — `GET/PUT /settings` (klucz API zapisywany, nigdy nie zwracany — tylko `has_api_key`).
- `routes/media.py` — `POST /images/generate`, `POST /images/edit` (data-URI), `POST /video/jobs`, `GET /video/jobs/{id}` (auto-zapis + historia).
- `routes/chat.py` — **WS `/chat/stream`**: most wątek→kolejka asyncio→WS, streaming UTF-8 (reuse `chat_completion_stream`), stop mid-stream, fallback nie-streamingowy; token w query (WS nie pozwala na nagłówek Authorization).
- `tools/api_smoke.py` — smoke-test.

**Zweryfikowane (`api_smoke.py` — 9/9 PASS):**
- `/health`, `/whoami` (backend_ready), `/auth/status`, `/models` (7 modeli, `default_code=grok-build-0.1`), `/settings` → 200.
- Token: brak → 401, zły → 403. WS: token OK → akceptacja, zły → odrzucenie.

**Decyzje techniczne:**
- Autoryzacja: REST przez `Authorization: Bearer` (router-level dependency), WS przez `?token=` (ograniczenie przeglądarkowego WebSocket).
- CORS + lifespan jak w Fazie 0; `Backend()` tworzony w lifespan (przy błędzie `/health` żyje, reszta → 503).

**Nie zweryfikowane automatycznie (wymaga ważnych poświadczeń + sieci — po stronie użytkownika):**
- Realne wywołania xAI: streaming czatu (treść), generowanie/edycja obrazu, zadania wideo, `POST /auth/login` (otwiera przeglądarkę). W sandboxie blokuje je przechwytywanie TLS. Mechanika tras (routing, auth, most streamingu) jest potwierdzona.

**Self-test:** `grok_core\.venv\Scripts\python grok_core\tools\api_smoke.py`

---

## 10c. Status Fazy 2 — UKOŃCZONA (2026-06-03)

**Co powstało (`desktop/src/renderer/src/`):**
- `lib/api.ts` — klient backendu: REST (`getModels`, `getSettings`, `putSettings`, `getAuthStatus`) + `streamChat` (WS `/chat/stream`, ramki delta/done/error, `stop()`); baseUrl+token z handshake'u.
- `lib/storage.ts` — utrwalanie rozmów w localStorage (frontend zarządza historią, wysyła pełne `messages` do WS; backend ChatStore wystawimy przez REST później).
- `lib/useConnection.ts` — hook stanu połączenia z procesem głównym.
- `components/ChatView.tsx` — moduł Chat: streaming, multi-rozmowy (lista + new/select/delete), **picker modelu w nagłówku** (płynna zmiana, zapis `chat_model`), system prompt + temperatura (panel, zapis do `/settings`), Stop, Copy, auto-scroll, Enter=wyślij / Shift+Enter=nowa linia.
- `components/Markdown.tsx` — render GFM (`react-markdown` + `remark-gfm`) + podświetlanie kodu (`rehype-highlight`/highlight.js) + przycisk Copy na blokach kodu.
- `components/Placeholder.tsx` — pozostałe moduły + karta statusu backendu.
- `App.tsx` — rail + routing modułów; `styles.css` — style czatu/markdown.

**Zweryfikowane:**
- `npm run typecheck` ✅ (exit 0), `npm run build` ✅ (494 moduły, renderer JS 1.3 MB, CSS 10.6 kB z motywem highlight.js).
- Zależności dołożone: `react-markdown` 10, `remark-gfm` 4, `rehype-highlight` 7, `highlight.js` 11.

**Decyzje techniczne:**
- Streaming: backend wysyła pełną treść (`full`) w każdej ramce → frontend podmienia treść ostatniej wiadomości asystenta (proste, bez akumulacji po stronie UI).
- Wybór modelu zapamiętywany w backendzie (`PUT /settings { chat_model }`) — „jak w Claude", bez wchodzenia w osobne ustawienia.
- Rozmowy w localStorage (klucz `grok.chat.*`) — niezależnie od backendowego ChatStore (do zintegrowania później).

**Świadomie odłożone (parytet z legacy do uzupełnienia w kolejnych fazach):**
- Załączniki (obraz/plik), wklejanie obrazu Ctrl+V, komendy `/image` `/video`, narzędziowy tryb mediów w czacie, eksport `.md`, edycja/regeneracja wiadomości, integracja rozmów z backendowym ChatStore.

**Do weryfikacji po stronie użytkownika (wymaga ważnych poświadczeń xAI):**
- Realny streaming treści: `cd desktop && npm run dev` → moduł **Chat** → wpisz wiadomość. (W sandboxie blokuje to przechwytywanie TLS do `api.x.ai`; mechanika WS potwierdzona w Fazie 1.)

---

## 10d. Status Fazy 3 — UKOŃCZONA (2026-06-03)

**Backend (dołożone trasy, `grok_core/routes/system.py`):**
- `GET /history` — wpisy historii generacji (HistoryManager, najnowsze pierwsze).
- `GET/PUT /config/output-dir` — odczyt/zmiana folderu wyjściowego mediów.
(Trasy `/images`, `/video`, `/auth`, `/settings`, `/models` już były z Fazy 1.)

**Electron (`src/main` + `preload`):** IPC `dialog:selectFolder` (natywny wybór folderu) i `shell:openPath` (otwarcie pliku/folderu) → `window.grok.selectFolder()` / `openPath()`.

**Frontend (`desktop/src/renderer/src/`):**
- `lib/api.ts` — dołożone: `generateImage`, `editImage`, `createVideoJob`, `pollVideoJob`, `getHistory`, `getOutputDir`/`setOutputDir`, `login`/`logout`.
- `lib/constants.ts` — listy proporcji/rozdzielczości (z config.py).
- `components/Generator.tsx` — prompt + warianty/proporcje/rozdzielczość → galeria wyników.
- `components/Edit.tsx` — referencje (file picker + drag&drop, limit 3, data-URI) + prompt → edycja.
- `components/Video.tsx` — formularz + polling zadania (4–5 s) → odtwarzacz wideo + Open file.
- `components/History.tsx` — lista generacji (badge trybu, prompt, czas, Open) + Refresh.
- `components/Settings.tsx` — konto OAuth (Sign in/out), klucz API (zapis, nigdy nie odczyt), folder wyjściowy (Browse), domyślne modele (chat + code).
- `components/MediaGallery.tsx` — wspólna siatka wyników (Open file/URL).
- `App.tsx` — routing do wszystkich modułów (Code wciąż placeholder → Faza 5).

**Zweryfikowane:**
- Backend: `api_smoke.py` OK (boot z nowym routerem); `GET /history` zwraca realne wpisy; `GET /config/output-dir` zwraca ścieżkę.
- Frontend: `npm run typecheck` ✅ (exit 0), `npm run build` ✅ (501 modułów, CSS 15.2 kB, JS 1.32 MB).

**Do weryfikacji po stronie użytkownika (ważne poświadczenia xAI + sieć):** realne generowanie obrazu/wideo, edycja, `Sign in` (otwiera przeglądarkę). W sandboxie blokuje to TLS; mechanika tras potwierdzona.

**Świadomie odłożone:** integracja rozmów czatu z backendowym ChatStore; obraz startowy dla wideo (image-to-video — backend przyjmuje na razie tylko text-to-video); załączniki/komendy w czacie (z Fazy 2).

---

## 10e. Status Fazy 4 — UKOŃCZONA (2026-06-03)

**Pakiet `grok_core/agent/`:**
- `workspace.py` — `Workspace` + sandbox ścieżek (odrzuca `..`/absolutne poza korzeń).
- `permissions.py` — `PermissionGate`: READONLY bez zgody, MUTATING (write/edit/run) za zgodą; allowlista sesji ("Always allow").
- `tools.py` — schematy function-calling + egzekutory: `read_file`, `list_dir`, `glob`, `grep`, `write_file`, `edit_file`, `run_command` (stream wyjścia + timeout/stop) + `preview_change` (diff/komenda do zatwierdzenia).
- `llm.py` — `stream_chat_with_tools`: streaming na xAI z akumulacją delt treści **i** `tool_calls` (UTF-8).
- `session.py` — `AgentSession.run_turn`: pętla model→narzędzia→wynik→powtórz; `llm_fn` wstrzykiwany (testowalność); emisja zdarzeń + blokujące `request_approval`.

**Trasy:**
- `routes/fs.py` — `GET/POST /fs/workspace`, `GET /fs/tree`, `GET /fs/read`, `POST /fs/write` (zapis ręczny = bezpośredni).
- `routes/git.py` — `GET /git/status`, `GET /git/diff` (subprocess git, graceful).
- `routes/agent.py` — **WS `/agent/stream`**: protokół workspace/message/approval/stop ↔ text/tool_call/approval_request/output/tool_result/assistant_done/done; most wątek↔kolejka asyncio, zatwierdzanie przez `threading.Event`.
- `routes/terminal.py` — **WS `/terminal`** (pywinpty, graceful gdy brak).
- `state.py` — workspace na poziomie `Backend` (`set_workspace`/`get_workspace`).

**Zweryfikowane (bez sieci xAI):**
- `agent_selfcheck.py` — **17/17 PASS**: narzędzia (write/read/list/glob/grep/edit/run_command + preview diff), sandbox (odrzucenie ucieczki), pętla agenta z **mockiem modelu** (tool_call → approval → tool_result → assistant_done, plik realnie zapisany, allowlista).
- `api_smoke.py` OK — serwer bootuje ze wszystkimi nowymi routerami.
- Live REST: `POST /fs/workspace` → OK, `GET /fs/tree` → 31 wpisów, `GET /git/status` → repo wykryte (branch + 20 zmian), brak tokenu → 401.

**Decyzje techniczne:**
- Streaming tool-calls własną funkcją (`agent/llm.py`) — legacy `api_manager` nietknięty.
- WS autoryzowane tokenem w query (jak czat). Agent zajęty → kolejne `message` odrzucane ("busy").
- `run_command` nie jest sandboxowany w treści → zawsze za zgodą; operacje plikowe sandboxowane do workspace.

**Do weryfikacji po stronie użytkownika:** realny przebieg agenta na modelu (xAI) — w Fazie 5 z UI; opcjonalnie `pip install pywinpty` w venv dla terminala (run_command agenta działa bez tego).

**Self-test:** `grok_core\.venv\Scripts\python grok_core\tools\agent_selfcheck.py`

---

## 10f. Status Fazy 5 — UKOŃCZONA (2026-06-03)

**Frontend (`desktop/src/renderer/src/`):**
- `lib/agentClient.ts` — `AgentConnection`: trwałe WS `/agent/stream` z subskrypcją zdarzeń, `setWorkspace`/`sendMessage`/`approve`/`stop`.
- `lib/api.ts` — dołożone: `fsGetWorkspace`, `fsSetWorkspace`, `fsTree`, `fsRead`, `fsWrite`, `gitStatus`.
- `components/CodeView.tsx` — orkiestrator: Open Folder, drzewo, zakładki edytora, terminal toggle, gałąź git, picker modelu (zapis `code_model`), Ctrl+S, auto-odświeżanie po turze agenta.
- `components/code/FileTree.tsx` — leniwe drzewo plików.
- `components/code/CodeEditor.tsx` — **CodeMirror 6** (JS/TS/Py/JSON + one-dark).
- `components/code/Terminal.tsx` — **xterm** ↔ WS `/terminal`.
- `components/code/AgentPanel.tsx` — czat agenta: streaming, karty narzędzi, **karty zatwierdzania** (Accept/Reject/Always) z podglądem diff/komendy, log wyjścia.
- `components/code/DiffView.tsx` — kolorowany diff z `preview_change`.
- `App.tsx` — Code → `CodeView` (koniec placeholderów).

**DECYZJA — edytor: CodeMirror 6 zamiast Monaco.** Powód: Monaco pod Vite/Electron wymaga ciężkiej konfiguracji web-workerów albo ładowania z CDN; CodeMirror daje ten sam UX (edytor + podświetlanie + diff w kartach zatwierdzania), bunduje się czysto i działa offline. Wymiana na Monaco możliwa później — izolowana w `CodeEditor.tsx`.

**Zależności dołożone:** `@uiw/react-codemirror`, `@codemirror/{state,theme-one-dark,lang-javascript,lang-python,lang-json}`, `@xterm/xterm`, `@xterm/addon-fit`.

**Zweryfikowane:**
- **GUI ładuje się** (potwierdzone przez użytkownika po instalacji zależności).
- `npm run typecheck` ✅ (exit 0), `npm run build` ✅ (541 modułów, CSS 28 kB, JS 2.79 MB).

**Do weryfikacji po stronie użytkownika (wymaga ważnych poświadczeń xAI):** realny przebieg agenta — Open Folder → polecenie do agenta → karty zatwierdzania z diffem → akceptacja → zapis pliku; terminal wymaga `pip install pywinpty` w venv.

---

## 10g. Status Fazy 6 — UKOŃCZONA (2026-06-03)

**Cel fazy:** dociągnąć moduł Code do poziomu „Claude Code/Codex" w obszarze uprawnień, gita i ergonomii. Karty approval (Accept/Reject/Always) i allowlista w pamięci powstały już w Fazie 5 — Faza 6 utrwala je, dodaje przegląd/czyszczenie oraz panel git, recent workspaces i skróty.

**Backend (`grok_core/`):**
- `agent/permissions.py` — `PermissionGate` **utrwalany w `grok_permissions.json`** (`_load`/`_save`); `allow()` zapisuje regułę na dysk (przeżywa restart), nowe `rules()` i `clear()`.
- `state.py` — gate przeniesiony na `Backend` (`self.permissions`) — **współdzielony** przez WS agenta i REST; `set_workspace` rejestruje folder w `recent_workspaces` (`_record_recent`, limit 10) zapisywanym w `grok_settings.json`; nowe `recent_workspaces()`.
- `routes/agent.py` — używa `backend.permissions` zamiast tworzyć gate per-połączenie (allowlista wspólna i trwała).
- `routes/permissions.py` — **NOWE**: `GET /permissions` (lista reguł), `DELETE /permissions` (wyczyść).
- `routes/git.py` — dołożone `POST /git/add` (stage wskazanych ścieżek lub `-A`) i `POST /git/commit` (`message` + `stage_all`; puste/nieudane → 400 z detalem).
- `routes/fs.py` — `GET /fs/recent` (ostatnie workspace).
- `config.py` — `PERMISSIONS_FILE = DATA_DIR/grok_permissions.json`; plik dopisany do `.gitignore`.

**Frontend (`desktop/src/renderer/src/`):**
- `lib/api.ts` — dołożone: `fsRecent`, `gitDiff`, `gitStage`, `gitCommit`, `getPermissions`, `clearPermissions`.
- `components/code/Menu.tsx` — **NOWE**: lekki popover (dropdown) z zamykaniem po kliknięciu poza / Esc.
- `components/code/GitPanel.tsx` — **NOWE**: lista zmian z badge'ami statusu (M/A/D/U), Stage all, pole commit message + Commit (stage_all), Refresh; „Working tree clean" / „Not a git repository".
- `components/CodeView.tsx` — w nagłówku: **Recent ▾** (szybkie przełączanie folderów), **Git** (toggle panelu, Ctrl+Shift+G), **🛡 Permissions ▾** (lista reguł + Clear all); panel Git w dolnej części drzewa (split aside); skróty **Ctrl+S** (zapis), **Ctrl+`** (terminal), **Ctrl+Shift+G** (git).
- `styles.css` — style menu/popover, panelu git i badge'ów statusu.

**Zweryfikowane (bez sieci xAI):**
- `agent_selfcheck.py` — **24/24 PASS** (dołożony blok trwałości allowlisty: reguła zapisywana, przeżywa reload, `clear` czyści i utrwala).
- `api_smoke.py` — **11/11 PASS** (dołożone `GET /permissions` i `GET /fs/recent` → 200 z listami; reszta tras Fazy 1 bez regresji).
- Trasy git na **tymczasowym repo** (test bezpośredni route'ów, 6/6): status widzi untracked → `commit(stage_all)` → working tree clean → wpis w `git log`; pusty message → 400; recent workspace zapisany.
- Frontend: `npm run typecheck` ✅ (exit 0), `npm run build` ✅ (543 moduły, CSS 32.1 kB, JS 2.8 MB).

**Decyzje techniczne:**
- Allowlista jest **trwała** (plik), nie tylko sesyjna — „Always allow" przeżywa restart; użytkownik panuje nad nią przez panel Permissions (Clear all). Klucz reguły jak dotąd: `cmd:<exe>` dla `run_command`, `tool:<name>:<path>` dla write/edit.
- Commit z poziomu panelu domyślnie robi `git add -A` przed `git commit` (obejmuje nowe pliki) — jeden klik „Commit". Osobny „Stage all" dostępny bez commitu.
- Recent workspaces trzymane w `grok_settings.json` (klucz `recent_workspaces`), nie eksponowane przez `GET /settings`.

**Do weryfikacji po stronie użytkownika:** pełny przebieg w GUI — Recent ▾ przełącza foldery, „Always allow" na karcie dodaje regułę widoczną w Permissions ▾, panel Git stage'uje i commituje realne zmiany. (Mechanika tras potwierdzona testami; realny agent na xAI nadal wymaga ważnych poświadczeń — sandbox blokuje TLS do api.x.ai.)

**Self-test:** `grok_core\.venv\Scripts\python grok_core\tools\agent_selfcheck.py` oraz `...\api_smoke.py`.

---

## 10h. Status Fazy 7 — UKOŃCZONA (2026-06-03)

**Cel fazy:** zamienić projekt w instalowalny `.exe` — spakowany sidecar (PyInstaller onedir) + instalator Electrona (electron-builder NSIS), z nadzorem cyklu życia sidecara.

**Sidecar (PyInstaller onedir):**
- `grok_core_sidecar.py` — cienki entry-point dla PyInstallera (`grok_core.__main__.main()` + `multiprocessing.freeze_support()`).
- `grok_core.spec` — **ONEDIR** (szybki start, bez rozpakowywania do tempa). `collect_all` dla uvicorn/fastapi/starlette/anyio/pydantic/websockets + `collect_submodules('uvicorn'/'grok_core')`; **legacy moduły z korzenia** (`config`, `api_manager`, `oauth_manager`, `chats_manager`, `history_manager`) jako `hiddenimports` z `pathex=['.']` — bo `grok_core/__init__.py` dokłada korzeń do `sys.path` dopiero w runtime (analiza statyczna ich nie widzi); `excludes` na tkinter/customtkinter. `console=True` (stdout = handshake), okno ukrywa Electron.
- `build_sidecar.ps1` — dba o venv + PyInstaller + pywinpty, buduje spec → `dist\grok-core\grok-core.exe`.
- `grok_core/tools/sidecar_smoke.py` — uruchamia **spakowany .exe** jak Electron (env token + handshake na stdout) i sprawdza `/health`, `/whoami`.

**Electron (electron-builder NSIS + lifecycle):**
- `desktop/electron-builder.yml` — target **NSIS** (x64), `extraResources` kopiuje `..\dist\grok-core` → `resources\grok-core`; NSIS: `oneClick:false`, wybór katalogu, `Grok-Desktop-Setup-<wersja>.exe`.
- `desktop/package.json` — devDep `electron-builder`; skrypty `pack:sidecar`, `dist`, `dist:full`.
- `desktop/src/main/index.ts` — **`resolveSidecar()`**: spakowany → `resources\grok-core\grok-core.exe`, dev → `python -m grok_core`; spawn z **`windowsHide:true`** (ukrywa konsolę sidecara). **Nadzór**: health-check `GET /health` co 10 s (3 porażki → ubicie i restart), **auto-restart po padzie** (do 5 prób, narastający backoff, reset po udanym `/whoami`), `manualStop` przy quit; `setAppUserModelId` dla taskbara.
- `config.IS_FROZEN` (bez zmian) kieruje dane spakowanego sidecara do `%LOCALAPPDATA%\AI Studio Pro` (zgodnie z rozdz. 9; współdzielone z legacy do Fazy 8).

**Zweryfikowane (w tym środowisku):**
- **Sidecar zbudowany i działa**: `PyInstaller 6.20` → `dist\grok-core\grok-core.exe` (~57 MB onedir). `sidecar_smoke.py` — **5/5 PASS** (handshake + token zgodny z env, `/health` 200, `/whoami` 200 z `backend_ready`, bez tokenu 401, zły 403). To dowodzi, że bundle dociągnął wszystkie ukryte importy: uvicorn/fastapi **oraz** legacy `config/api_manager/oauth_manager/chats_manager/history_manager` (bo `backend_ready=True` ⇒ `Backend()` zbudowany).
- `agent_selfcheck.py` 24/24 i `api_smoke.py` 11/11 nadal OK (bez regresji); `npm run typecheck` ✅.

**Do wykonania po stronie użytkownika (sieć):**
- **Build instalatora**: `cd desktop && npm run dist` (sidecar już zbudowany) lub `npm run dist:full` (od zera). electron-builder pobiera przy pierwszym uruchomieniu NSIS/winCodeSign/electron z GitHuba — wymaga sieci (w sandboxie pobieranie się wiesza; u użytkownika `npm install` electron-buildera poszedł w 13 s). Wynik: `desktop\dist\Grok-Desktop-Setup-<wersja>.exe`.
- Ikona **dołączona**: `desktop\build\icon.ico` (z `make_icon.py`, 16–256 px, auto-wykrywana). Podpisywanie kodu i auto-update (electron-updater) — świadomie odłożone (rozdz. 9).
- **Stan po stronie użytkownika (2026-06-03):** `npm install` electron-buildera 25.1.8 OK; `npm run build` (main+preload+renderer) OK. Pozostał `npm run dist` (pobranie NSIS/electron + spakowanie).

**Self-test:** `pwsh -File build_sidecar.ps1` → `grok_core\.venv\Scripts\python grok_core\tools\sidecar_smoke.py`.

---

## 10i. Status Fazy 8 — DEMOTACJA WYKONANA (2026-06-03)

> **Aktualizacja (2026-06-03):** katalog `legacy/` został później przemianowany na **`archive/`**
> (ten sam poziom zagnieżdżenia pod korzeniem repo → shimy ścieżek `dirname(dirname(__file__))`,
> `pathex=['..']` i `$PSScriptRoot\..` działają bez żadnych zmian w kodzie). Opis historyczny
> poniżej mówi o `legacy/`; obecnie pliki starej apki znajdują się w `archive/`.

**Cel fazy:** sprowadzić projekt do jednej aplikacji docelowej. Krok 1 (ten): zdemotować starą apkę customtkinter do izolowanego `legacy/` jako **fallback**, bez psucia ścieżek danych i bez ruszania współdzielonego rdzenia. Krok 2 (USUNIĘCIE) — świadomie odłożony do czasu, aż użytkownik zweryfikuje nową aplikację z ważnymi poświadczeniami xAI (czat/obrazy/wideo/agent), bo do tego czasu legacy jest jedyną zweryfikowaną ścieżką.

**Kluczowe rozróżnienie — co jest „legacy", a co „współdzielonym rdzeniem":**
- **Przeniesione do `legacy/`** (czysto customtkinter): `app.py`, `ui_utils.py`, `run.bat`, `build.ps1`, `GrokDesktopApp.spec`, `installer.iss`, `version_info.txt`, `requirements.txt`, `DISTRIBUTION.md`.
- **Pozostają w korzeniu** (reużywane przez `grok_core`): `config.py`, `api_manager.py`, `oauth_manager.py`, `chats_manager.py`, `history_manager.py` + `make_icon.py` (współdzielony generator ikony) + pliki pakowania sidecara (`grok_core_sidecar.py`, `grok_core.spec`, `build_sidecar.ps1`). `code.html` (stray) nietknięty.

**Wykonane zmiany:**
- `legacy/app.py` — dodany **shim `sys.path`** na samej górze (`insert(0, dirname(dirname(__file__)))`), by importy „po nazwie" (`config`, `api_manager`, `ui_utils`…) działały po przenosinach. `ui_utils` rozwiązuje się z `legacy/` (katalog skryptu), rdzeń z korzenia.
- `legacy/GrokDesktopApp.spec` — `pathex=['..']`, by PyInstaller znalazł współdzielony rdzeń w korzeniu przy budowie starego `.exe`.
- `legacy/build.ps1` — `Set-Location $PSScriptRoot`; `make_icon.py` wołane jako `..\make_icon.py` (został w korzeniu).
- `legacy/run.bat` — `cd /d "%~dp0"`.
- `legacy/README.md` — nowy: notka deprecacji, jak uruchomić, **dlaczego rdzeń zostaje w korzeniu** (współdzielenie danych).
- Root `README.md` — struktura repo + sekcja „Aplikacja legacy (fallback)" zaktualizowane.

**Dlaczego ścieżki danych są bezpieczne:** `config.py` **nie ruszony** i **nie przeniesiony** — `config.DATA_DIR` zależy od jego położenia (korzeń w dev, `%LOCALAPPDATA%\AI Studio Pro` po spakowaniu), nie od `legacy/`. Legacy i nowa apka dalej współdzielą `grok_settings.json`/`grok_chats.json`/`grok_auth.json`/`grok_config.json` (reguły własności z pamięci projektu zachowane).

**Zweryfikowane:**
- **Nowy backend bez regresji** (rdzeń nadal w korzeniu): `agent_selfcheck.py` 24/24, `api_smoke.py` 11/11 — OK.
- **Legacy importuje się po przenosinach**: `Python310 -c "import app"` z `legacy/` → „LEGACY IMPORT OK" (`app` + `config` + `ui_utils` rozwiązane przez shim; Python310 ma customtkinter/Pillow/dotenv). Pełnego GUI nie odpalamy headless — testuje użytkownik.
- Artefakty buildu legacy (`legacy/dist`, `legacy/build`, `legacy/Output`, `appicon.ico`) są już objęte `.gitignore` (wzorce katalogowe bez wiodącego `/`).

**Krok 2 — WYKONANY (2026-06-04):** użytkownik zrobił pełną kopię zapasową na osobnym dysku i **usunął `archive/` z repo** (`git rm -r archive`). Stara apka nie jest już śledzona — pozostaje jako kopia zewnętrzna. Współdzielony rdzeń (`config.py` itd.) **zostaje w korzeniu** — wymaga go sidecar `grok_core` i build PyInstaller, niezależnie od legacy (patrz „single most important structural fact" w `CLAUDE.md`).

---

## 11. Ryzyka i pułapki (część z pamięci projektu)

- **Streaming z tool-calls:** obecny `chat_with_tools` jest nie-streamingowy — dodać akumulację delt `tool_calls` (zweryfikować wsparcie xAI).
- **Terminal natywny:** unikamy `node-pty` (rebuild natywny pod Electron na Windows). **Używamy `pywinpty`** w backendzie i streamujemy przez WS — jeden mechanizm dla terminala i `run_command`.
- **OAuth xAI:** nieudokumentowane endpointy `auth.x.ai` + publiczny `client_id` grok-cli/Hermes — może przestać działać po stronie xAI; klucz API jako fallback. Lokalny callback (port 56121) zostaje w Pythonie.
- **UTF-8 streaming:** zachować jawne dekodowanie bajtów (mojibake polskich znaków przy `decode_unicode=True`).
- **Własność plików JSON:** nie nadpisywać `grok_config.json` (należy do `HistoryManager`).
- **Sandbox/uprawnienia:** krytyczne dla bezpieczeństwa — walidacja ścieżek i bramki po stronie backendu, nie frontendu.
- **Język UI:** całość interfejsu po angielsku (komentarze/docstringi mogą zostać po polsku).
- **Wydajność:** duże drzewa plików i obserwowanie zmian — `watchdog` (Python) lub `chokidar`; lazy-load drzewa.

---

## 12. Następne kroki

1. **Faza 0** — założyć monorepo (`git init`), strukturę `/desktop` + `/grok_core`, scaffold electron-vite, pusty FastAPI, handshake port+token, spawn sidecara.
2. Po Fazie 0 — przejść do ekstrakcji backendu (Faza 1) i portu modułu Chat (Faza 2).

---

## 13. Faza 9 — Nadbudowa i hardening (po Fazach 0–8)

Sekcje 1–12 to **zapis historyczny** planu (stan na Fazy 0–8). Po nich projekt się rozwinął; ta sekcja
rekonsoliduje **aktualny stan**, by §1–12 nie wprowadzały w błąd (P3-5).

**Moduły (renderer, 7):** Chat · Code · **Image** · Video · **Voice** · History · Settings.
- Generator + Edit **scalone w Image** (bez referencji → generowanie, z referencjami → edycja).
- **Video**: generowanie (tekst→wideo / obraz startowy) + **edycja** + **przedłużanie**.
- **Voice** (nowy): Speak (TTS) / Transcribe (STT) / Live (realtime przez WS).
- **Chat**: doszły **załączniki** (obraz/plik) i **głos** (TTS odpowiedzi, dyktowanie STT).
- Szczegóły i kontrakty: **[`MODYFIKACJE.md`](MODYFIKACJE.md)** (żywa specyfikacja tych modułów).

**Frontend — faktyczny stack** (różni się od planu w §3–4):
- **Edytor/diff: CodeMirror 6** (nie Monaco — §10f), izolowany w `CodeEditor.tsx`.
- **Style: Tailwind v4** (CSS-first: tokeny + motywy jasny/ciemny) — nie shadcn/Radix.
- **Stan serwera:** własny lekki cache (`lib/serverState.ts`: `useModels`/`useSettings`) — nie react-query/zustand.
- **Markdown:** react-markdown + rehype-highlight; **terminal:** xterm; **panele:** react-resizable-panels.

**Pełna lista endpointów (stan obecny):**
- **REST** (Bearer, poza `/health`): `GET /health` · `GET /whoami` · `GET /auth/status` · `POST /auth/login`
  · `POST /auth/logout` · `GET /models` · `GET`/`PUT /settings` · `POST /images/generate` · `POST /images/edit`
  · `POST /video/jobs` · `POST /video/edits` · `POST /video/extensions` · `GET /video/jobs/{id}`
  · `POST /voice/tts` · `POST /voice/stt` · `GET /history` · `GET`/`PUT /config/output-dir`
  · `GET`/`POST /fs/workspace` · `GET /fs/tree` · `GET /fs/read` · `GET /fs/recent` · `POST /fs/write`
  · `GET /git/status` · `GET /git/diff` · `POST /git/add` · `POST /git/commit` · `GET`/`DELETE /permissions`.
- **WebSocket** (token w query `?token=`): `WS /chat/stream` · `WS /agent/stream` · `WS /terminal` · `WS /voice/realtime`.

**M10 (czat na Responses API — pierwszy plaster, 2026-06-05):** rdzeń `/chat/stream` chodzi przez
**`grok_core/responses_client.py`** (`POST /v1/responses`, streaming) z **live search**
(`web_search`/`x_search`), **wizją** (rodzina grok-4) i **cytowaniami**; legacy `chat/completions`
zostaje tylko jako fallback czystego czatu. Nowe ramki WS: `tool_call` · `citations` · `usage`;
nowe pola wejścia `chat`: `search_mode` (auto/on/off) + `sources`. Ustawienia: `chat_search_mode`,
`chat_search_sources`. Pełny status i to-do (B4/B5/F5) w **[`PLAN_M10_CZAT.md`](PLAN_M10_CZAT.md)** §6.

**Wersja produktu (P3-4):** jedno źródło prawdy = `desktop/package.json`; sidecar raportuje ją w
handshake / `/health` / `/whoami` (env `GROK_CORE_APP_VERSION` ← Electron, z odczytem package.json jako
fallbackiem). Legacy `config.APP_VERSION` to **osobna** wersja archiwalnej apki customtkinter.

**Hardening (P0–P3):** bezpieczeństwo agenta, odporność streamingu/WS, obsługa błędów, trwałość danych,
jakość/wydajność frontu, CI + testy logiki — pełny rejestr i status w **[`PLAN_NAPRAWY.md`](PLAN_NAPRAWY.md)**.

---

*Dokument utrzymywany w `docs/REBUILD_PLAN.md`. Aktualizować przy zmianach decyzji.*
