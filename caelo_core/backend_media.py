"""Media/generacja — mixin `Backend` (P2-13, wydzielone ze `state.py`).

`MediaMixin` skupia: egzekutory zadań generacji (`_gen_executor`/`_run_image_job`/
`_run_video_job` — używane przez `GenJobManager`), zapis mediów na dysk (`save_media_urls`/
`save_media_bytes`/`_download_media`, https-only + limit rozmiaru, P1-14) oraz rejestrację
artefaktów M9 (`_record_media_artifact`/`_media_kind`). Metody odwołują się do `self.api`/
`self.history`/`self.add_artifact`/`self.record_event` — rozwiązywane na `Backend` w runtime.

UWAGA (self-checki): `genjobs_check.py` i `api_smoke.py` podmieniają `requests` oraz
`VIDEO_POLL_INTERVAL_S` jako atrybuty TEGO modułu (mock sieci/pollingu) — patchują
`caelo_core.backend_media`, nie `state`.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

log = logging.getLogger(__name__)

try:
    import requests  # type: ignore
except Exception:  # pragma: no cover
    requests = None  # type: ignore

# P1-14: twardy limit pobieranych mediów (anty-OOM / miękki DoS przy spoofie URL).
MAX_MEDIA_BYTES = 256 * 1024 * 1024  # 256 MB (wideo bywa duże, ale nie nieograniczone)

# M11-B3: polling zadań wideo po stronie workera (sekundy). Deadline chroni przed
# zadaniem zaciętym w stanie nieterminalnym (analogicznie do POLL_DEADLINE w UI).
VIDEO_POLL_INTERVAL_S = 5
VIDEO_JOB_DEADLINE_S = 12 * 60


class MediaMixin:
    """Generacja + zapis mediów + artefakty M9. Mixin do `Backend`."""

    def _gen_executor(self, job, cancel) -> list:
        """Wykonaj zadanie generacji → lista artifact_id (M9). Rzuca przy błędzie."""
        if job.kind == "image":
            return self._run_image_job(job, cancel)
        if job.kind == "video":
            return self._run_video_job(job, cancel)
        raise ValueError(f"unknown gen job kind: {job.kind}")

    def _run_image_job(self, job, cancel) -> list:
        p = job.params
        prompt = p.get("prompt", "")
        n = int(p.get("n", 1) or 1)
        ratio = p.get("aspect_ratio", "auto")
        resolution = p.get("resolution", "1k")
        model = p.get("model") or None
        if job.op == "text2img":
            urls = self.api.generate_image(prompt, n, ratio, resolution, model=model)
            legacy_mode = "generate"
        else:  # edit / variation — oba przez /images/edits (referencja + prompt)
            images = list(p.get("images") or [])
            if not images:
                raise ValueError("edit/variation requires at least one reference image")
            urls = self.api.edit_image_b64(prompt, images, n, ratio, resolution, model=model)
            legacy_mode = "edit"
        results = self.save_media_urls(urls, prompt, legacy_mode, ".png",
                                       project_id=job.project_id,
                                       meta_extra={"gen_op": job.op, "model": model or ""})
        return [r["artifact_id"] for r in results if r.get("artifact_id")]

    def _run_video_job(self, job, cancel) -> list:
        from caelo_core.genjobs import GenJobCancelled

        p = job.params
        prompt = p.get("prompt", "")
        model = p.get("model") or None
        # Wybór wywołania xAI po operacji; dalej wspólna pętla pollingu.
        if job.op == "edit":
            request_id = self.api.edit_video_job(prompt, p["video"], model=model)
        elif job.op == "extend":
            request_id = self.api.extend_video_job(
                prompt, p["video"], duration=int(p.get("duration") or 0) or None, model=model)
        else:  # text2video / img2video
            request_id = self.api.create_video_job(
                prompt, int(p.get("duration", 6) or 6), p.get("resolution", "480p"),
                p.get("aspect_ratio", "Original"), None, model=model,
                image_data_uri=p.get("image"),
            )
        deadline = time.time() + VIDEO_JOB_DEADLINE_S
        while True:
            if cancel.is_set():
                raise GenJobCancelled()
            st = self.api.poll_video_status(request_id)
            status = (st or {}).get("status")
            if status == "done":
                url = (st.get("video") or {}).get("url")
                if not url:
                    raise RuntimeError("video job finished without a URL")
                results = self.save_media_urls([url], prompt, "video", ".mp4",
                                               project_id=job.project_id,
                                               meta_extra={"gen_op": job.op, "model": model or ""})
                return [r["artifact_id"] for r in results if r.get("artifact_id")]
            if status in ("failed", "expired"):
                raise RuntimeError(f"video job {status}")
            if time.time() > deadline:
                raise RuntimeError("video job timed out (still rendering)")
            # Czekaj, ale pozostań przerywalny: wait() wraca natychmiast po cancel.
            cancel.wait(VIDEO_POLL_INTERVAL_S)

    @staticmethod
    def _media_kind(legacy_mode: str, ext: str):
        """Zmapuj legacy tryb zapisu ('generate'/'edit'/'video'/'tts') + rozszerzenie
        na M9 (type, mode, mime). M9 mode ∈ {image, video, voice}."""
        e = (ext or "").lower().lstrip(".")
        audio_mime = {"mp3": "audio/mpeg", "wav": "audio/wav", "ogg": "audio/ogg",
                      "m4a": "audio/mp4"}
        image_mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                      "webp": "image/webp", "gif": "image/gif"}
        if legacy_mode == "tts" or e in audio_mime:
            return "audio", "voice", audio_mime.get(e, "audio/mpeg")
        if legacy_mode == "video" or e in ("mp4", "mov", "webm"):
            return "video", "video", "video/mp4"
        return "image", "image", image_mime.get(e, "image/png")

    def _record_media_artifact(self, *, legacy_mode: str, ext: str, prompt: str,
                               path, url, project_id=None, meta_extra=None):
        """M9-B2: zapisz wygenerowane medium jako artefakt + zdarzenie historii.
        Wołane z `save_media_urls`/`save_media_bytes` (poza gorącą pętlą; błędy połykane).
        `project_id` (M11): jawny scope (np. z `GenJob`) — None stempluje aktywnym.
        Zwraca utworzony Artifact (albo None przy błędzie magazynu)."""
        a_type, a_mode, mime = self._media_kind(legacy_mode, ext)
        meta = {"prompt": prompt or "", "op": legacy_mode}
        if url:
            meta["url"] = url
        if meta_extra:
            meta.update(meta_extra)
        art = self.add_artifact(type=a_type, mode=a_mode, mime=mime,
                                path=path or "", meta=meta, project_id=project_id)
        self.record_event(mode=a_mode, text=prompt or "",
                          artifact_id=(art.id if art else None), project_id=project_id)
        return art

    # --- zapis mediów (auto-save jak ResultCard/_auto_save_video) ---
    def save_media_urls(self, urls, prompt: str, mode: str, ext: str,
                        download: bool = True, project_id=None,
                        meta_extra=None) -> list:
        out = []
        save_dir = Path(self.history.get_save_path())
        try:
            save_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            log.warning("Could not create media save dir %s", save_dir, exc_info=True)
        for url in urls:
            path = None
            if download and requests is not None:
                try:
                    path = self._download_media(url, save_dir, mode, ext)
                except Exception:
                    log.warning("Failed to download/save media from %s", url, exc_info=True)
                    path = None
            try:
                self.history.save_to_history(mode, path or url, prompt)
            except Exception:
                log.warning("Failed to record media in history", exc_info=True)
            # M9-B2: artefakt + zdarzenie we wspólnej, przeszukiwalnej historii huba.
            # M11: zwracamy też artifact_id, by GenJob zarejestrował swoje wyjścia.
            art = self._record_media_artifact(legacy_mode=mode, ext=ext, prompt=prompt,
                                              path=path, url=url, project_id=project_id,
                                              meta_extra=meta_extra)
            out.append({"url": url, "path": path,
                        "artifact_id": (art.id if art else None)})
        return out

    def _download_media(self, url: str, save_dir: Path, mode: str, ext: str) -> str:
        """P1-14: pobranie mediów z xAI BEZPIECZNIE — tylko `https` (blokuje SSRF do
        http/file/itp.), strumieniowo na dysk z TWARDYM limitem rozmiaru (bez
        buforowania całości w pamięci). Zwraca ścieżkę pliku albo rzuca wyjątek."""
        if urlparse(url).scheme != "https":
            raise ValueError("refused non-https media URL")
        fn = f"studio_{mode}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}{ext}"
        target = save_dir / fn
        total = 0
        try:
            with requests.get(url, timeout=180, stream=True) as r:
                r.raise_for_status()
                cl = r.headers.get("Content-Length")
                if cl and cl.isdigit() and int(cl) > MAX_MEDIA_BYTES:
                    raise ValueError("media exceeds size cap")
                with open(target, "wb") as f:
                    for chunk in r.iter_content(65536):
                        if not chunk:
                            continue
                        total += len(chunk)
                        if total > MAX_MEDIA_BYTES:
                            raise ValueError("media exceeds size cap")
                        f.write(chunk)
            return str(target)
        except Exception:
            try:
                if target.exists():
                    target.unlink()  # usuń częściowy plik
            except OSError:
                pass
            raise

    def save_media_bytes(self, data: bytes, prompt: str, mode: str, ext: str) -> dict:
        """Zapis gotowych bajtów (np. audio z TTS) do folderu wyjściowego + historia."""
        save_dir = Path(self.history.get_save_path())
        path = None
        try:
            save_dir.mkdir(parents=True, exist_ok=True)
            fn = f"studio_{mode}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}{ext}"
            target = save_dir / fn
            target.write_bytes(data)
            path = str(target)
        except Exception:
            log.warning("Could not save media bytes to disk", exc_info=True)
            path = None
        try:
            self.history.save_to_history(mode, path or "", prompt)
        except Exception:
            log.warning("Failed to record media (bytes) in history", exc_info=True)
        # M9-B2: artefakt (np. audio TTS) + zdarzenie w historii huba.
        self._record_media_artifact(legacy_mode=mode, ext=ext, prompt=prompt,
                                    path=path, url=None)
        return {"path": path}
