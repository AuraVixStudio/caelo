"""api_smoke — grupa self-checków: smoke_routes (P3-13 split). Funkcje `_unit_*`/`_live_*(checks)` wołane przez `api_smoke.main()`."""
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


def _unit_fs_routes(checks: list) -> None:
    """P3-8: zachowanie tras /fs (write/read/tree) + sandbox — in-process, bez xAI
    i bez zaśmiecania realnych plików danych (route'y wołane wprost na temp workspace)."""
    import tempfile
    from pathlib import Path

    sys.path.insert(0, REPO_DIR)
    from fastapi import HTTPException  # noqa: E402
    from caelo_core.agent.workspace import Workspace  # noqa: E402
    from caelo_core.routes import fs as fs_route  # noqa: E402

    def rejects400(fn) -> bool:
        try:
            fn()
            return False
        except HTTPException as e:
            return e.status_code == 400

    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        r = fs_route.write(fs_route.WriteReq(path="sub/hello.txt", content="hi from test"), ws=ws)
        checks.append(("/fs/write ok + on disk",
                       r.get("ok") is True
                       and (Path(d) / "sub/hello.txt").read_text(encoding="utf-8") == "hi from test"))

        r = fs_route.read("sub/hello.txt", ws=ws)
        checks.append(("/fs/read round-trips content", r.get("content") == "hi from test"))

        r = fs_route.tree(".", ws=ws)
        names = [e["name"] for e in r["entries"]]
        checks.append(("/fs/tree lists workspace entry", "sub" in names))

        # sandbox: ucieczki poza workspace → 400 (nie wyciekają plików spoza root)
        checks.append(("/fs/read rejects '..' escape (400)",
                       rejects400(lambda: fs_route.read("../../etc/passwd", ws=ws))))
        checks.append(("/fs/write rejects '..' escape (400)",
                       rejects400(lambda: fs_route.write(fs_route.WriteReq(path="../escape.txt", content="x"), ws=ws))))
        checks.append(("/fs/tree rejects '..' escape (400)",
                       rejects400(lambda: fs_route.tree("../..", ws=ws))))


def _unit_git_routes(checks: list) -> None:
    """P3-8: zachowanie tras /git (status/commit + walidacja) — in-process."""
    import subprocess
    import tempfile
    from pathlib import Path

    sys.path.insert(0, REPO_DIR)
    from fastapi import HTTPException  # noqa: E402
    from caelo_core.agent.workspace import Workspace  # noqa: E402
    from caelo_core.routes import git as git_route  # noqa: E402

    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        r = git_route.status(ws=ws)
        checks.append(("/git/status non-repo -> is_repo false", r.get("is_repo") is False))

        ready = True
        try:
            for args in (["init"], ["config", "user.email", "t@t.test"], ["config", "user.name", "Tester"]):
                subprocess.run(["git", *args], cwd=d, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=15, check=True)
        except Exception:
            ready = False

        if not ready:
            checks.append(("git unavailable — repo tests skipped", True))
            return

        (Path(d) / "a.txt").write_text("hello\n", encoding="utf-8")
        r = git_route.status(ws=ws)
        checks.append(("/git/status repo -> is_repo true", r.get("is_repo") is True))

        r = git_route.commit(git_route.CommitReq(message="test commit", stage_all=True), ws=ws)
        checks.append(("/git/commit (stage_all) -> ok", r.get("ok") is True))

        def rejects400(fn) -> bool:
            try:
                fn()
                return False
            except HTTPException as e:
                return e.status_code == 400

        checks.append(("/git/commit empty message -> 400",
                       rejects400(lambda: git_route.commit(
                           git_route.CommitReq(message="   ", stage_all=False), ws=ws))))


def _unit_history_routes(checks: list) -> None:
    """M9-B3: trasy /history i /artifacts (lista + filtry FTS + paginacja) oraz
    /artifacts/{id} i /artifacts/{id}/content (strumień + walidacja ścieżki).
    In-process: magazyn podmieniony na temp (HS._default_store), Backend bez I/O
    (__new__), legacy history zatrapowane — bez sieci i bez realnych plików danych."""
    import tempfile
    from pathlib import Path

    sys.path.insert(0, REPO_DIR)
    from fastapi import HTTPException  # noqa: E402
    from fastapi.responses import FileResponse  # noqa: E402
    import caelo_core.history_store as HS  # noqa: E402
    from caelo_core.history_store import HistoryStore  # noqa: E402
    from caelo_core.routes import history as hist_route  # noqa: E402
    from caelo_core.state import Backend  # noqa: E402

    with tempfile.TemporaryDirectory() as d:
        store = HistoryStore(Path(d) / "h.db")
        prev = HS._default_store
        HS._default_store = store  # Backend.history_store → temp
        try:
            b = Backend.__new__(Backend)  # bez __init__ (bez I/O / sieci)

            class _FakeHistory:
                def get_save_path(self_) -> str:
                    return d  # dozwolony katalog treści = temp

            b.history = _FakeHistory()

            # seed: artefakt-obraz z plikiem na dysku + zdarzenia dwóch trybów
            pic = Path(d) / "pic.png"
            pic.write_bytes(b"\x89PNG\r\n\x1a\nfake-bytes")
            art = store.add_artifact(type="image", mode="image", mime="image/png",
                                     path=str(pic), meta={"prompt": "neon cyberpunk"})
            store.record_event(mode="image", text="neon cyberpunk skyline", artifact_id=art.id)
            store.record_event(mode="chat", text="hello about dragons")

            def H(**kw):
                p = dict(q=None, mode=None, project_id=None, from_=None, to=None,
                         limit=50, offset=0)
                p.update(kw)
                return hist_route.list_history(b=b, **p)

            def A(**kw):
                p = dict(mode=None, project_id=None, from_=None, to=None,
                         limit=50, offset=0)
                p.update(kw)
                return hist_route.list_artifacts(b=b, **p)

            r = H()
            checks.append(("/history lists all events", len(r["events"]) == 2))
            r = H(q="cyberpunk")
            checks.append(("/history q (FTS) filters + ranks",
                           len(r["events"]) == 1 and r["events"][0]["mode"] == "image"))
            r = H(mode="chat")
            checks.append(("/history mode filter",
                           len(r["events"]) == 1 and r["events"][0]["mode"] == "chat"))
            r = H(limit=1)
            checks.append(("/history paginates (limit)", len(r["events"]) == 1 and r["limit"] == 1))

            # M19-B10: eksport historii do Markdown (tekst + prompt/model z meta)
            store.record_event(mode="code", text="Refactored the parser.",
                               meta={"prompt": "refactor the parser", "model": "grok-build"})

            def X(**kw):
                p = dict(q=None, mode=None, project_id=None, from_=None, to=None,
                         limit=200, offset=0)
                p.update(kw)
                return hist_route.export_history(b=b, **p)

            resp = X()
            body = resp.body.decode("utf-8")
            checks.append(("/history/export -> text/markdown",
                           "text/markdown" in (resp.media_type or "")))
            checks.append(("/history/export includes recorded text (response)",
                           "hello about dragons" in body and "Refactored the parser." in body))
            checks.append(("/history/export includes prompt + model from meta",
                           "refactor the parser" in body and "grok-build" in body))
            body_code = X(mode="code").body.decode("utf-8")
            checks.append(("/history/export honors mode filter",
                           "Refactored the parser." in body_code
                           and "hello about dragons" not in body_code))

            r = A()
            checks.append(("/artifacts lists artifacts", len(r["artifacts"]) == 1))
            r = A(mode="video")
            checks.append(("/artifacts mode filter narrows", r["artifacts"] == []))

            meta = hist_route.get_artifact(art.id, b=b)
            checks.append(("/artifacts/{id} metadata",
                           meta["id"] == art.id and meta["mime"] == "image/png"))

            missing404 = False
            try:
                hist_route.get_artifact("does-not-exist", b=b)
            except HTTPException as e:
                missing404 = e.status_code == 404
            checks.append(("/artifacts/{id} missing -> 404", missing404))

            resp = hist_route.get_artifact_content(art.id, b=b)
            checks.append(("/artifacts/{id}/content -> FileResponse (inline)",
                           isinstance(resp, FileResponse)
                           and Path(resp.path).name == "pic.png"
                           and resp.media_type == "image/png"))

            # M9-B4: send-to bus — obraz → blok vision (image_url, base64 z dysku)
            ib = hist_route.artifact_input_block(art.id, b=b)
            checks.append(("/artifacts/{id}/input-block (image) -> vision block",
                           ib["block"]["type"] == "image_url"
                           and ib["block"]["image_url"]["url"].startswith("data:image/png;base64,")))
            ib_missing404 = False
            try:
                hist_route.artifact_input_block("does-not-exist", b=b)
            except HTTPException as e:
                ib_missing404 = e.status_code == 404
            checks.append(("/artifacts/{id}/input-block missing -> 404", ib_missing404))

            # anty-traversal: artefakt wskazujący POZA dozwolone katalogi → 403
            outside = Path(d).resolve().parent / "grok_b3_outside_marker.bin"
            evil = store.add_artifact(type="file", mode="file", path=str(outside))
            denied = False
            try:
                hist_route.get_artifact_content(evil.id, b=b)
            except HTTPException as e:
                denied = e.status_code == 403
            checks.append(("/artifacts/{id}/content outside allowed dirs -> 403", denied))

            # M11 follow-up: DELETE /artifacts/{id} kasuje rekord + plik (sandbox)
            pic2 = Path(d) / "del.png"
            pic2.write_bytes(b"\x89PNG\r\n\x1a\nx")
            delart = store.add_artifact(type="image", mode="image", mime="image/png", path=str(pic2))
            r = hist_route.delete_artifact(delart.id, b=b)
            checks.append(("/artifacts/{id} DELETE removes record + file",
                           r["ok"] is True and r["deleted_file"] is True
                           and not pic2.exists() and store.get_artifact(delart.id) is None))
            del404 = False
            try:
                hist_route.delete_artifact("does-not-exist", b=b)
            except HTTPException as e:
                del404 = e.status_code == 404
            checks.append(("/artifacts/{id} DELETE unknown -> 404", del404))

            # DELETE artefaktu spoza dozwolonych katalogów: rekord znika, pliku NIE ruszamy
            ext_marker = Path(d).resolve().parent / "grok_del_outside_marker.bin"
            ext_marker.write_bytes(b"keep")
            try:
                evil2 = store.add_artifact(type="file", mode="file", path=str(ext_marker))
                r2 = hist_route.delete_artifact(evil2.id, b=b)
                checks.append(("/artifacts/{id} DELETE outside dir: record gone, file kept",
                               r2["deleted_file"] is False and ext_marker.exists()
                               and store.get_artifact(evil2.id) is None))
            finally:
                if ext_marker.exists():
                    ext_marker.unlink()
        except Exception as exc:  # noqa: BLE001
            checks.append((f"history routes: scenario ran ({exc})", False))
        finally:
            HS._default_store = prev
            store.close()


def _unit_projects_routes(checks: list) -> None:
    """M9-B5: trasy /projects (list/create/select) + stemplowanie aktywnym projektem.
    In-process: magazyn → temp (HS._default_store), SETTINGS_FILE → temp (current_project
    i recent_workspaces nie dotykają realnego caelo_settings.json), Backend bez I/O."""
    import tempfile
    from pathlib import Path

    sys.path.insert(0, REPO_DIR)
    import config  # type: ignore  # noqa: E402
    from fastapi import HTTPException  # noqa: E402
    import caelo_core.history_store as HS  # noqa: E402
    from caelo_core.history_store import HistoryStore  # noqa: E402
    from caelo_core.routes import projects as proj_route  # noqa: E402
    from caelo_core.state import Backend  # noqa: E402

    with tempfile.TemporaryDirectory() as d:
        store = HistoryStore(Path(d) / "h.db")
        prev_store = HS._default_store
        prev_settings = config.SETTINGS_FILE
        HS._default_store = store
        config.SETTINGS_FILE = Path(d) / "caelo_settings.json"
        try:
            b = Backend.__new__(Backend)  # bez __init__; current_project_id = class default None

            r = proj_route.list_projects(b=b)
            checks.append(("/projects empty list + shape",
                           r["projects"] == [] and "current_project_id" in r
                           and "recent_workspaces" in r))

            r = proj_route.create_project(proj_route.CreateProjectReq(name="Alpha"), b=b)
            pid = r["project"]["id"]
            checks.append(("/projects create selects it as current", r["current_project_id"] == pid))

            # aktywny projekt stempluje zapisywane zdarzenia
            b.record_event(mode="chat", text="scoped alpha note")
            checks.append(("/projects active stamps recorded events",
                           len(store.list_events(project_id=pid)) == 1))

            r = proj_route.list_projects(b=b)
            checks.append(("/projects lists created project",
                           [p["id"] for p in r["projects"]] == [pid] and r["current_project_id"] == pid))

            r = proj_route.select_project(proj_route.SelectProjectReq(project_id=None), b=b)
            checks.append(("/projects/current null clears active",
                           b.current_project_id is None and r["project"] is None))

            unknown404 = False
            try:
                proj_route.select_project(proj_route.SelectProjectReq(project_id="does-not-exist"), b=b)
            except HTTPException as e:
                unknown404 = e.status_code == 404
            checks.append(("/projects/current unknown id -> 404", unknown404))

            # select istniejący ponownie ustawia aktywny
            proj_route.select_project(proj_route.SelectProjectReq(project_id=pid), b=b)
            checks.append(("/projects/current re-selects existing", b.current_project_id == pid))
        except Exception as exc:  # noqa: BLE001
            checks.append((f"projects routes: scenario ran ({exc})", False))
        finally:
            HS._default_store = prev_store
            config.SETTINGS_FILE = prev_settings
            store.close()


def _unit_agent_routes(checks: list) -> None:
    """M13-B5: trasy /agent/checkpoints, /agent/undo, /agent/caelo-md — in-process,
    bez sieci. Backend bez __init__ (tylko workspace + checkpointy na temp)."""
    import tempfile
    from pathlib import Path

    sys.path.insert(0, REPO_DIR)
    from fastapi import HTTPException  # noqa: E402
    from caelo_core.agent.workspace import Workspace  # noqa: E402
    from caelo_core.routes import agent_api as ar  # noqa: E402
    from caelo_core.state import Backend  # noqa: E402

    with tempfile.TemporaryDirectory() as d:
        b = Backend.__new__(Backend)  # bez __init__ (bez I/O / sieci)
        b._workspace = None
        b._checkpoints = None

        r = ar.list_checkpoints(b=b)
        checks.append(("/agent/checkpoints no workspace -> empty",
                       r["has_workspace"] is False and r["checkpoints"] == []))

        undo_400 = False
        try:
            ar.undo(ar.UndoReq(), b=b)
        except HTTPException as e:
            undo_400 = e.status_code == 400
        checks.append(("/agent/undo no workspace -> 400", undo_400))

        ws = Workspace(d)
        b._workspace = ws
        (ws.root / "a.txt").write_text("orig\n", encoding="utf-8")

        cp = b.get_checkpoints()
        cp.begin_turn(label="edit a")
        cp.snapshot("a.txt")
        (ws.root / "a.txt").write_text("changed\n", encoding="utf-8")
        cp.snapshot("new.txt")
        (ws.root / "new.txt").write_text("new\n", encoding="utf-8")

        r = ar.list_checkpoints(b=b)
        checks.append(("/agent/checkpoints lists session checkpoint",
                       r["has_workspace"] is True and len(r["checkpoints"]) == 1
                       and r["checkpoints"][0]["files"] == 2))

        r = ar.undo(ar.UndoReq(), b=b)
        checks.append(("/agent/undo restores + deletes",
                       (ws.root / "a.txt").read_text(encoding="utf-8") == "orig\n"
                       and not (ws.root / "new.txt").exists()
                       and "a.txt" in r["restored"] and "new.txt" in r["deleted"]))

        # nieznany checkpoint -> 404
        cp.begin_turn()
        cp.snapshot("a.txt")
        (ws.root / "a.txt").write_text("x\n", encoding="utf-8")
        unknown404 = False
        try:
            ar.undo(ar.UndoReq(checkpoint_id="does-not-exist"), b=b)
        except HTTPException as e:
            unknown404 = e.status_code == 404
        checks.append(("/agent/undo unknown checkpoint -> 404", unknown404))

        # CAELO.md round-trip (atomowy zapis pod workspace, sandbox)
        gm = ar.get_caelo_md(b=b)
        checks.append(("/agent/caelo-md initial empty",
                       gm["exists"] is False and gm["content"] == ""))
        ar.put_caelo_md(ar.CaeloMdReq(content="never touch /vendor"), ws=ws)
        gm2 = ar.get_caelo_md(b=b)
        checks.append(("/agent/caelo-md round-trips",
                       gm2["exists"] is True and "never touch /vendor" in gm2["content"]))


def _unit_permissions_routes(checks: list) -> None:
    """M19-B4: trasy /permissions/rules (GET/PUT) — walidacja + persystencja do ustawień
    + przebudowa bramki. In-process: Backend bez __init__, read/write_settings na pamięci
    (bez I/O), reload_permission_rules() prawdziwy (workspace None → tylko globalne)."""
    sys.path.insert(0, REPO_DIR)
    from fastapi import HTTPException  # noqa: E402
    from caelo_core.agent.permissions import PermissionGate  # noqa: E402
    from caelo_core.routes import permissions as pr  # noqa: E402
    from caelo_core.state import Backend  # noqa: E402

    b = Backend.__new__(Backend)  # bez __init__ (bez I/O / sieci)
    b._workspace = None
    b.permissions = PermissionGate(None)
    store: dict = {}
    b.read_settings = lambda: dict(store)             # type: ignore[assignment]
    b.write_settings = lambda data: store.update(data)  # type: ignore[assignment]

    r = pr.get_glob_rules(b=b)
    checks.append(("/permissions/rules initially empty", r == {"allow": [], "deny": []}))

    r = pr.put_glob_rules(pr.RulesBody(allow=["Bash(npm*)"], deny=["Edit(secret/**)"]), b=b)
    checks.append(("/permissions/rules PUT stores + rebuilds gate",
                   "Bash(npm*)" in r["allow"] and "Edit(secret/**)" in r["deny"]
                   and b.permissions.evaluate_rules("edit_file", {"path": "secret/k"}) == "deny"
                   and store.get("permission_rules", {}).get("allow") == ["Bash(npm*)"]))

    bad400 = False
    try:
        pr.put_glob_rules(pr.RulesBody(allow=["Nope(x)"]), b=b)
    except HTTPException as e:
        bad400 = e.status_code == 400
    checks.append(("/permissions/rules invalid -> 400 (fail-closed)", bad400))
    checks.append(("/permissions/rules 400 leaves prior rules intact",
                   "Bash(npm*)" in pr.get_glob_rules(b=b)["allow"]))


def _unit_lsp_routes(checks: list) -> None:
    """M19-B3: trasy /lsp (lista/dodaj/usuń) — in-process, globalny lsp.json w temp
    DATA_DIR (bez I/O realnych danych, bez startu serwerów języka)."""
    import tempfile
    from pathlib import Path

    sys.path.insert(0, REPO_DIR)
    import config  # type: ignore  # noqa: E402
    from fastapi import HTTPException  # noqa: E402
    from caelo_core.routes import lsp as lr  # noqa: E402
    from caelo_core.state import Backend  # noqa: E402

    with tempfile.TemporaryDirectory() as d:
        orig = config.DATA_DIR
        config.DATA_DIR = Path(d)  # globalny lsp.json czytany/pisany tu
        try:
            b = Backend.__new__(Backend)  # bez __init__ (bez I/O / sieci)
            b._workspace = None
            b._lsp = None

            r = lr.list_servers(b=b)
            checks.append(("/lsp initially empty", r["servers"] == [] and r["has_workspace"] is False))

            lr.add_server(lr.LspServerBody(name="pyright", command="pyright-langserver",
                          args=["--stdio"], extensionToLanguage={".py": "python"}), b=b)
            r = lr.list_servers(b=b)
            checks.append(("/lsp add persists server",
                           any(s["name"] == "pyright" and "python" in s["languages"]
                               for s in r["servers"])))

            lr.remove_server("pyright", b=b)
            checks.append(("/lsp delete removes server",
                           not any(s["name"] == "pyright" for s in lr.list_servers(b=b)["servers"])))

            bad = False
            try:
                lr.add_server(lr.LspServerBody(name="x", command="",
                              extensionToLanguage={".x": "y"}), b=b)
            except HTTPException as e:
                bad = e.status_code == 400
            checks.append(("/lsp add invalid (no command) -> 400", bad))
        finally:
            config.DATA_DIR = orig


def _unit_mcp_routes(checks: list) -> None:
    """M14-B1/F1: trasy /mcp — add/list/enable/start/stop/remove in-process. Remote
    bez podprocesu (maskowanie sekretu); stdio startuje mock-serwer (pełna ścieżka
    route→manager→client). Backend bez __init__ (manager na temp configu)."""
    import tempfile
    from pathlib import Path

    sys.path.insert(0, REPO_DIR)
    from fastapi import HTTPException  # noqa: E402
    from caelo_core.mcp.manager import McpManager  # noqa: E402
    from caelo_core.routes import mcp as mr  # noqa: E402
    from caelo_core.state import Backend  # noqa: E402

    mock = os.path.join(PKG_DIR, "tools", "_mcp_mock_server.py")
    with tempfile.TemporaryDirectory() as d:
        b = Backend.__new__(Backend)
        b._mcp = McpManager(Path(d) / "caelo_mcp.json")
        try:
            mr.add_server(mr.McpServerReq(id="rmt", name="Remote", transport="remote",
                                          url="https://ex.com/mcp", authorization="Bearer S"), b=b)
            lst = mr.list_servers(b=b)["servers"]
            rmt = next((s for s in lst if s["id"] == "rmt"), {})
            checks.append(("/mcp add remote + masks secret",
                           rmt.get("has_authorization") is True and "authorization" not in rmt))

            mr.set_enabled("rmt", mr.EnabledReq(enabled=False), b=b)
            checks.append(("/mcp set enabled toggles",
                           mr.server_status("rmt", b=b)["server"]["enabled"] is False))

            mr.add_server(mr.McpServerReq(id="mock", name="Mock", transport="stdio",
                                          command=[sys.executable, mock]), b=b)
            st = mr.start_server("mock", b=b)["server"]
            checks.append(("/mcp start stdio -> ready + tools",
                           st["status"] == "ready" and st["tool_count"] == 2))
            mr.stop_server("mock", b=b)

            mr.remove_server("rmt", b=b)
            gone404 = False
            try:
                mr.server_status("rmt", b=b)
            except HTTPException as e:
                gone404 = e.status_code == 404
            checks.append(("/mcp remove + 404 after", gone404))

            bad400 = False
            try:
                mr.add_server(mr.McpServerReq(id="x", transport="stdio", command=[]), b=b)
            except HTTPException as e:
                bad400 = e.status_code == 400
            checks.append(("/mcp add stdio without command -> 400", bad400))
        except Exception as exc:  # noqa: BLE001
            checks.append((f"mcp routes: scenario ran ({exc})", False))
        finally:
            b._mcp.shutdown()


def _unit_team_routes(checks: list) -> None:
    """M17 (F2/F4/F5): trasy /agent/team — role/limity, scalenia (apply/reject/diff,
    konflikt), przebiegi. Backend bez __init__ (rejestr + magazyn na temp)."""
    import tempfile
    from pathlib import Path

    sys.path.insert(0, REPO_DIR)
    from fastapi import HTTPException  # noqa: E402
    from caelo_core.agent.roles import RoleRegistry  # noqa: E402
    from caelo_core.agent.workspace import Workspace  # noqa: E402
    from caelo_core.agent import worktree as WT  # noqa: E402
    from caelo_core.routes import team as tr  # noqa: E402
    from caelo_core.state import Backend  # noqa: E402

    with tempfile.TemporaryDirectory() as d:
        b = Backend.__new__(Backend)
        b._workspace = None
        b._checkpoints = None
        b._team_merges = None
        b._team_reports = []
        b._subagents = RoleRegistry(Path(d) / "subagents.json")

        # role: wbudowane widoczne + limity
        roles = tr.list_roles(b=b)
        ids = {r["id"] for r in roles["roles"]}
        checks.append(("/team/roles lists builtin roles",
                       {"researcher", "reviewer", "implementer", "tester"} <= ids
                       and roles["limits"]["max_depth"] == 1))

        # upsert custom role + remove
        tr.upsert_role(tr.RoleReq(id="docs", label="Docs", tools=["read_file"],
                                  mcp="readonly"), b=b)
        checks.append(("/team/roles upsert adds role",
                       any(r["id"] == "docs" for r in tr.list_roles(b=b)["roles"])))
        tr.remove_role("docs", b=b)
        checks.append(("/team/roles remove deletes role",
                       all(r["id"] != "docs" for r in tr.list_roles(b=b)["roles"])))

        # M19-B9/B11: effort + persona + kontrakt I/O round-trip przez trasę (RoleReq
        # musi je przepuścić — inaczej UI by ich nie zapisał).
        tr.upsert_role(tr.RoleReq(
            id="io-role", label="IO", tools=["read_file"], mcp="readonly",
            reasoning_effort="high", instructions="Be precise.",
            inputs=[{"name": "spec", "io_type": "file", "required": True, "description": "the spec"}],
            outputs=[{"name": "report", "required": True, "description": "the report"}],
        ), b=b)
        got = next((r for r in tr.list_roles(b=b)["roles"] if r["id"] == "io-role"), None)
        checks.append(("/team/roles round-trips effort + persona + I/O (B9/B11)",
                       got is not None and got["reasoning_effort"] == "high"
                       and got["instructions"] == "Be precise."
                       and got["inputs"][0]["name"] == "spec"
                       and got["outputs"][0]["name"] == "report"
                       and got["outputs"][0]["required"] is True))
        tr.remove_role("io-role", b=b)

        # limity walidowane (clamp)
        lim = tr.set_limits(tr.LimitsReq(max_parallel=99, max_total_turns=5), b=b)["limits"]
        checks.append(("/team/limits clamps + persists",
                       lim["max_parallel"] == 8 and lim["max_total_turns"] == 5))

        # merges bez workspace → puste
        m0 = tr.list_merges(b=b)
        checks.append(("/team/merges no workspace -> empty",
                       m0["has_workspace"] is False and m0["merges"] == []))

        # workspace + syntetyczne scalenie (worktree z nowym plikiem)
        ws = Workspace(d)
        b._workspace = ws
        (ws.root / "orig.txt").write_text("orig\n", encoding="utf-8")
        store = b.get_team_merges()
        wt = Path(tempfile.mkdtemp()) / "wt"
        WT.copy_worktree(ws.root, wt)
        (wt / "added.txt").write_text("added\n", encoding="utf-8")
        ch = WT.compute_changes(ws.root, wt)
        pm = store.add(agent_id="sa1", role="implementer", task="t",
                       worktree_dir=str(wt), files=ch["files"], diff=ch["diff"], created_at=0)

        listed = tr.list_merges(b=b)
        checks.append(("/team/merges lists pending merge",
                       listed["has_workspace"] is True and len(listed["merges"]) == 1))
        dr = tr.merge_diff(pm.id, b=b)
        checks.append(("/team/merges diff returns unified diff", "+added" in dr["diff"]))

        # apply → plik w workspace, worktree wyrzucony
        res = tr.apply_merge(pm.id, b=b)
        checks.append(("/team/merges apply writes file + clears",
                       (ws.root / "added.txt").exists() and not wt.exists()
                       and tr.list_merges(b=b)["merges"] == []))

        # nieznane scalenie → 404
        nf = False
        try:
            tr.merge_diff("nope", b=b)
        except HTTPException as e:
            nf = e.status_code == 404
        checks.append(("/team/merges unknown -> 404", nf))

        # runs (telemetria) — początkowo puste, po record_team_report widoczne
        checks.append(("/team/runs empty initially", tr.list_runs(b=b)["runs"] == []))
        b.record_team_report({"run": 1, "totals": {"subagents": 2}})
        checks.append(("/team/runs reports recorded run",
                       tr.list_runs(b=b)["runs"][0]["totals"]["subagents"] == 2))
