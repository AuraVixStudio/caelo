"""api_smoke — grupa self-checków: smoke_core (P3-13 split). Funkcje `_unit_*`/`_live_*(checks)` wołane przez `api_smoke.main()`."""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from caelo_core.tools._smoke_common import (  # noqa: F401
    PREFIX, REPO_DIR, THIS_DIR, PKG_DIR,
    _read_handshake, _get, _post, _delete, _cors_acao, _capture_no_token_warn,
    _ws_check, _ws_bad_token_rejected,
)


def _unit_ws_auth(checks: list) -> None:
    """Deterministyczny test logiki autoryzacji WS (P0-8) — bez sieci, na atrapie."""
    import types

    sys.path.insert(0, REPO_DIR)
    from caelo_core.state import _ws_origin_ok, ws_authorized  # noqa: E402

    def fake(state_token: str, qtoken=None, origin=None):
        return types.SimpleNamespace(
            app=types.SimpleNamespace(state=types.SimpleNamespace(session_token=state_token)),
            query_params=({"token": qtoken} if qtoken is not None else {}),
            headers=({"origin": origin} if origin is not None else {}),
        )

    checks.append(("ws_auth: valid token accepted", ws_authorized(fake("secret", "secret")) is True))
    checks.append(("ws_auth: bad token rejected", ws_authorized(fake("secret", "nope")) is False))
    checks.append(("ws_auth: missing token rejected", ws_authorized(fake("secret")) is False))

    os.environ.pop("CAELO_CORE_ALLOW_NO_TOKEN", None)
    checks.append(("ws_auth: no-token config -> DENIED (fail-closed)", ws_authorized(fake("", "x")) is False))
    os.environ["CAELO_CORE_ALLOW_NO_TOKEN"] = "1"
    checks.append(("ws_auth: explicit opt-in allows no-token", ws_authorized(fake("", "x")) is True))
    os.environ.pop("CAELO_CORE_ALLOW_NO_TOKEN", None)
    checks.append(("ws_auth: no-token serves WARNING log (P2-14)",
                   _capture_no_token_warn(lambda: ws_authorized(fake("", "x")))))

    checks.append(("ws_auth: foreign origin rejected", ws_authorized(fake("secret", "secret", "https://evil.example")) is False))
    checks.append(("ws_auth: loopback origin ok", ws_authorized(fake("secret", "secret", "http://localhost:5173")) is True))
    checks.append(("origin: file:// ok", _ws_origin_ok("file://") is True))
    checks.append(("origin: null/none ok", _ws_origin_ok("null") is True and _ws_origin_ok(None) is True))


def _unit_lazy_init_race(checks: list) -> None:
    """S31-c: `_lazy` (double-checked) zwraca JEDEN obiekt i woła fabrykę RAZ pod
    współbieżnym pierwszym dostępem — bez tego dwa równoległe requesty FastAPI budowały
    dwa managery (drugi `GenJobManager._reap_stale` failowałby zadania pierwszego)."""
    import threading as _t

    sys.path.insert(0, REPO_DIR)
    from caelo_core.state import Backend

    b = Backend.__new__(Backend)  # bez __init__ (bez I/O); _lazy_lock jest KLASOWY
    b._x = None
    built = {"n": 0}
    built_lock = _t.Lock()
    barrier = _t.Barrier(16)
    seen: set = set()
    seen_lock = _t.Lock()

    def factory():
        with built_lock:
            built["n"] += 1
        time.sleep(0.005)  # poszerz okno wyścigu
        return object()

    def worker():
        barrier.wait()
        obj = b._lazy("_x", factory)
        with seen_lock:
            seen.add(id(obj))

    threads = [_t.Thread(target=worker) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    checks.append(("backend: _lazy returns one instance under concurrency (S31-c)",
                   len(seen) == 1 and built["n"] == 1))


def _unit_data_dir_override(checks: list) -> None:
    """P1-E: CAELO_CORE_DATA_DIR przekierowuje DATA_DIR i WSZYSTKIE stałe pochodne
    (SETTINGS_FILE/HISTORY_DB_FILE/…). To gwarancja, że spawnowany sidecar self-checków
    siada na izolowanym katalogu, nie na realnym repo. Reload w izolacji, potem restore."""
    import importlib
    import shutil
    import tempfile

    sys.path.insert(0, REPO_DIR)
    import config  # type: ignore  # noqa: E402

    prev = os.environ.get("CAELO_CORE_DATA_DIR")
    tmp = tempfile.mkdtemp(prefix="caelo-cfg-")
    try:
        os.environ["CAELO_CORE_DATA_DIR"] = tmp
        importlib.reload(config)
        checks.append(("P1-E: CAELO_CORE_DATA_DIR redirects DATA_DIR + derived paths",
                       config.DATA_DIR == Path(tmp)
                       and config.SETTINGS_FILE.parent == Path(tmp)
                       and config.HISTORY_DB_FILE.parent == Path(tmp)))
    finally:
        if prev is None:
            os.environ.pop("CAELO_CORE_DATA_DIR", None)
        else:
            os.environ["CAELO_CORE_DATA_DIR"] = prev
        importlib.reload(config)  # przywróć DATA_DIR = korzeń repo dla reszty smoke
        shutil.rmtree(tmp, ignore_errors=True)


def _unit_rest_token_auth(checks: list) -> None:
    """P1-10: require_token jest FAIL-CLOSED bez skonfigurowanego tokenu (jak WS)."""
    import types

    sys.path.insert(0, REPO_DIR)
    from fastapi import HTTPException  # noqa: E402
    from caelo_core.state import require_token  # noqa: E402

    def fake(state_token: str):
        return types.SimpleNamespace(
            app=types.SimpleNamespace(state=types.SimpleNamespace(session_token=state_token)))

    def raises(state_token, authorization, status) -> bool:
        try:
            require_token(fake(state_token), authorization)
            return False
        except HTTPException as e:
            return e.status_code == status

    checks.append(("rest_auth: valid bearer accepted",
                   require_token(fake("secret"), "Bearer secret") is None))
    checks.append(("rest_auth: missing bearer rejected (401)", raises("secret", None, 401)))
    checks.append(("rest_auth: bad bearer rejected (403)", raises("secret", "Bearer nope", 403)))

    os.environ.pop("CAELO_CORE_ALLOW_NO_TOKEN", None)
    checks.append(("rest_auth: no-token config -> DENIED (fail-closed)",
                   raises("", "Bearer anything", 401)))
    os.environ["CAELO_CORE_ALLOW_NO_TOKEN"] = "1"
    checks.append(("rest_auth: explicit opt-in allows no-token",
                   require_token(fake(""), None) is None))
    os.environ.pop("CAELO_CORE_ALLOW_NO_TOKEN", None)
    checks.append(("rest_auth: no-token serves WARNING log (P2-14)",
                   _capture_no_token_warn(lambda: require_token(fake(""), None))))


def _unit_input_validation(checks: list) -> None:
    """P1-8: modele tras odrzucają złe wejście (Pydantic → 422)."""
    sys.path.insert(0, REPO_DIR)
    from pydantic import ValidationError  # noqa: E402
    from caelo_core.routes.media import EditImageReq, GenerateImageReq, VideoExtendReq  # noqa: E402
    from caelo_core.routes.voice import TTSReq  # noqa: E402

    def rejects(fn) -> bool:
        try:
            fn()
        except ValidationError:
            return True
        except Exception:
            return False
        return False

    ok = True
    try:
        GenerateImageReq(prompt="a cat", n=2)
        EditImageReq(prompt="x", images=["data:image/png;base64,AAAA"])
        TTSReq(text="hello")
        VideoExtendReq(prompt="x", video="https://x/v.mp4", duration=5)
    except Exception:
        ok = False
    checks.append(("validation: valid input accepted", ok))
    checks.append(("validation: n out of range rejected",
                   rejects(lambda: GenerateImageReq(prompt="x", n=999))))
    checks.append(("validation: empty prompt rejected",
                   rejects(lambda: GenerateImageReq(prompt="", n=1))))
    checks.append(("validation: non-data-URI image rejected",
                   rejects(lambda: EditImageReq(prompt="x", images=["http://evil/x.png"]))))
    checks.append(("validation: too many images rejected",
                   rejects(lambda: EditImageReq(prompt="x", images=["data:image/png;base64,AA"] * 50))))
    checks.append(("validation: extend duration out of range rejected",
                   rejects(lambda: VideoExtendReq(prompt="x", video="https://x/v.mp4", duration=99))))
    checks.append(("validation: empty TTS text rejected", rejects(lambda: TTSReq(text=""))))


def _unit_settings_ownership(checks: list) -> None:
    """P3-1: zapis ustawień NIE rusza caelo_config.json (CLAUDE.md: ten plik jest
    wyłączną domeną HistoryManagera — zapis czegokolwiek innego kasuje dane).

    Przekierowujemy WSZYSTKIE pliki danych do tempdir (config.* oraz nazwy już
    zaimportowane do legacy modułów), siejemy sentinel w caelo_config.json, robimy
    Backend.update_settings(...) i sprawdzamy, że caelo_config.json jest nietknięty,
    a patch trafił do caelo_settings.json. Oryginalne ścieżki przywracamy w finally."""
    import tempfile

    sys.path.insert(0, REPO_DIR)
    import config  # type: ignore  # noqa: E402
    import chats_manager  # type: ignore  # noqa: E402
    import history_manager  # type: ignore  # noqa: E402
    import oauth_manager  # type: ignore  # noqa: E402
    from caelo_core.state import Backend  # noqa: E402

    # config.* czytane są dynamicznie (atrybut); ale legacy moduły zrobiły
    # `from config import CONFIG_FILE/HISTORY_DIR/CHATS_FILE/AUTH_FILE` → trzeba podmienić też u nich.
    # P1-E (izolacja): oauth_manager zrobił `from config import AUTH_FILE`, więc bez podmiany
    # u niego OAuthManager czytałby REALNY caelo_auth.json dewelopera (zalogowany → „oauth
    # dostępne") i fałszywie psułby asercje „no oauth".
    saved_cfg = {k: getattr(config, k) for k in
                 ("SETTINGS_FILE", "CONFIG_FILE", "CHATS_FILE", "PERMISSIONS_FILE",
                  "AUTH_FILE", "HISTORY_DIR")}
    saved_hist = (history_manager.CONFIG_FILE, history_manager.HISTORY_DIR)
    saved_chats = chats_manager.CHATS_FILE
    saved_oauth = oauth_manager.AUTH_FILE

    with tempfile.TemporaryDirectory() as d:
        dp = __import__("pathlib").Path(d)
        try:
            config.SETTINGS_FILE = dp / "caelo_settings.json"
            config.CONFIG_FILE = dp / "caelo_config.json"
            config.CHATS_FILE = dp / "caelo_chats.json"
            config.PERMISSIONS_FILE = dp / "caelo_permissions.json"
            config.AUTH_FILE = dp / "caelo_auth.json"
            config.HISTORY_DIR = dp / "generated_history"
            config.HISTORY_DIR.mkdir(exist_ok=True)
            history_manager.CONFIG_FILE = config.CONFIG_FILE
            history_manager.HISTORY_DIR = config.HISTORY_DIR
            chats_manager.CHATS_FILE = config.CHATS_FILE
            oauth_manager.AUTH_FILE = config.AUTH_FILE  # P1-E: izoluj OAuth od realnego loginu

            # Sentinel w domenie HistoryManagera (history/chat_history/save_path).
            sentinel = json.dumps(
                {"history": [{"mode": "generate", "url": "x", "prompt": "p"}],
                 "chat_history": [], "save_path": str(config.HISTORY_DIR)},
                ensure_ascii=False, indent=2)
            config.CONFIG_FILE.write_text(sentinel, encoding="utf-8")
            before = config.CONFIG_FILE.read_text(encoding="utf-8")

            b = Backend()
            b.update_settings({"chat_model": "grok-4", "api_key": "sk-SECRET-should-stay-put"})

            after = config.CONFIG_FILE.read_text(encoding="utf-8")
            checks.append(("settings ownership: caelo_config.json untouched by settings write",
                           after == before))

            s = json.loads(config.SETTINGS_FILE.read_text(encoding="utf-8"))
            checks.append(("settings ownership: patch persisted to caelo_settings.json",
                           s.get("chat_model") == "grok-4"))
            checks.append(("settings ownership: api key stored (has_api_key)",
                           b.has_api_key() is True))

            # Przelacznik zrodla auth (TWARDY): jawny wybor nie przeskakuje po cichu.
            # Backend testowy: brak logowania OAuth -> oauth niedostepny.
            checks.append(("auth source: stored key active under auto (no oauth)",
                           b.has_stored_key() is True and b.active_auth_source() == "api_key"))
            checks.append(("auth: is_authenticated true when a source is active (S31-h)",
                           b.is_authenticated() is True))
            b.update_settings({"auth_source": "oauth"})
            checks.append(("auth source: preference persisted",
                           b.auth_source_pref() == "oauth"))
            checks.append(("auth source: forced oauth + no login -> none (hard switch)",
                           b.active_auth_source() == "none"))
            checks.append(("auth: is_authenticated false when forced source unavailable (S31-h)",
                           b.is_authenticated() is False))
            b.update_settings({"auth_source": "api_key"})
            checks.append(("auth source: forced api_key uses stored key (ignores oauth)",
                           b.active_auth_source() == "api_key"))
            b.clear_api_key()
            checks.append(("auth source: clear_api_key removes stored key",
                           b.has_stored_key() is False))
        except Exception as exc:  # noqa: BLE001
            checks.append((f"settings ownership: scenario ran ({exc})", False))
        finally:
            for k, v in saved_cfg.items():
                setattr(config, k, v)
            history_manager.CONFIG_FILE, history_manager.HISTORY_DIR = saved_hist
            chats_manager.CHATS_FILE = saved_chats
            oauth_manager.AUTH_FILE = saved_oauth


def _unit_json_corrupt_backup(checks: list) -> None:
    """P1-11: load_json_or_backup — brak pliku → default; korupcja → kopia .corrupt."""
    import tempfile
    from pathlib import Path

    sys.path.insert(0, REPO_DIR)
    import config  # type: ignore  # noqa: E402

    with tempfile.TemporaryDirectory() as d:
        missing = Path(d) / "nope.json"
        checks.append(("json loader: missing file -> default",
                       config.load_json_or_backup(missing, {"x": 1}) == {"x": 1}))

        good = Path(d) / "good.json"
        good.write_text('{"a": 2}', encoding="utf-8")
        checks.append(("json loader: valid json returned",
                       config.load_json_or_backup(good, None) == {"a": 2}))

        bad = Path(d) / "bad.json"
        bad.write_text("{not valid json", encoding="utf-8")
        res = config.load_json_or_backup(bad, {"fallback": True})
        backup = Path(str(bad) + ".corrupt")
        checks.append(("json loader: corrupt -> default", res == {"fallback": True}))
        checks.append(("json loader: corrupt moved to .corrupt (original gone)",
                       backup.exists() and not bad.exists()))

        # S31-e: BŁĄD ODCZYTU (OSError) ≠ korupcja — plik zostaje nietknięty, zwracamy default
        # (tu żyją tokeny/klucz, więc przejściowy I/O nie może po cichu kasować configu).
        valid = Path(d) / "valid.json"
        valid.write_text('{"keep": true}', encoding="utf-8")
        orig_read = Path.read_text

        def _boom(self, *a, **k):
            if self == valid:
                raise OSError("simulated sharing violation")
            return orig_read(self, *a, **k)

        Path.read_text = _boom
        try:
            res2 = config.load_json_or_backup(valid, {"default": 1})
        finally:
            Path.read_text = orig_read
        corrupt2 = Path(str(valid) + ".corrupt")
        checks.append(("json loader: OSError -> default, file left intact (S31-e)",
                       res2 == {"default": 1} and valid.exists() and not corrupt2.exists()))


def _unit_history_manager_concurrency(checks: list) -> None:
    """S31-m: współbieżne save_to_history (workery genjobs + czat) nie gubią wpisów —
    lock serializuje read-modify-write+persist. Bez locka stary snapshot nadpisywał plik."""
    import tempfile
    import threading as _t
    from pathlib import Path

    sys.path.insert(0, REPO_DIR)
    import config  # type: ignore  # noqa: E402
    import history_manager  # type: ignore  # noqa: E402

    saved = (config.CONFIG_FILE, config.HISTORY_DIR,
             history_manager.CONFIG_FILE, history_manager.HISTORY_DIR)
    with tempfile.TemporaryDirectory() as d:
        dp = Path(d)
        config.CONFIG_FILE = dp / "caelo_config.json"
        config.HISTORY_DIR = dp / "gen"
        config.HISTORY_DIR.mkdir()
        history_manager.CONFIG_FILE = config.CONFIG_FILE
        history_manager.HISTORY_DIR = config.HISTORY_DIR
        try:
            hm = history_manager.HistoryManager()
            T, M = 8, 30
            barrier = _t.Barrier(T)

            def worker(tid: int) -> None:
                barrier.wait()
                for i in range(M):
                    hm.save_to_history("generate", f"u{tid}-{i}", "p")

            threads = [_t.Thread(target=worker, args=(t,)) for t in range(T)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(20)
            reloaded = history_manager.HistoryManager()  # czyta plik z dysku
            checks.append(("history_manager: concurrent saves lose no entries (S31-m)",
                           len(reloaded.history) == min(T * M, 500)))
        finally:
            (config.CONFIG_FILE, config.HISTORY_DIR,
             history_manager.CONFIG_FILE, history_manager.HISTORY_DIR) = saved


def _unit_oauth_recovery(checks: list) -> None:
    """S31-f: login() nie pisze na stdout (print→log, kontrakt handshake). S31-g: lock to
    RLock + backoff po nieudanym refreshu (drugie wywołanie nie sieciuje w cooldownie)."""
    import inspect
    import threading as _t
    import types

    sys.path.insert(0, REPO_DIR)
    import oauth_manager as OM  # type: ignore  # noqa: E402

    checks.append(("oauth: login() has no print() to stdout (S31-f)",
                   "print(" not in inspect.getsource(OM.OAuthManager.login)))

    mgr = OM.OAuthManager()
    checks.append(("oauth: lock is reentrant RLock (S31-g)",
                   isinstance(mgr._lock, type(_t.RLock()))))

    # backoff: wygasły token + nieudany refresh → 2× get_access_token = 1 strzał sieciowy
    mgr.tokens = {"access_token": "old", "refresh_token": "rt", "expires_at": 1}
    mgr._refresh_fail_until = 0.0
    calls = {"n": 0}

    class _Resp:
        status_code = 500
        text = "err"

        def json(self):
            return {}

    def _post(*a, **k):
        calls["n"] += 1
        return _Resp()

    prev = OM.requests
    OM.requests = types.SimpleNamespace(post=_post, get=getattr(prev, "get", None))
    try:
        r1 = mgr.get_access_token()
        r2 = mgr.get_access_token()
    finally:
        OM.requests = prev
    checks.append(("oauth: failed refresh backs off (1 network call across 2 calls) (S31-g)",
                   r1 is None and r2 is None and calls["n"] == 1))


def _unit_error_sanitization(checks: list) -> None:
    """P1-13: git nie zwraca surowego stderr (ścieżek FS) — generyczny detail."""
    import types
    from pathlib import Path

    sys.path.insert(0, REPO_DIR)
    from fastapi import HTTPException  # noqa: E402
    from caelo_core.routes import git as git_route  # noqa: E402

    abs_path = "C:\\Users\\victim\\secret\\repo\\.git"
    fakews = types.SimpleNamespace(root=Path("."))

    orig = git_route._run_git
    git_route._run_git = lambda ws, args, timeout=20: (1, "", f"fatal: {abs_path}")
    try:
        st = git_route.status(ws=fakews)
        checks.append(("error sanit: git status detail generic (no abs path)",
                       abs_path not in (st.get("detail") or "")))
        try:
            git_route.commit(types.SimpleNamespace(message="x", stage_all=False), ws=fakews)
            commit_detail = ""
        except HTTPException as e:
            commit_detail = str(e.detail)
        checks.append(("error sanit: git commit detail generic (no abs path)",
                       abs_path not in commit_detail and commit_detail == "git commit failed"))
    finally:
        git_route._run_git = orig


def _unit_packages(checks: list) -> None:
    """M16: trasy /packages — eksport→inspect→install (za zgodą), brak auto-run,
    szablony, odinstalowanie. Backend bez __init__ (manager na temp configu)."""
    import tempfile
    from pathlib import Path

    sys.path.insert(0, REPO_DIR)
    from fastapi import HTTPException  # noqa: E402
    from caelo_core.commands import CommandRegistry  # noqa: E402
    from caelo_core.mcp.manager import McpManager  # noqa: E402
    from caelo_core.packages.manager import PackageManager  # noqa: E402
    from caelo_core.routes import packages as pr  # noqa: E402
    from caelo_core.state import Backend  # noqa: E402

    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        b = Backend.__new__(Backend)
        b._packages = PackageManager(
            d / "caelo_packages.json", d / "skills", d / "templates",
            command_registry=CommandRegistry(d / "caelo_commands.json", d / "commands"),
            mcp_manager=McpManager(d / "caelo_mcp.json"), app_version="1.1")
        try:
            # szablony wbudowane widoczne
            tids = {t["id"] for t in pr.list_templates(b=b)["templates"]}
            checks.append(("/packages/templates lists builtins",
                           {"renpy-vn-starter", "daz-render-pipeline"} <= tids))

            # eksport komendy → pakiet
            b._packages._commands.add_command(
                {"name": "greet", "template": "Hi {input}", "target": "chat"})
            ex = pr.export_package(pr.ExportReq(type="command", ref="greet"), b=b)
            checks.append(("/packages/export produces .caelopkg + base64",
                           ex["filename"].endswith(".caelopkg") and bool(ex["data_b64"])))

            # inspect (bez instalacji) zwraca integralność + manifest
            rep = pr.inspect_package(pr.InspectReq(data_b64=ex["data_b64"]), b=b)["report"]
            checks.append(("/packages/inspect integrity + no install",
                           rep["integrity_ok"] is True and rep["manifest"]["type"] == "command"
                           and not pr.list_packages(b=b)["packages"]))

            # install bez zgody → 400
            no_consent = False
            try:
                pr.install_package(pr.InstallReq(data_b64=ex["data_b64"], consent=False), b=b)
            except HTTPException as e:
                no_consent = e.status_code == 400
            checks.append(("/packages/install without consent -> 400", no_consent))

            # install za zgodą → zarejestrowane
            b._packages._commands.remove_command("greet")
            res = pr.install_package(pr.InstallReq(data_b64=ex["data_b64"], consent=True), b=b)
            checks.append(("/packages/install with consent records package",
                           res["installed"]["id"] == "greet"
                           and b._packages._commands.get("greet") is not None))

            # registry parse (in-process, bez sieci)
            entries = b._packages.parse_registry(
                {"packages": [{"id": "greet", "type": "command", "version": "2.0.0",
                               "url": "https://x/greet.caelopkg"}]})
            ups = b._packages.check_updates(entries)
            greet_up = next((u for u in ups if u["id"] == "greet"), {})
            checks.append(("/packages updates: has_update flagged",
                           greet_up.get("has_update") is True))

            # odinstalowanie
            checks.append(("/packages DELETE uninstalls",
                           pr.uninstall_package("greet", type="command", b=b)["ok"] is True
                           and not pr.list_packages(b=b)["packages"]))

            # zła nazwa base64 → 400
            bad_b64 = False
            try:
                pr.inspect_package(pr.InspectReq(data_b64="!!notbase64!!"), b=b)
            except HTTPException as e:
                bad_b64 = e.status_code == 400
            checks.append(("/packages/inspect bad base64 -> 400", bad_b64))
        except Exception as exc:  # noqa: BLE001
            checks.append((f"packages routes: scenario ran ({exc})", False))
        finally:
            b._packages._mcp.shutdown()


def _unit_commands_skills(checks: list) -> None:
    """M14-B4/B6: rejestr komend (wbudowane + użytkownika, expand, override, mode) i
    biblioteka skilli (wbudowane Ren'Py/DAZ odkryte, get/enable/inject/create/delete,
    sandbox)."""
    import tempfile
    from pathlib import Path

    sys.path.insert(0, REPO_DIR)
    from caelo_core.commands import CommandRegistry  # noqa: E402
    from caelo_core.markdown_meta import parse_frontmatter  # noqa: E402
    from caelo_core.skills import SkillManager  # noqa: E402

    # --- frontmatter ---
    meta, body = parse_frontmatter("---\nname: X\ntriggers: [a, b]\nenabled: true\n---\nBODY\n")
    checks.append(("B4: frontmatter parses list/bool/body",
                   meta.get("name") == "X" and meta.get("triggers") == ["a", "b"]
                   and meta.get("enabled") is True and body.strip() == "BODY"))
    checks.append(("B4: no frontmatter -> body intact",
                   parse_frontmatter("just text")[1] == "just text"))

    # --- komendy ---
    with tempfile.TemporaryDirectory() as d:
        reg = CommandRegistry(Path(d) / "caelo_commands.json", Path(d) / "commands")
        names = {c["name"] for c in reg.list_commands()}
        checks.append(("B4: builtins present",
                       {"plan", "review", "commit", "test", "mcp"} <= names))
        plan = reg.get("plan")
        checks.append(("B4: /plan carries plan mode (drives gate)",
                       plan and plan.get("mode") == "plan" and plan.get("target") == "agent"))
        checks.append(("B4: expand substitutes {input}",
                       "refactor X" in reg.expand("plan", "refactor X")))
        checks.append(("B4: expand unknown -> raw input", reg.expand("nope", "hello") == "hello"))
        # komenda użytkownika: dodanie, trwałość, override builtina
        reg.add_command({"name": "review", "template": "MY REVIEW {input}", "target": "chat"})
        reg.add_command({"name": "deploy", "template": "Deploy to {input}"})
        reg2 = CommandRegistry(Path(d) / "caelo_commands.json", Path(d) / "commands")
        rv = reg2.get("review")
        checks.append(("B4: user command persists + overrides builtin",
                       rv and rv["template"] == "MY REVIEW {input}" and rv["builtin"] is False))
        checks.append(("B4: user command added", reg2.get("deploy") is not None))
        checks.append(("B4: remove builtin-shadow falls back to builtin",
                       reg2.remove_command("review") and reg2.get("review")["builtin"] is True))
        bad = False
        try:
            reg2.add_command({"name": "bad name!", "template": "x"})
        except ValueError:
            bad = True
        checks.append(("B4: invalid command name rejected", bad))

    # --- skille ---
    with tempfile.TemporaryDirectory() as d:
        sm = SkillManager(Path(d))
        ids = {s["id"] for s in sm.list_skills()}
        checks.append(("B6: general builtin skills discovered",
                       {"commit", "write-tests", "refactor", "debug",
                        "document-code", "explain-codebase"} <= ids))
        # M19-B6: wbudowane skille-orkiestratory (pętle wieloagentowe)
        checks.append(("B6: orchestration builtin skills discovered",
                       {"implement", "review", "design", "best-of-n",
                        "check-work", "pr-babysit"} <= ids))
        sk = sm.get_skill("commit")
        checks.append(("B6: get_skill returns body + builtin flag",
                       sk and "commit" in sk["body"].lower() and sk["builtin"] is True))
        checks.append(("B6: disabled skill not injected", sm.injected_text() == ""))
        sm.set_enabled("commit", True)
        inj = sm.injected_text()
        checks.append(("B6: enabled skill injected into context",
                       "Commit" in inj and "Active skills" in inj))
        # M19-B6: skill-orkiestrator wstrzykuje instrukcję sterowania `delegate`
        sm.set_enabled("implement", True)
        inj_impl = sm.injected_text(["implement"])
        checks.append(("B6: orchestration skill injects delegate-loop guidance",
                       "delegate" in inj_impl.lower()
                       and ("implementer" in inj_impl.lower() or "reviewer" in inj_impl.lower())))
        # tworzenie skilla użytkownika z szablonu + odkrycie
        sm.create_skill("my-flow", template="workflow", name="My Flow")
        checks.append(("B6: created skill discovered",
                       any(s["id"] == "my-flow" and s["builtin"] is False for s in sm.list_skills())))
        checks.append(("B6: builtin skill not deletable", sm.delete_skill("commit") is False))
        checks.append(("B6: user skill deletable", sm.delete_skill("my-flow") is True
                       and all(s["id"] != "my-flow" for s in sm.list_skills())))
        bad = False
        try:
            sm.create_skill("../escape")
        except ValueError:
            bad = True
        checks.append(("B6: skill id traversal rejected", bad))

    # --- B5 §1.3: interop skilli (~/.claude/skills + <ws>/.claude|.grok/skills) ---
    def _mk_skill(folder: Path, name: str) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: d\ntriggers: []\n---\n\n# {name}\n\nBODY-{name}\n",
            encoding="utf-8")

    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        user_dir, claude_home, ws = d / "skills", d / "claude_home", d / "ws"
        _mk_skill(user_dir / "user-skill", "User Skill")
        _mk_skill(claude_home / "skills" / "cc-global", "CC Global")
        _mk_skill(ws / ".claude" / "skills" / "cc-proj", "CC Project")
        _mk_skill(ws / ".grok" / "skills" / "grok-proj", "Grok Project")
        # kolizje pierwszeństwa: builtin < user < claude-global < projekt
        _mk_skill(user_dir / "dup", "Dup User")
        _mk_skill(claude_home / "skills" / "dup", "Dup Global")        # > user
        _mk_skill(ws / ".claude" / "skills" / "dup", "Dup Project")    # > global
        _mk_skill(user_dir / "dup2", "Dup2 User")
        _mk_skill(claude_home / "skills" / "dup2", "Dup2 Global")      # > user (brak projektu)

        sm = SkillManager(user_dir, workspace_root=ws, claude_home=claude_home)
        by_id = {s["id"]: s for s in sm.list_skills()}
        checks.append(("B5: interop skills discovered from all sources",
                       {"user-skill", "cc-global", "cc-proj", "grok-proj"} <= set(by_id)))
        checks.append(("B5: source tags global/project/user",
                       by_id["cc-global"]["source"] == "claude-global"
                       and by_id["cc-proj"]["source"] == "claude-project"
                       and by_id["grok-proj"]["source"] == "grok-project"
                       and by_id["user-skill"]["source"] == "user"))
        checks.append(("B5: project overrides global+user on id collision",
                       by_id["dup"]["source"] == "claude-project"))
        checks.append(("B5: claude-global overrides user on id collision",
                       by_id["dup2"]["source"] == "claude-global"))

        sm.set_enabled("cc-global", True)
        inj = sm.injected_text()
        checks.append(("B5: enabled interop skill injected", "BODY-CC Global" in inj))
        checks.append(("B5: enabled-state written to SKILLS_DIR only (not interop dir)",
                       (user_dir / "_state.json").is_file()
                       and not (claude_home / "skills" / "_state.json").exists()))
        checks.append(("B5: interop skill not deletable (foreign dir)",
                       sm.delete_skill("cc-global") is False))
        checks.append(("B5: interop SKILL.md untouched after delete attempt",
                       (claude_home / "skills" / "cc-global" / "SKILL.md").is_file()))

        srcs = {s["source"] for s in SkillManager(user_dir).list_skills()}
        checks.append(("B5: no interop sources by default",
                       not ({"claude-global", "claude-project", "grok-project"} & srcs)))
