"""Selfcheck silnika zadań generacji (M11-B1…B5) — in-process, bez sieci xAI.

Weryfikuje `caelo_core.genjobs.GenJobManager` na temp `HistoryStore` z atrapą
egzekutora ORAZ realny egzekutor `Backend._run_image_job/_run_video_job`
(z zamockowanym `api`/pobieraniem) — czyli „wyjścia → artefakty M9", anulowanie,
ponawianie, limit kolejki, koszt. Plus walidacja tras `/genjobs` (Pydantic).

Wzorzec jak pozostałe skrypty w `caelo_core/tools/`: lista (nazwa, ok), kod wyjścia
0 = wszystkie asercje przeszły. Nie dotyka realnych plików danych (temp) ani xAI.
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import types
from pathlib import Path

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PKG_DIR = os.path.dirname(THIS_DIR)
REPO_DIR = os.path.dirname(PKG_DIR)
sys.path.insert(0, REPO_DIR)


def _store(d: str):
    from caelo_core.history_store import HistoryStore
    return HistoryStore(Path(d) / "genjobs.db")


def _unit_lifecycle(checks: list) -> None:
    """Cykl życia: submit → done; wyjścia zarejestrowane jako artefakty M9; koszt."""
    from caelo_core.genjobs import GenJobManager, estimate_cost

    with tempfile.TemporaryDirectory() as d:
        store = _store(d)

        def exec_ok(job, cancel):
            art = store.add_artifact(type="image", mode="image", mime="image/png",
                                     path="", meta={"prompt": job.params.get("prompt")})
            return [art.id]

        mgr = GenJobManager(exec_ok, store=store, workers=2, max_active=8)
        try:
            job = mgr.submit(kind="image", op="text2img", params={"prompt": "a cat", "n": 2})
            checks.append(("genjobs: submit cost = estimate (B5)",
                           job.cost == estimate_cost("image", "text2img", {"n": 2})))
            final = mgr.wait(job.id, timeout=10)
            checks.append(("genjobs: lifecycle reaches done", final is not None and final.status == "done"))
            checks.append(("genjobs: outputs registered as artifacts (M9)",
                           bool(final.artifact_ids) and store.get_artifact(final.artifact_ids[0]) is not None))
            listed = mgr.list_jobs()
            checks.append(("genjobs: job persisted + listable", any(j.id == job.id for j in listed)))
            checks.append(("genjobs: get round-trips", mgr.get(job.id).status == "done"))
        finally:
            mgr.close()
            store.close()


def _unit_error(checks: list) -> None:
    """Błąd egzekutora → status failed z komunikatem (nie wywraca workera)."""
    from caelo_core.genjobs import GenJobManager

    with tempfile.TemporaryDirectory() as d:
        store = _store(d)

        def exec_fail(job, cancel):
            raise RuntimeError("boom xAI 500")

        mgr = GenJobManager(exec_fail, store=store, workers=1, max_active=8)
        try:
            j = mgr.submit(kind="image", op="text2img", params={"prompt": "x"})
            f = mgr.wait(j.id, timeout=10)
            checks.append(("genjobs: executor error -> failed + message",
                           f.status == "failed" and "boom" in f.error))

            # retry tworzy NOWE zadanie (te same params); done/running nie podlega retry
            again = mgr.retry(j.id)
            checks.append(("genjobs: retry creates a new job", again is not None and again.id != j.id))
            mgr.wait(again.id, timeout=10)
            no_retry = False
            done_store = store.get_gen_job(again.id)
            # po wykonaniu again też failed → retry znów dozwolony; sprawdźmy guard na done
            ok2 = store.add_artifact  # noop ref to keep linters calm
            try:
                # symuluj zadanie done i spróbuj retry → ValueError
                from caelo_core.genjobs import DONE
                store.upsert_gen_job(id="manual-done", kind="image", op="text2img",
                                     params={}, status=DONE, created_at=time.time(),
                                     updated_at=time.time())
                mgr.retry("manual-done")
            except ValueError:
                no_retry = True
            checks.append(("genjobs: retry rejected for non-failed/cancelled", no_retry and done_store is not None and bool(ok2)))
        finally:
            mgr.close()
            store.close()


def _unit_cancel(checks: list) -> None:
    """Anulowanie: running (egzekutor obserwuje event) i queued (przed startem)."""
    from caelo_core.genjobs import GenJobCancelled, GenJobManager

    # --- cancel RUNNING ---
    with tempfile.TemporaryDirectory() as d:
        store = _store(d)
        started = threading.Event()

        def exec_long(job, cancel):
            started.set()
            while not cancel.is_set():
                cancel.wait(0.05)
            raise GenJobCancelled()

        mgr = GenJobManager(exec_long, store=store, workers=1, max_active=8)
        try:
            j = mgr.submit(kind="video", op="text2video", params={"prompt": "x", "duration": 6})
            started.wait(5)
            mgr.cancel(j.id)
            c = mgr.wait(j.id, timeout=10)
            checks.append(("genjobs: cancel running -> cancelled", c.status == "cancelled"))
        finally:
            mgr.close()
            store.close()

    # --- cancel QUEUED (worker zajęty pierwszym zadaniem) ---
    with tempfile.TemporaryDirectory() as d:
        store = _store(d)
        first_started = threading.Event()
        release = threading.Event()
        ran_second: list = []

        def exec_blocky(job, cancel):
            if job.params.get("tag") == "first":
                first_started.set()
                release.wait(5)
                return []
            ran_second.append(job.id)
            return []

        mgr = GenJobManager(exec_blocky, store=store, workers=1, max_active=8)
        try:
            j1 = mgr.submit(kind="image", op="text2img", params={"prompt": "x", "tag": "first"})
            first_started.wait(5)
            j2 = mgr.submit(kind="image", op="text2img", params={"prompt": "y"})
            c2 = mgr.cancel(j2.id)  # j2 wciąż queued (worker trzyma j1)
            checks.append(("genjobs: cancel queued -> cancelled immediately", c2.status == "cancelled"))
            release.set()
            mgr.wait(j1.id, timeout=10)
            time.sleep(0.2)  # daj workerowi szansę pominąć anulowane j2
            checks.append(("genjobs: cancelled queued job never executes", j2.id not in ran_second))
        finally:
            mgr.close()
            store.close()


def _unit_queue_limit(checks: list) -> None:
    """B4: przekroczony limit aktywnych → GenJobQueueFull (czytelny komunikat)."""
    from caelo_core.genjobs import GenJobManager, GenJobQueueFull

    with tempfile.TemporaryDirectory() as d:
        store = _store(d)
        release = threading.Event()

        def exec_hold(job, cancel):
            release.wait(5)
            return []

        mgr = GenJobManager(exec_hold, store=store, workers=2, max_active=2)
        try:
            a = mgr.submit(kind="image", op="text2img", params={"prompt": "a"})
            b = mgr.submit(kind="image", op="text2img", params={"prompt": "b"})
            full = False
            try:
                mgr.submit(kind="image", op="text2img", params={"prompt": "c"})
            except GenJobQueueFull:
                full = True
            checks.append(("genjobs: queue limit enforced (B4)", full))
            release.set()
            mgr.wait(a.id, timeout=10)
            mgr.wait(b.id, timeout=10)
        finally:
            mgr.close()
            store.close()


def _unit_clear(checks: list) -> None:
    """Czyszczenie listy: clear_finished (po kind / wszystko) + remove pojedynczego;
    aktywne zadanie NIE jest usuwane. Artefaktów nie ruszamy (tu egzekutor ich nie tworzy)."""
    from caelo_core.genjobs import GenJobManager

    with tempfile.TemporaryDirectory() as d:
        store = _store(d)

        def exec_ok(job, cancel):
            return []

        mgr = GenJobManager(exec_ok, store=store, workers=2, max_active=16)
        try:
            ji = mgr.submit(kind="image", op="text2img", params={"prompt": "a"})
            mgr.wait(ji.id, timeout=10)
            jv = mgr.submit(kind="video", op="text2video", params={"prompt": "b", "duration": 6})
            mgr.wait(jv.id, timeout=10)

            n = mgr.clear_finished(kind="image")
            checks.append(("genjobs: clear_finished(kind=image) removes only image",
                           n == 1 and mgr.get(ji.id) is None and mgr.get(jv.id) is not None))

            n2 = mgr.clear_finished()
            checks.append(("genjobs: clear_finished() removes the rest",
                           n2 == 1 and mgr.get(jv.id) is None and mgr.list_jobs() == []))

            j2 = mgr.submit(kind="image", op="text2img", params={"prompt": "c"})
            mgr.wait(j2.id, timeout=10)
            checks.append(("genjobs: remove terminal job -> gone",
                           mgr.remove(j2.id) is True and mgr.get(j2.id) is None))
        finally:
            mgr.close()
            store.close()

    # remove aktywnego → odmowa (worker je trzyma)
    with tempfile.TemporaryDirectory() as d:
        store = _store(d)
        started = threading.Event()
        release = threading.Event()

        def exec_block(job, cancel):
            started.set()
            release.wait(5)
            return []

        mgr = GenJobManager(exec_block, store=store, workers=1, max_active=4)
        try:
            j = mgr.submit(kind="image", op="text2img", params={"prompt": "x"})
            started.wait(5)
            checks.append(("genjobs: remove active job refused",
                           mgr.remove(j.id) is False and mgr.get(j.id) is not None))
            release.set()
            mgr.wait(j.id, timeout=10)
        finally:
            mgr.close()
            store.close()


def _fake_download(monkeypatch_target):
    """Atrapa state.requests.get — strumieniuje stałe bajty na dysk (bez sieci)."""
    class _Resp:
        def __init__(self):
            self.headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def raise_for_status(self):
            pass

        def iter_content(self, n):
            yield b"FAKE-MEDIA-BYTES"

    return types.SimpleNamespace(get=lambda url, **kw: _Resp())


def _make_backend(store, save_dir: str):
    """Backend bez __init__ (bez I/O/sieci) z atrapami api/history pod egzekutor."""
    from caelo_core.state import Backend

    b = Backend.__new__(Backend)
    b._genjobs = None
    b.current_project_id = None

    class _FakeHistory:
        def get_save_path(self_inner):
            return save_dir

        def save_to_history(self_inner, *a, **k):
            pass

    b.history = _FakeHistory()
    return b


def _unit_backend_image_executor(checks: list) -> None:
    """Realny `Backend._run_image_job` — reużywa api + save_media_urls → artefakty M9.
    Mockujemy api (URL-e) i pobieranie (state.requests). Edit honoruje referencje."""
    import caelo_core.history_store as HS
    import caelo_core.state as state_mod
    from caelo_core.genjobs import GenJob

    with tempfile.TemporaryDirectory() as d:
        store = _store(d)
        prev_store = HS._default_store
        prev_requests = state_mod.requests
        HS._default_store = store
        state_mod.requests = _fake_download(state_mod)
        try:
            proj = store.add_project(name="Creative")
            b = _make_backend(store, d)
            b.current_project_id = proj.id

            captured = {}

            class _FakeApi:
                def generate_image(self_inner, prompt, n, ratio, resolution, model=None):
                    captured["gen"] = (prompt, n, ratio, resolution, model)
                    return [f"https://x/g{i}.png" for i in range(n)]

                def edit_image_b64(self_inner, prompt, images, n, ratio, resolution, model=None):
                    captured["edit"] = (prompt, list(images), n, ratio, resolution, model)
                    return ["https://x/e0.png"]

            b.api = _FakeApi()

            # text2img → 2 artefakty-obrazy, ostemplowane projektem
            job = GenJob(id="t1", kind="image", op="text2img",
                         params={"prompt": "a cat", "n": 2, "aspect_ratio": "1:1",
                                 "resolution": "1k", "model": "grok-imagine-image"},
                         project_id=proj.id, created_at=time.time(), updated_at=time.time())
            ids = b._run_image_job(job, threading.Event())
            arts = [store.get_artifact(i) for i in ids]
            checks.append(("genjobs/exec: text2img -> 2 image artifacts",
                           len(ids) == 2 and all(a and a.type == "image" for a in arts)))
            checks.append(("genjobs/exec: artifacts stamped with job project",
                           all(a.project_id == proj.id for a in arts)))
            checks.append(("genjobs/exec: file downloaded to save dir",
                           all(a.path and Path(a.path).is_file() for a in arts)))

            # edit → reużywa edit_image_b64 z referencjami (do 3)
            refs = ["data:image/png;base64,AAAA", "data:image/png;base64,BBBB",
                    "data:image/png;base64,CCCC"]
            ejob = GenJob(id="t2", kind="image", op="edit",
                          params={"prompt": "snowy", "n": 1, "images": refs,
                                  "aspect_ratio": "auto", "resolution": "1k"},
                          project_id=proj.id, created_at=time.time(), updated_at=time.time())
            eids = b._run_image_job(ejob, threading.Event())
            checks.append(("genjobs/exec: edit returns artifact + honors up to 3 refs",
                           len(eids) == 1 and len(captured["edit"][1]) == 3))
        except Exception as exc:  # noqa: BLE001
            checks.append((f"genjobs/exec: image scenario ran ({exc})", False))
        finally:
            HS._default_store = prev_store
            state_mod.requests = prev_requests
            store.close()


def _unit_backend_video_executor(checks: list) -> None:
    """Realny `Backend._run_video_job` — submit + poll do done → artefakt; cancel
    przerywa pętlę pollingu (GenJobCancelled)."""
    import caelo_core.history_store as HS
    import caelo_core.state as state_mod
    from caelo_core.genjobs import GenJob, GenJobCancelled

    with tempfile.TemporaryDirectory() as d:
        store = _store(d)
        prev_store = HS._default_store
        prev_requests = state_mod.requests
        prev_interval = state_mod.VIDEO_POLL_INTERVAL_S
        HS._default_store = store
        state_mod.requests = _fake_download(state_mod)
        state_mod.VIDEO_POLL_INTERVAL_S = 0  # bez czekania w teście
        try:
            b = _make_backend(store, d)

            polls = {"n": 0}

            class _DoneApi:
                def create_video_job(self_inner, *a, **k):
                    return "rid-123"

                def poll_video_status(self_inner, rid):
                    polls["n"] += 1
                    if polls["n"] < 2:
                        return {"status": "in_progress"}
                    return {"status": "done", "video": {"url": "https://x/clip.mp4"}}

            b.api = _DoneApi()
            vjob = GenJob(id="v1", kind="video", op="text2video",
                          params={"prompt": "drone", "duration": 6, "resolution": "480p"},
                          created_at=time.time(), updated_at=time.time())
            vids = b._run_video_job(vjob, threading.Event())
            art = store.get_artifact(vids[0]) if vids else None
            checks.append(("genjobs/exec: video poll-loop -> done artifact",
                           bool(vids) and art is not None and art.type == "video"
                           and polls["n"] >= 2))

            # edit/extend → dispatch na edit_video_job/extend_video_job (ten sam poll)
            called = {}

            class _EditApi:
                def edit_video_job(self_inner, prompt, video, model=None):
                    called["edit"] = (prompt, video)
                    return "rid-edit"

                def extend_video_job(self_inner, prompt, video, duration=None, model=None):
                    called["extend"] = (prompt, video, duration)
                    return "rid-ext"

                def poll_video_status(self_inner, rid):
                    return {"status": "done", "video": {"url": "https://x/clip2.mp4"}}

            b.api = _EditApi()
            ev = b._run_video_job(
                GenJob(id="v3", kind="video", op="edit",
                       params={"prompt": "restyle", "video": "https://x/src.mp4"},
                       created_at=time.time(), updated_at=time.time()), threading.Event())
            checks.append(("genjobs/exec: op=edit calls edit_video_job",
                           bool(ev) and called.get("edit") == ("restyle", "https://x/src.mp4")))
            xv = b._run_video_job(
                GenJob(id="v4", kind="video", op="extend",
                       params={"prompt": "more", "video": "https://x/src.mp4", "duration": 4},
                       created_at=time.time(), updated_at=time.time()), threading.Event())
            checks.append(("genjobs/exec: op=extend calls extend_video_job w/ duration",
                           bool(xv) and called.get("extend") == ("more", "https://x/src.mp4", 4)))

            # cancel: poll zawsze in_progress, event ustawiony → GenJobCancelled
            class _StuckApi:
                def create_video_job(self_inner, *a, **k):
                    return "rid-stuck"

                def poll_video_status(self_inner, rid):
                    return {"status": "in_progress"}

            b.api = _StuckApi()
            ev = threading.Event()
            ev.set()
            cancelled = False
            try:
                b._run_video_job(GenJob(id="v2", kind="video", op="text2video",
                                        params={"prompt": "x", "duration": 6},
                                        created_at=time.time(), updated_at=time.time()), ev)
            except GenJobCancelled:
                cancelled = True
            checks.append(("genjobs/exec: cancel breaks video poll loop", cancelled))
        except Exception as exc:  # noqa: BLE001
            checks.append((f"genjobs/exec: video scenario ran ({exc})", False))
        finally:
            HS._default_store = prev_store
            state_mod.requests = prev_requests
            state_mod.VIDEO_POLL_INTERVAL_S = prev_interval
            store.close()


def _unit_route_validation(checks: list) -> None:
    """Walidacja tras /genjobs (Pydantic): op vs referencje, limity, data-URI."""
    from pydantic import ValidationError
    from caelo_core.routes.genjobs import ImageJobReq, VideoJobReq

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
        ImageJobReq(prompt="a cat")  # text2img bez referencji
        ImageJobReq(op="edit", prompt="x",
                    images=["data:image/png;base64,AA", "data:image/png;base64,BB",
                            "data:image/png;base64,CC"])
        VideoJobReq(prompt="drone")  # text2video
        VideoJobReq(op="img2video", prompt="motion", image="data:image/png;base64,AA")
        VideoJobReq(op="edit", prompt="restyle", video="https://x/v.mp4")
        VideoJobReq(op="extend", prompt="more", video="https://x/v.mp4", duration=5)
    except Exception:
        ok = False
    checks.append(("genjobs/route: valid requests accepted", ok))
    checks.append(("genjobs/route: edit without video rejected",
                   rejects(lambda: VideoJobReq(op="edit", prompt="x"))))
    checks.append(("genjobs/route: edit with image rejected",
                   rejects(lambda: VideoJobReq(op="edit", prompt="x", video="https://x/v.mp4",
                                               image="data:image/png;base64,AA"))))
    checks.append(("genjobs/route: text2video with video rejected",
                   rejects(lambda: VideoJobReq(op="text2video", prompt="x", video="https://x/v.mp4"))))
    checks.append(("genjobs/route: extend duration > max rejected",
                   rejects(lambda: VideoJobReq(op="extend", prompt="x", video="https://x/v.mp4",
                                               duration=99))))
    checks.append(("genjobs/route: text2img with images rejected",
                   rejects(lambda: ImageJobReq(op="text2img", prompt="x",
                                               images=["data:image/png;base64,AA"]))))
    checks.append(("genjobs/route: edit without images rejected",
                   rejects(lambda: ImageJobReq(op="edit", prompt="x"))))
    checks.append(("genjobs/route: more than 3 refs rejected",
                   rejects(lambda: ImageJobReq(op="edit", prompt="x",
                                               images=["data:image/png;base64,AA"] * 4))))
    checks.append(("genjobs/route: non-data-URI ref rejected",
                   rejects(lambda: ImageJobReq(op="edit", prompt="x",
                                               images=["http://evil/x.png"]))))
    checks.append(("genjobs/route: img2video without image rejected",
                   rejects(lambda: VideoJobReq(op="img2video", prompt="x"))))
    checks.append(("genjobs/route: video duration out of range rejected",
                   rejects(lambda: VideoJobReq(prompt="x", duration=999))))


def main() -> int:
    import logging
    # Wycisz logger silnika: testy CELOWO wywołują błędy/anulowania (handled),
    # więc ich tracebacki nie powinny zaśmiecać wyniku selfchecka.
    logging.getLogger("caelo.genjobs").setLevel(logging.CRITICAL)

    checks: list = []
    _unit_lifecycle(checks)
    _unit_error(checks)
    _unit_cancel(checks)
    _unit_queue_limit(checks)
    _unit_clear(checks)
    _unit_backend_image_executor(checks)
    _unit_backend_video_executor(checks)
    _unit_route_validation(checks)

    ok = True
    for name, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    print("RESULT:", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
