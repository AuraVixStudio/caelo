# caelo-desktop (Electron + React + TypeScript)

Frontend aplikacji Caelo. Spawnuje backend Python (`caelo_core`) jako
sidecar i łączy się z nim po 127.0.0.1 z tokenem sesji (handshake). Zob. też
[`../README.md`](../README.md).

## Wymagania
- Node.js ≥ 20 (testowane na v22)
- Backend `caelo_core` z zainstalowanym venv (zob. `../caelo_core/README.md`)

## Uruchomienie (dev)
```powershell
npm ci           # instalacja z package-lock.json (powtarzalna; preferowana — P3-6)
# npm install    # tylko gdy DODAJESZ/zmieniasz zależności (aktualizuje lockfile)
npm run dev      # Electron + Vite HMR; proces główny spawnuje `python -m caelo_core`
```
> Po dołożeniu nowych zależności zrestartuj `npm run dev` — Vite musi je przeoptymalizować.

## Skrypty
- `npm run dev` — tryb deweloperski (Electron + Vite HMR)
- `npm run build` — produkcyjny build (main + preload + renderer → `out/`)
- `npm run typecheck` — sprawdzenie typów (node + web)
- `npm run lint` — ESLint (reguły `react-hooks`)
- `npm test` — Vitest (utile + komponenty; zob. niżej)
- `npm run pack:sidecar` — buduje sidecar PyInstaller (`../build_sidecar.ps1` → `../dist/caelo-core`)
- `npm run dist` — instalator NSIS (zakłada zbudowany sidecar w `../dist/caelo-core`)
- `npm run dist:full` — pełny pipeline: sidecar → frontend build → instalator NSIS

## Testy (Vitest)

Dwie warstwy, obie pod `npm test`, leżą w `test/` (POZA `tsconfig` → nie wpływają na `npm run typecheck`):

- **Czyste utile** (`test/*.test.ts`, środowisko `node`, domyślne) — logika stanu i transformacje bez
  DOM: agentTrust (maszyna stanów plan/undo/checkpoint), attachments (most send-to ↔ API), audioCost,
  commands (paleta), genjobs (kolejka), hubQuery, searchState (etykiety wyszukiwania/cytaty), sendTo,
  slashCommands, storage, teamView (M17), voice.
- **Komponenty React** (`test/components/*.test.tsx`, środowisko `jsdom` przez docblock
  `// @vitest-environment jsdom` w każdym pliku → node pozostaje domyślny, utile nietknięte) — render +
  interakcja na **React Testing Library**: prymitywy UI (Button, Input/Textarea, Badge, Select,
  IconButton, Slider, Card) oraz kontekst motywu (ThemeProvider/useTheme — `setTheme` przełącza klasę
  `.dark` i persistuje do localStorage; matchMedia stubowany w `test/components/_matchMedia.ts`).

```powershell
npm test                 # cała kolekcja (utile + komponenty)
npm test -- Button       # pojedynczy plik/wzorzec
```

Wymaga dev-zależności RTL: `@testing-library/react`, `@testing-library/jest-dom`,
`@testing-library/user-event`, `jsdom` (w `devDependencies`).

Warstwa jednostkowa pokrywa prymitywy UI, kontekst motywu oraz **paletę komend** (`CommandPalette`
— filtr/Enter/Escape/klik), deterministycznie i bez sieci. **Do zrobienia osobno:** testy ciężkich
komponentów funkcyjnych (ChatView, AgentPanel, TeamView — wymagają harnessu mockującego
`window.caelo` + kontekst Hub + klienta API).

## E2E (Playwright)

Testy end-to-end sterują **realną przeglądarką** nad `preview:web` (Vite na :4599 z atrapą
`window.caelo` z [`lib/devMock`](src/renderer/src/lib/devMock.ts)) — renderer **bez Electrona i bez
sidecara**. Pokrywają ([`e2e/*.spec.ts`](e2e/), config [`playwright.config.ts`](playwright.config.ts)):
**powłokę** (ładowanie/„Connected", nawigacja po rail + `aria-current`, paleta **Ctrl-K**) oraz
**przepływ z danymi backendu** — switcher projektu listujący `GET /projects` i przełączający przez
`POST /projects/current`, z backendem zmockowanym przez `page.route()` ([`e2e/_mock.ts`](e2e/_mock.ts)).

Biegną w **CI** (osobny job `e2e` w `ci.yml`) i lokalnie (`@playwright/test` jest w `devDependencies`):
```powershell
npx playwright install chromium     # raz: binaria przeglądarki (~130 MB, z CDN Playwrighta)
npm run test:e2e                     # podnosi preview:web i uruchamia specy z e2e/ (headless)
```
> **Restrykcyjna sieć (TLS-interception blokuje CDN Playwrighta)?** Jeśli nie da się dociągnąć
> buildu pasującego do `@playwright/test`, wskaż **pre-zainstalowaną** przeglądarkę:
> `$env:E2E_CHROMIUM_PATH="…\ms-playwright\chromium-<v>\chrome-win64\chrome.exe"; npm run test:e2e`.
> Config czyta tę zmienną opcjonalnie (domyślnie standardowe zachowanie — CI dociąga build sam).

E2E jest **deterministyczne**: `workers: 1` (jeden współdzielony `preview:web`), a specy czekają na
gotową powłokę/moduł przed interakcją (np. na nagłówek modułu lub przed `Ctrl-K`). Mock REST
([`_mock.ts`](e2e/_mock.ts)) przechwytuje `http://127.0.0.1:9/**` (baseUrl z devMock) i odpowiada JSON-em
per ścieżka; testy nadpisują wybrane endpointy. Kolejne przepływy (np. send-to) dodaje się analogicznie.

## Pakowanie (instalator .exe — Faza 7)
Dwa artefakty: **spakowany sidecar** (PyInstaller onedir) + **instalator Electrona** (electron-builder NSIS).

```powershell
# 1) Sidecar: PyInstaller onedir z caelo_core\.venv  ->  ..\dist\caelo-core\caelo-core.exe
npm run pack:sidecar
#    (weryfikacja samego sidecara, bez Electrona:)
..\caelo_core\.venv\Scripts\python ..\caelo_core\tools\sidecar_smoke.py

# 2) Instalator: frontend build + electron-builder  ->  dist\Grok-Desktop-Setup-<wersja>.exe
npm run dist

# lub wszystko naraz:
npm run dist:full
```

- **Sidecar** definiuje `..\caelo_core.spec` (onedir = szybki start, brak rozpakowywania do tempa).
  Bundluje uvicorn/FastAPI + legacy `config/api_manager/oauth_manager/chats_manager/history_manager`
  (deklarowane jako `hiddenimports`, bo `caelo_core/__init__.py` dokłada korzeń do `sys.path` dopiero
  w runtime). Terminal (`pywinpty`) dołączany, jeśli zainstalowany w venv.
- **Electron** (`electron-builder.yml`): cały katalog `..\dist\caelo-core` ląduje w `resources\caelo-core`.
  W trybie spakowanym (`app.isPackaged`) proces główny uruchamia `caelo-core.exe` z `resources`
  (`windowsHide` ukrywa jego konsolę), zamiast `python -m caelo_core`.
- **Dane**: w wersji spakowanej sidecar ma `sys.frozen=True`, więc `config.DATA_DIR` =
  `%LOCALAPPDATA%\AI Studio Pro` (dawniej współdzielone z legacy app — usuniętą w Fazie 8).
- **Ikona**: oficjalny zestaw marki Caelo (źródło: `..\assets\brand\`) — `desktop\build\icon.ico`
  (Windows), `icon.icns` (macOS) i `icon.png` 1024 px (Linux). electron-builder wykrywa je
  automatycznie po nazwie. Aby zmienić logo, podmień te pliki (lub wygeneruj nowe z `assets\brand\`).
- **Nadzór**: proces główny robi health-check `/health` co 10 s i restartuje sidecar po padzie
  (do 5 prób z narastającym backoffem); przy zamknięciu aplikacji zabija sidecar.

## Wybór interpretera Pythona (sidecar)
Proces główny szuka Pythona w kolejności:
1. zmienna środowiskowa `CAELO_CORE_PYTHON`,
2. venv backendu: `../caelo_core/.venv/Scripts/python.exe` (Windows),
3. systemowy `python` / `python3`.

```powershell
$env:CAELO_CORE_PYTHON = "C:\sciezka\do\python.exe"; npm run dev
```

## Struktura
```
src/main/index.ts            proces główny: spawn sidecara, handshake, IPC (folder/openPath), okno
src/preload/index.ts         contextBridge → window.caelo (getCore, onCoreStatus, selectFolder, openPath)
src/renderer/
  src/App.tsx                rail modułów + routing
  src/types.ts               typy współdzielone (CoreConnection, window.caelo)
  src/lib/                   api.ts (REST+WS), agentClient.ts (WS agenta),
                             storage.ts (rozmowy), useConnection.ts, constants.ts
  src/components/            ChatView, CodeView, Image, Video, Voice, History,
                             Settings, Markdown, MediaGallery, Attachments, ErrorBoundary
  src/components/code/       FileTree, CodeEditor (CodeMirror), Terminal (xterm),
                             AgentPanel (czat agenta + karty zatwierdzania), DiffView, GitPanel
  src/index.css              motyw (Tailwind v4: tokeny + jasny/ciemny) — dawniej styles.css
```

## Kluczowe biblioteki
- **electron-vite** (vite 7) + React 19 + TypeScript
- **Tailwind v4** (CSS-first; tokeny + motywy jasny/ciemny w `src/index.css`)
- **react-markdown** + **rehype-highlight** — render czatu
- **@uiw/react-codemirror** (CodeMirror 6) — edytor modułu Code
- **@xterm/xterm** — terminal modułu Code
- **react-resizable-panels** (v4) — układ paneli (mini-IDE, czat)

## Uwagi
- UI jest po angielsku (zasada projektu); komentarze w kodzie mogą być po polsku.
- Połączenie z backendem: `window.caelo.getCore()` zwraca `{ baseUrl, token, status }`
  używane przez `src/lib/api.ts` do REST i WebSocketów.
