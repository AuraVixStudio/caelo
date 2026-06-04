# Grok Desktop

Desktopowa aplikacja dla **Grok (xAI)** w stylu **Claude Code / Codex** — czat, generowanie/edycja obrazów i wideo, oraz **agentowy moduł programistyczny** z dostępem do lokalnych plików (czytanie/edycja, uruchamianie poleceń, drzewo projektu, podgląd diff i zatwierdzanie zmian).

> **Status:** Fazy 0–8 wykonane (2026-06-03); plan i status faz: [`docs/REBUILD_PLAN.md`](docs/REBUILD_PLAN.md).
> Nadbudowa (Image/Video/Voice/załączniki) — żywa specyfikacja: [`docs/MODYFIKACJE.md`](docs/MODYFIKACJE.md);
> hardening do jakości produkcyjnej (P0–P3): [`docs/PLAN_NAPRAWY.md`](docs/PLAN_NAPRAWY.md).
> Aplikacja customtkinter (legacy) została **usunięta z repo** (zachowana jako kopia zewnętrzna) —
> domknięcie Fazy 8. Realne ścieżki xAI (czat/media/głos/OAuth/agent) weryfikuje użytkownik z ważnymi
> poświadczeniami — sandbox blokuje TLS do `api.x.ai`.

To monorepo to przebudowa wcześniejszej aplikacji w customtkinter (Python) na architekturę **Electron (frontend) + Python sidecar (backend)**. Dojrzała logika xAI (OAuth, streaming, media) jest **reużyta**, nie przepisywana od zera.

---

## Architektura

```
┌──────────────────────── Electron (proces główny) ─────────────────────────┐
│  okno, menu, IPC, cykl życia sidecara; spawn `python -m grok_core`         │
│  handshake: generuje token sesji → env GROK_CORE_TOKEN; czyta port ze stdout│
│  preload (contextBridge) → window.grok ; Renderer: React + TypeScript        │
│  Moduły: Chat · Code (mini-IDE) · Image · Video · Voice · History · Settings  │
└───────────────────────────────────────────────────────────────────────────┘
              │  HTTP (REST) + WebSocket (streaming) — tylko 127.0.0.1 + token
              ▼
┌──────────────── Python backend „grok-core" (FastAPI / uvicorn) ────────────┐
│  Reużyte managery legacy: api_manager · oauth_manager · chats · history     │
│  Trasy: /auth /models /settings /chat(WS) /images /video /voice(+WS) /history│
│         /fs /git /permissions /agent(WS) /terminal(WS)                      │
│  Silnik agenta: narzędzia plikowe + sandbox + zatwierdzanie + pętla LLM      │
└───────────────────────────────────────────────────────────────────────────┘
              │  Bearer (OAuth/API key) — wyłącznie do api.x.ai
              ▼  xAI / Grok API
```

## Struktura repo

```
grok_desktop_app/
│
├── desktop/                 # FRONTEND — Electron + React 19 + TS  (zob. desktop/README.md)
│   └── src/{main,preload,renderer}
│
├── grok_core/               # BACKEND — sidecar FastAPI  (zob. grok_core/README.md)
│   ├── server.py            #   montaż tras, app.state (token/backend), lifespan
│   ├── state.py             #   Backend: managery, klucze, workspace, zależności
│   ├── routes/              #   auth, models, settings, chat, media, voice, system, fs, git, permissions, agent, terminal
│   ├── agent/               #   workspace(sandbox), permissions, tools, llm, session
│   ├── tools/               #   self-checki (handshake_check, api_smoke, agent_selfcheck, sidecar_smoke)
│   ├── errors.py · validation.py    #   wspólne helpery tras (sanityzacja błędów, limity wejścia)
│   └── requirements.txt · requirements.lock   #   zależności (luźne) + przypięte (powtarzalny build)
│
├── docs/                    # DOKUMENTACJA  (indeks: docs/README.md)
│   ├── REBUILD_PLAN.md      #   plan przebudowy (Fazy 0–8) + §13 „Faza 9" (stan obecny)
│   ├── MODYFIKACJE.md       #   nadbudowa: Image/Video/Voice/załączniki (żywa specyfikacja)
│   └── PLAN_NAPRAWY.md      #   plan napraw/hardeningu (P0–P3) — zrealizowany
│
├── .github/workflows/ci.yml # CI: self-checki backendu + typecheck frontu
├── .gitignore · CLAUDE.md · README.md          # meta repo
│
└── ─── WSPÓŁDZIELONY RDZEŃ xAI + pakowanie — ZOSTAJE W KORZENIU ───
    (NIE przenosić/zmieniać nazw — patrz CLAUDE.md „single most important structural fact":
     łamie importy grok_core, build PyInstaller i — przez położenie config.py — ścieżki danych)
      config.py               # ścieżki/DATA_DIR, modele, OAuth, design tokens (jego LOKALIZACJA ustala ścieżki danych)
      api_manager.py          # klient xAI: chat/stream, images, video, tts/stt, list_models
      oauth_manager.py        # OAuth PKCE (auth.x.ai) + lokalny callback (z fallbackiem portu)
      chats_manager.py        # magazyn rozmów (grok_chats.json)
      history_manager.py      # historia mediów (wyłączny właściciel grok_config.json)
      make_icon.py            # generator appicon.ico (referencja w config.ICON_FILE)
      grok_core_sidecar.py · grok_core.spec · build_sidecar.ps1   # pakowanie sidecara (PyInstaller onedir)
```

---

## Wymagania
- **Node.js ≥ 20** (testowane na v22)
- **Python 3.10+** (testowane na 3.10/3.11)
- Windows (główna platforma; ścieżki danych i terminal pod Windows)

## Szybki start (dev)

**1) Backend (`grok_core`) — izolowany venv:**
```powershell
cd grok_core
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt   # lub: -r requirements.lock (przypięte wersje — powtarzalny build)
# w sieci z przechwytywaniem TLS dodaj:
#   --trusted-host pypi.org --trusted-host files.pythonhosted.org
cd ..
```

**2) Frontend (`desktop`):**
```powershell
cd desktop
npm ci           # instalacja z package-lock.json (powtarzalna; `npm install` tylko przy zmianie zależności)
npm run dev      # uruchamia okno Electron + spawnuje backend
```

`npm run dev` startuje electron-vite (HMR), proces główny spawnuje sidecar,
czyta handshake (port + token) i łączy się z backendem po 127.0.0.1.

> Proces główny szuka Pythona w kolejności: `GROK_CORE_PYTHON` (env) →
> `grok_core/.venv/Scripts/python.exe` → systemowy `python`.

---

## Moduły
- **Chat** — streaming, multi-rozmowy, picker modelu, system prompt + temperatura, markdown + kod, **załączniki** (obraz/plik) oraz **głos** (TTS odpowiedzi + dyktowanie STT).
- **Code** — mini-IDE: drzewo plików, edytor (CodeMirror), terminal (xterm), **czat agenta** z narzędziami plikowymi i **kartami zatwierdzania** (Accept/Reject/Always) + podgląd diff.
- **Image** — generowanie i edycja obrazów w jednym panelu (bez referencji → generowanie, z referencjami → edycja), wybór modelu, warianty.
- **Video** — generowanie (tekst→wideo / obraz startowy), **edycja** i **przedłużanie** wideo (polling zadania).
- **Voice** — Speak (TTS), Transcribe (STT) i Live (realtime przez WebSocket).
- **History** — historia generacji.
- **Settings** — konto OAuth, klucz API, folder wyjściowy, domyślne modele, uprawnienia agenta.

> Moduły Image/Video/Voice i załączniki to nadbudowa na Fazach 0–8 — szczegóły w [`docs/MODYFIKACJE.md`](docs/MODYFIKACJE.md).

## Bezpieczeństwo
- Backend nasłuchuje **wyłącznie na 127.0.0.1** (niedostępny z sieci).
- REST wymaga `Authorization: Bearer <token>`; WebSockety — token w query (`?token=`).
- Token Bearer xAI wysyłany **tylko** do `api.x.ai`.
- Operacje plikowe agenta **sandboxowane** do katalogu workspace; zmiany plików i polecenia wymagają **zatwierdzenia**.

## Self-checki backendu
```powershell
grok_core\.venv\Scripts\python grok_core\tools\handshake_check.py   # handshake + auth
grok_core\.venv\Scripts\python grok_core\tools\api_smoke.py         # trasy REST/WS
grok_core\.venv\Scripts\python grok_core\tools\agent_selfcheck.py   # narzędzia + pętla agenta (mock)
```

## Znane ograniczenia
- Realne wywołania xAI (treść czatu, obrazy/wideo, logowanie OAuth, przebieg agenta) wymagają ważnych poświadczeń i sieci — weryfikowane na maszynie użytkownika.
- **Terminal** wymaga `pip install pywinpty` w venv backendu (agentowy `run_command` działa bez tego).
- Edytor: **CodeMirror 6** (świadomie zamiast Monaco — patrz `docs/REBUILD_PLAN.md`).
- Pakowanie do instalatora `.exe` — gotowe (Faza 7): sidecar PyInstaller zbudowany i przetestowany; instalator NSIS przez `cd desktop && npm run dist` (pobiera NSIS/electron z sieci — uruchamiane u użytkownika).

## Dokumentacja
- [`docs/README.md`](docs/README.md) — **indeks dokumentacji** (od czego zacząć, co gdzie szukać).
- [`docs/REBUILD_PLAN.md`](docs/REBUILD_PLAN.md) — plan przebudowy, decyzje, status faz 0–8, ryzyka (§13 = stan obecny).
- [`docs/MODYFIKACJE.md`](docs/MODYFIKACJE.md) — nadbudowa (Image/Video/Voice/załączniki) — żywa specyfikacja.
- [`docs/PLAN_NAPRAWY.md`](docs/PLAN_NAPRAWY.md) — plan napraw/hardeningu (P0–P3) i postęp.
- [`desktop/README.md`](desktop/README.md) — frontend (skrypty, struktura, interpreter Pythona).
- [`grok_core/README.md`](grok_core/README.md) — backend (instalacja, endpointy, self-checki).

## Aplikacja legacy (customtkinter)
Stara aplikacja customtkinter **została usunięta z tego repo** (zachowana jako kopia zewnętrzna) —
domknięcie Fazy 8. Współdzielony rdzeń xAI (`config.py`, `api_manager.py`, `oauth_manager.py`,
`chats_manager.py`, `history_manager.py`) **pozostaje w korzeniu** — nie ze względu na legacy, lecz
bo reużywa go sidecar `grok_core` (importy top-level) i build PyInstaller, a `config.py` swoim
położeniem wyznacza ścieżki danych. Aby ponownie uruchomić legacy z kopii, trzeba obok niej umieścić
te moduły rdzenia (wtedy użyje własnego `config.py` → własnego katalogu danych).
