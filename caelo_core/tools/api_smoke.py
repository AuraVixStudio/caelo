"""Smoke-test tras Fazy 1 — odwzorowuje, jak frontend rozmawia z backendem.

Spawnuje `python -m caelo_core`, czyta handshake i weryfikuje:
  REST:  /health, /whoami(token), /auth/status, /models, /settings  -> 200
         /models bez tokenu -> 401, zły token -> 403
         media/voice (P3-1): /images/*, /video/*, /voice/* — auth (401/403)
           oraz kształt wejścia (Pydantic -> 422) BEZ realnego wywołania xAI
  WS:    /chat/stream?token=<ok>   -> połączenie zaakceptowane
         /chat/stream?token=<zły>  -> odrzucone

Unity (bez sieci xAI): autoryzacja WS, timeouty APIManager, most czatu, walidacja
wejścia, dekodowanie SSE jako UTF-8 (P3-1), oraz strażnik własności plików JSON
(P3-1: zapis ustawień nie rusza caelo_config.json — domena HistoryManagera).

Nie wykonuje realnych wywołań xAI (obraz/wideo/czat) — to weryfikuje użytkownik
z ważnymi poświadczeniami. Kod wyjścia 0 = wszystkie asercje OK.
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Uruchamiany jako skrypt (`python caelo_core/tools/api_smoke.py`) — dołóż korzeń
# repo do sys.path PRZED importem pakietu caelo_core (pytest robi to przez conftest).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from caelo_core.tools._smoke_common import (  # noqa: F401
    PREFIX, REPO_DIR, THIS_DIR, PKG_DIR,
    _read_handshake, _get, _post, _delete, _cors_acao, _capture_no_token_warn,
    _isolated_env, _ws_check, _ws_bad_token_rejected,
)

from caelo_core.tools.smoke_chat import (  # noqa: F401,E402
    _unit_responses_client,
    _unit_responses_mcp_loop,
    _unit_chat_bridge,
    _unit_chat_media,
    _unit_sse_utf8,
    _unit_api_timeouts,
)
from caelo_core.tools.smoke_media import (  # noqa: F401,E402
    _unit_collections,
    _unit_voice_converse,
    _unit_media_download_guard,
    _live_media_voice_routes,
    _live_genjobs_routes,
)
from caelo_core.tools.smoke_routes import (  # noqa: F401,E402
    _unit_fs_routes,
    _unit_git_routes,
    _unit_history_routes,
    _unit_projects_routes,
    _unit_agent_routes,
    _unit_permissions_routes,
    _unit_lsp_routes,
    _unit_mcp_routes,
    _unit_team_routes,
    _unit_sessions_routes,
)
from caelo_core.tools.smoke_core import (  # noqa: F401,E402
    _unit_ws_auth,
    _unit_data_dir_override,
    _unit_lazy_init_race,
    _unit_rest_token_auth,
    _unit_input_validation,
    _unit_settings_ownership,
    _unit_json_corrupt_backup,
    _unit_oauth_recovery,
    _unit_history_manager_concurrency,
    _unit_error_sanitization,
    _unit_packages,
    _unit_commands_skills,
)


def main() -> int:
    token = secrets.token_urlsafe(16)
    env, tmp_data = _isolated_env(token)  # P1-E: izolowany DATA_DIR (nie realny repo)
    proc = subprocess.Popen(
        [sys.executable, "-m", "caelo_core"],
        cwd=REPO_DIR, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        info = _read_handshake(proc)
        port = info["port"]
        base = f"http://127.0.0.1:{port}"
        print(f"[handshake] port={port} version={info.get('version')}")

        checks = []

        # P1-E: żywy sidecar NIE może używać realnego DATA_DIR (korzeń repo);
        # inaczej `DELETE /genjobs` w smoke_media kasowałby realną listę zadań.
        checks.append(("P1-E: sidecar runs in isolated DATA_DIR (not repo root)",
                       os.path.isdir(tmp_data)
                       and os.path.abspath(tmp_data) != os.path.abspath(REPO_DIR)))

        s, body = _get(base, "/health")
        checks.append(("/health == 200", s == 200 and bool(body)))

        # P3-4: wersja z JEDNEGO źródła — sidecar (handshake + /health) raportuje
        # wersję z desktop/package.json (tu bez env CAELO_CORE_APP_VERSION → odczyt pliku).
        try:
            pkg_v = json.loads(
                (Path(REPO_DIR) / "desktop" / "package.json").read_text(encoding="utf-8")
            ).get("version")
        except Exception as exc:  # noqa: BLE001
            pkg_v = None
            checks.append((f"version: read desktop/package.json ({exc})", False))
        if pkg_v:
            checks.append(("version: handshake == package.json (single source)",
                           info.get("version") == pkg_v))
            checks.append(("version: /health == package.json",
                           bool(body) and body.get("version") == pkg_v))

        s, body = _get(base, "/whoami", token)
        checks.append(("/whoami(token) == 200 + backend_ready", s == 200 and body and body.get("backend_ready") is True))

        s, body = _get(base, "/auth/status", token)
        checks.append(("/auth/status == 200", s == 200 and body is not None and "authenticated" in body))
        # Przelacznik zrodla auth: status raportuje faktyczne aktywne zrodlo + flagi kluczy.
        checks.append(("/auth/status exposes active_source", body is not None
                       and body.get("active_source") in ("oauth", "api_key", "env", "none")
                       and "has_stored_key" in body and "auth_source" in body))

        s, body = _get(base, "/models", token)
        ok_models = s == 200 and body and isinstance(body.get("chat"), list) and len(body["chat"]) > 0
        checks.append(("/models == 200 + chat list", ok_models))
        if ok_models:
            print(f"  [info] models.default_chat={body.get('default_chat')} default_code={body.get('default_code')} chat_count={len(body['chat'])}")

        s, body = _get(base, "/settings", token)
        checks.append(("/settings == 200", s == 200 and body is not None and "chat_model" in body))

        s, body = _get(base, "/permissions", token)
        checks.append(("/permissions == 200 + rules list", s == 200 and body is not None and isinstance(body.get("rules"), list)))

        s, body = _get(base, "/fs/recent", token)
        checks.append(("/fs/recent == 200 + recent list", s == 200 and body is not None and isinstance(body.get("recent"), list)))

        # M9-B3: historia/artefakty huba — 200 + kształt (treść zależy od stanu bazy).
        s, body = _get(base, "/history", token)
        checks.append(("/history == 200 + events list",
                       s == 200 and body is not None and isinstance(body.get("events"), list)))
        s, body = _get(base, "/artifacts", token)
        checks.append(("/artifacts == 200 + artifacts list",
                       s == 200 and body is not None and isinstance(body.get("artifacts"), list)))
        s, _ = _get(base, "/history")
        checks.append(("/history (no token) == 401", s == 401))
        s, _ = _get(base, "/history", "wrong")
        checks.append(("/history (bad token) == 403", s == 403))
        # M9-B4: send-to bus route guarded + 404 for unknown id (with token).
        s, _ = _get(base, "/artifacts/nope/input-block")
        checks.append(("/artifacts/{id}/input-block (no token) == 401", s == 401))
        s, _ = _get(base, "/artifacts/nope/input-block", token)
        checks.append(("/artifacts/{id}/input-block (unknown id) == 404", s == 404))
        # M11 follow-up: usuwanie artefaktu — token gate + 404 dla nieznanego id.
        s, _ = _delete(base, "/artifacts/nope")
        checks.append(("DELETE /artifacts/{id} (no token) == 401", s == 401))
        s, _ = _delete(base, "/artifacts/does-not-exist", token)
        checks.append(("DELETE /artifacts/{id} (unknown id) == 404", s == 404))

        # M9-B5: projekty huba — 200 + kształt; bramka tokenu.
        s, body = _get(base, "/projects", token)
        checks.append(("/projects == 200 + shape",
                       s == 200 and body is not None and isinstance(body.get("projects"), list)
                       and "current_project_id" in body))
        s, _ = _get(base, "/projects")
        checks.append(("/projects (no token) == 401", s == 401))
        s, _ = _post(base, "/projects/current", {"project_id": None})
        checks.append(("/projects/current (no token) == 401", s == 401))

        # M10-B5: collections (project knowledge / file_search) — 200 + shape; token gate.
        s, body = _get(base, "/collections", token)
        checks.append(("/collections == 200 + shape",
                       s == 200 and body is not None and isinstance(body.get("files"), list)
                       and "has_collection" in body))
        s, _ = _get(base, "/collections")
        checks.append(("/collections (no token) == 401", s == 401))

        # M13-B5: agent checkpoints/undo/caelo-md — 200 + kształt; bramka tokenu.
        s, body = _get(base, "/agent/checkpoints", token)
        checks.append(("/agent/checkpoints == 200 + shape",
                       s == 200 and body is not None and isinstance(body.get("checkpoints"), list)))
        s, _ = _get(base, "/agent/checkpoints")
        checks.append(("/agent/checkpoints (no token) == 401", s == 401))
        s, _ = _post(base, "/agent/undo", {})
        checks.append(("/agent/undo (no token) == 401", s == 401))
        s, _ = _post(base, "/agent/undo", {}, "wrong")
        checks.append(("/agent/undo (bad token) == 403", s == 403))

        # M21: trwałe sesje agenta — 200 + kształt; bramka tokenu (jak checkpoints).
        s, body = _get(base, "/agent/sessions", token)
        checks.append(("/agent/sessions == 200 + shape",
                       s == 200 and body is not None and isinstance(body.get("sessions"), list)))
        s, _ = _get(base, "/agent/sessions")
        checks.append(("/agent/sessions (no token) == 401", s == 401))
        s, _ = _get(base, "/agent/sessions", "wrong")
        checks.append(("/agent/sessions (bad token) == 403", s == 403))

        s, _ = _get(base, "/models")
        checks.append(("/models (no token) == 401", s == 401))
        s, _ = _get(base, "/models", "wrong")
        checks.append(("/models (bad token) == 403", s == 403))

        # P1-9: CORS zawężony — dev loopback dozwolony, obcy origin odcięty.
        checks.append(("CORS allows dev loopback origin",
                       _cors_acao(base, "/health", "http://localhost:5173") == "http://localhost:5173"))
        checks.append(("CORS allows file:// (null) origin",  # spakowany Electron
                       _cors_acao(base, "/health", "null") == "null"))
        checks.append(("CORS blocks foreign origin",
                       _cors_acao(base, "/health", "https://evil.example") is None))

        # P3-1: żywe trasy media/voice — auth (401/403) + kształt wejścia (422),
        # bez dotykania xAI.
        _live_media_voice_routes(base, token, checks)

        # M11: żywe trasy /genjobs — auth + walidacja (422) + list shape + 404.
        _live_genjobs_routes(base, token, checks)

        # P3-1: żywe testy WS wymagają biblioteki `websockets` (z uvicorn[standard]).
        # Wcześniej brak biblioteki dawał CICHY „pass" (fałszywie zielone). Teraz
        # dostępność to osobna asercja, a żywe testy WS pomijamy jawnie, gdy jej brak.
        try:
            import websockets  # type: ignore  # noqa: F401
            has_ws = True
        except Exception:
            has_ws = False
        checks.append(("websockets installed (uvicorn[standard]) for WS tests", has_ws))
        if has_ws:
            ok_acc, bad_rej = asyncio.run(_ws_check(port, token))
            checks.append(("WS /chat/stream (token) accepted", ok_acc))
            checks.append(("WS /chat/stream (bad token) rejected", bad_rej))

            # P0-8: dangerous WS endpoints must reject a bad token too (M12: + voice
            # stt/stream + converse bridges).
            for path in ("/agent/stream", "/terminal", "/voice/realtime",
                         "/voice/stt/stream", "/voice/converse"):
                rej = asyncio.run(_ws_bad_token_rejected(port, path))
                checks.append((f"WS {path} (bad token) rejected", rej))
        else:
            print("  [SKIP] live WS checks — `websockets` not importable (broken venv?)")

        # P0-8: deterministic unit check of the WS auth logic (fail-closed/origin).
        _unit_ws_auth(checks)

        # P1-E: CAELO_CORE_DATA_DIR override przekierowuje DATA_DIR (izolacja smoke).
        _unit_data_dir_override(checks)

        # S31-c: leniwa inicjalizacja managerów Backendu jest thread-safe (jeden obiekt).
        _unit_lazy_init_race(checks)

        # P1-4: every APIManager HTTP call must pass an explicit timeout.
        _unit_api_timeouts(checks)

        # M10-B1/B2/B3: Responses API client — UTF-8, live-search events, citations.
        _unit_responses_client(checks)

        # M14-B2: klient-side function calling w Responses (pętla narzędzi MCP).
        _unit_responses_mcp_loop(checks)

        # M10-B5: collections (file_search) — vector-store client + Backend + routes.
        _unit_collections(checks)

        # P1-3/M10: chat streaming bridge on Responses — deltas, tool_call, citations,
        # legacy fallback, vision gating, file_search attach, single-flight.
        _unit_chat_bridge(checks)

        # M20: chat media-generation tools (function-calling: image inline + video queued).
        _unit_chat_media(checks)

        # M12-B3/B5: voice conversation pipeline — transcript -> Responses -> TTS -> audio,
        # barge-in skips TTS, cost counters.
        _unit_voice_converse(checks)

        # P1-8: route input validation (Pydantic constraints / data-URI checks).
        _unit_input_validation(checks)

        # P3-1: SSE dekodowane jako UTF-8 (strażnik mojibake).
        _unit_sse_utf8(checks)

        # P3-1: zapis ustawień nie rusza caelo_config.json (własność plików JSON).
        _unit_settings_ownership(checks)

        # M6 — stabilność/dane:
        _unit_rest_token_auth(checks)        # P1-10: REST fail-closed bez tokenu
        _unit_json_corrupt_backup(checks)    # P1-11/S31-e: loader z backupem .corrupt
        _unit_oauth_recovery(checks)         # S31-f/g: oauth print→log + lock/backoff
        _unit_history_manager_concurrency(checks)  # S31-m: HistoryManager thread-safe
        _unit_error_sanitization(checks)     # P1-13: git nie wycieka stderr/ścieżek
        _unit_media_download_guard(checks)   # P1-14: https-only + limit rozmiaru

        # M8 — testy tras (P3-8): fs/git in-process (sandbox, round-trip, commit).
        _unit_fs_routes(checks)
        _unit_git_routes(checks)

        # M9-B3: trasy historii/artefaktów (lista + filtry FTS + content + anty-traversal).
        _unit_history_routes(checks)

        # M9-B5: trasy projektów (list/create/select) + stemplowanie aktywnym projektem.
        _unit_projects_routes(checks)

        # M13-B5: trasy agenta (checkpoints/undo/caelo-md) — in-process.
        _unit_agent_routes(checks)

        # M21: trwałe sesje agenta (lista/filtr po projekcie/odczyt/kasowanie) — in-process.
        _unit_sessions_routes(checks)

        # M19-B4: trasy /permissions/rules (reguły glob — walidacja/persystencja/przebudowa).
        _unit_permissions_routes(checks)

        # M19-B3: trasy /lsp (serwery języka — lista/dodaj/usuń).
        _unit_lsp_routes(checks)

        # M14-B1/F1: trasy /mcp (serwery MCP) — in-process (remote + stdio mock).
        _unit_mcp_routes(checks)

        # M14-B4/B6: rejestr komend slash + biblioteka skilli (in-process).
        _unit_commands_skills(checks)

        # M16: trasy /packages (marketplace — eksport/inspect/install/szablony).
        _unit_packages(checks)

        # M17: trasy zespołu (role/limity/scalenia/przebiegi) — in-process.
        _unit_team_routes(checks)

        ok = True
        for name, passed in checks:
            print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
            ok = ok and passed
        print("RESULT:", "OK" if ok else "FAILED")
        return 0 if ok else 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        shutil.rmtree(tmp_data, ignore_errors=True)  # P1-E: sprzątanie temp DATA_DIR


if __name__ == "__main__":
    sys.exit(main())
