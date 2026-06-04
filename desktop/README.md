# grok-desktop (Electron + React + TypeScript)

Frontend aplikacji Grok Desktop. Spawnuje backend Python (`grok_core`) jako
sidecar i łączy się z nim po 127.0.0.1 z tokenem sesji (handshake). Zob. też
[`../README.md`](../README.md).

## Wymagania
- Node.js ≥ 20 (testowane na v22)
- Backend `grok_core` z zainstalowanym venv (zob. `../grok_core/README.md`)

## Uruchomienie (dev)
```powershell
npm install      # instaluje WSZYSTKIE zależności z package.json (jednorazowo)
npm run dev      # Electron + Vite HMR; proces główny spawnuje `python -m grok_core`
```
> Po dołożeniu nowych zależności zrestartuj `npm run dev` — Vite musi je przeoptymalizować.

## Skrypty
- `npm run dev` — tryb deweloperski (Electron + Vite HMR)
- `npm run build` — produkcyjny build (main + preload + renderer → `out/`)
- `npm run typecheck` — sprawdzenie typów (node + web)
- `npm run pack:sidecar` — buduje sidecar PyInstaller (`../build_sidecar.ps1` → `../dist/grok-core`)
- `npm run dist` — instalator NSIS (zakłada zbudowany sidecar w `../dist/grok-core`)
- `npm run dist:full` — pełny pipeline: sidecar → frontend build → instalator NSIS

## Pakowanie (instalator .exe — Faza 7)
Dwa artefakty: **spakowany sidecar** (PyInstaller onedir) + **instalator Electrona** (electron-builder NSIS).

```powershell
# 1) Sidecar: PyInstaller onedir z grok_core\.venv  ->  ..\dist\grok-core\grok-core.exe
npm run pack:sidecar
#    (weryfikacja samego sidecara, bez Electrona:)
..\grok_core\.venv\Scripts\python ..\grok_core\tools\sidecar_smoke.py

# 2) Instalator: frontend build + electron-builder  ->  dist\Grok-Desktop-Setup-<wersja>.exe
npm run dist

# lub wszystko naraz:
npm run dist:full
```

- **Sidecar** definiuje `..\grok_core.spec` (onedir = szybki start, brak rozpakowywania do tempa).
  Bundluje uvicorn/FastAPI + legacy `config/api_manager/oauth_manager/chats_manager/history_manager`
  (deklarowane jako `hiddenimports`, bo `grok_core/__init__.py` dokłada korzeń do `sys.path` dopiero
  w runtime). Terminal (`pywinpty`) dołączany, jeśli zainstalowany w venv.
- **Electron** (`electron-builder.yml`): cały katalog `..\dist\grok-core` ląduje w `resources\grok-core`.
  W trybie spakowanym (`app.isPackaged`) proces główny uruchamia `grok-core.exe` z `resources`
  (`windowsHide` ukrywa jego konsolę), zamiast `python -m grok_core`.
- **Dane**: w wersji spakowanej sidecar ma `sys.frozen=True`, więc `config.DATA_DIR` =
  `%LOCALAPPDATA%\AI Studio Pro` (współdzielone z legacy app do Fazy 8).
- **Ikona**: `desktop\build\icon.ico` (dołączona; wygenerowana z `..\make_icon.py`, komplet 16–256 px) —
  electron-builder wykrywa ją automatycznie. Aby zmienić logo, podmień ten plik.
- **Nadzór**: proces główny robi health-check `/health` co 10 s i restartuje sidecar po padzie
  (do 5 prób z narastającym backoffem); przy zamknięciu aplikacji zabija sidecar.

## Wybór interpretera Pythona (sidecar)
Proces główny szuka Pythona w kolejności:
1. zmienna środowiskowa `GROK_CORE_PYTHON`,
2. venv backendu: `../grok_core/.venv/Scripts/python.exe` (Windows),
3. systemowy `python` / `python3`.

```powershell
$env:GROK_CORE_PYTHON = "C:\sciezka\do\python.exe"; npm run dev
```

## Struktura
```
src/main/index.ts            proces główny: spawn sidecara, handshake, IPC (folder/openPath), okno
src/preload/index.ts         contextBridge → window.grok (getCore, onCoreStatus, selectFolder, openPath)
src/renderer/
  src/App.tsx                rail modułów + routing
  src/types.ts               typy współdzielone (CoreConnection, window.grok)
  src/lib/                   api.ts (REST+WS), agentClient.ts (WS agenta),
                             storage.ts (rozmowy), useConnection.ts, constants.ts
  src/components/            ChatView, CodeView, Generator, Edit, Video, History,
                             Settings, Markdown, MediaGallery, Placeholder
  src/components/code/       FileTree, CodeEditor (CodeMirror), Terminal (xterm),
                             AgentPanel (czat agenta + karty zatwierdzania), DiffView
  src/styles.css             motyw + style modułów
```

## Kluczowe biblioteki
- **electron-vite** (vite 7) + React 19 + TypeScript
- **react-markdown** + **rehype-highlight** — render czatu
- **@uiw/react-codemirror** (CodeMirror 6) — edytor modułu Code
- **@xterm/xterm** — terminal modułu Code

## Uwagi
- UI jest po angielsku (zasada projektu); komentarze w kodzie mogą być po polsku.
- Połączenie z backendem: `window.grok.getCore()` zwraca `{ baseUrl, token, status }`
  używane przez `src/lib/api.ts` do REST i WebSocketów.
