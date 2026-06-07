# caelo-core (backend sidecar)

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
# z katalogu repozytorium (nie z caelo_core/)
caelo_core/.venv/Scripts/python -m caelo_core
```
Serwer wybiera wolny port na 127.0.0.1 i wypisuje na stdout linię handshake:
```
__CAELO_CORE_READY__ {"port": <int>, "token": "<str>", "version": "<str>"}
```

Zmienne środowiskowe:
- `CAELO_CORE_TOKEN` — token sesji (ustawiany przez Electron; inaczej losowany),
- `CAELO_CORE_PORT` — wymuszony port (inaczej wolny port).

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

Faza 6 (uprawnienia / git / recent):
- `GET /permissions`, `DELETE /permissions` — allowlista agenta („Always allow")
- `POST /git/add`, `POST /git/commit`
- `GET /fs/recent` — ostatnie workspace

Nadbudowa — media / głos (patrz [`../docs/plans/MODYFIKACJE.md`](../docs/plans/MODYFIKACJE.md)):
- `POST /video/edits`, `POST /video/extensions` — edycja / przedłużanie wideo (odpyt przez `GET /video/jobs/{id}`)
- `POST /voice/tts`, `POST /voice/stt` — TTS / STT (audio base64 w JSON)
- **WS `/voice/realtime?token=...`** — most do `wss://api.x.ai/v1/realtime`
- `GET /models` — dodatkowo: `image`, `voices`, `default_image`, `default_voice`, `realtime_model`

## Self-checki

Uruchamiane przez **pytest** (P3-13) — każda suita to osobny test parametryczny:
```bash
caelo_core/.venv/Scripts/pip install -r caelo_core/requirements-dev.txt  # raz: pytest
caelo_core/.venv/Scripts/python -m pytest caelo_core/tests -v            # wszystkie suity
caelo_core/.venv/Scripts/python -m pytest caelo_core/tests -k api_smoke  # jedna (-k)
```
Każda suita biegnie też jako samodzielny skrypt (ma `main()`):
```bash
caelo_core/.venv/Scripts/python caelo_core/tools/handshake_check.py   # handshake + /whoami
caelo_core/.venv/Scripts/python caelo_core/tools/api_smoke.py         # REST + WS + token
caelo_core/.venv/Scripts/python caelo_core/tools/agent_selfcheck.py   # agent (mock LLM)
```
