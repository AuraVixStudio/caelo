# grok-core (backend sidecar)

Backend FastAPI uruchamiany przez Electron jako sidecar. W Fazie 0: handshake
(port + token) i autoryzacja tokenem.

## Instalacja (izolowany venv)
```bash
python -m venv .venv
# Windows
.venv\Scripts\pip install -r requirements.txt
# Linux/macOS
.venv/bin/pip install -r requirements.txt
```
> Uwaga: w sieci z przechwytywaniem TLS dodaj do `pip install`:
> `--trusted-host pypi.org --trusted-host files.pythonhosted.org`

## Uruchomienie samodzielne
```bash
# z katalogu repozytorium (nie z grok_core/)
grok_core/.venv/Scripts/python -m grok_core
```
Serwer wybiera wolny port na 127.0.0.1 i wypisuje na stdout linię handshake:
```
__GROK_CORE_READY__ {"port": <int>, "token": "<str>", "version": "<str>"}
```

Zmienne środowiskowe:
- `GROK_CORE_TOKEN` — token sesji (ustawiany przez Electron; inaczej losowany),
- `GROK_CORE_PORT` — wymuszony port (inaczej wolny port).

## Endpointy
Faza 0:
- `GET /health` — bez autoryzacji, liveness.
- `GET /whoami` — wymaga `Authorization: Bearer <token>`.

Faza 1 (REST wymaga nagłówka `Authorization: Bearer <token>`):
- `GET /auth/status`, `POST /auth/login` (OAuth PKCE), `POST /auth/logout`
- `GET /models` — modele czatu/wideo + `default_code` (grok-build-0.1)
- `GET /settings`, `PUT /settings` — klucz API zapisywany, nigdy nie zwracany
- `POST /images/generate`, `POST /images/edit` (obrazy jako data-URI)
- `POST /video/jobs`, `GET /video/jobs/{id}`
- `GET /history`, `GET/PUT /config/output-dir`
- **WS `/chat/stream?token=<token>`** — streaming czatu (token w query, nie w nagłówku)

Faza 4 (agent kodowania):
- `GET/POST /fs/workspace`, `GET /fs/tree`, `GET /fs/read`, `POST /fs/write`
- `GET /git/status`, `GET /git/diff`
- **WS `/agent/stream?token=...`** — agent kodowania (narzędzia + zatwierdzanie)
- **WS `/terminal?token=...`** — terminal (wymaga `pywinpty`)

## Self-checki
```bash
# handshake + /health + autoryzacja /whoami
grok_core/.venv/Scripts/python grok_core/tools/handshake_check.py
# trasy Fazy 1 (REST + WS + egzekwowanie tokenu)
grok_core/.venv/Scripts/python grok_core/tools/api_smoke.py
# silnik agenta Fazy 4 (narzędzia + sandbox + pętla z mockiem)
grok_core/.venv/Scripts/python grok_core/tools/agent_selfcheck.py
```
