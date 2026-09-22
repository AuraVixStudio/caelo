"""Media/generacja — mixin `Backend` (P2-13, wydzielone ze `state.py`).

`MediaMixin` skupia: egzekutory zadań generacji (`_gen_executor`/`_run_image_job`/
`_run_video_job` — używane przez `GenJobManager`), zapis mediów na dysk (`save_media_urls`/
`save_media_bytes`/`_download_media`, https-only + limit rozmiaru, P1-14) oraz rejestrację
artefaktów M9 (`_record_media_artifact`/`_media_kind`). Wywołania modeli przechodzą
przez `self.get_provider`; zapis odwołuje się do `self.history`/`self.add_artifact`/
`self.record_event` — rozwiązywane na `Backend` w runtime.

UWAGA (self-checki): `genjobs_check.py` i `api_smoke.py` podmieniają `requests` oraz
`VIDEO_POLL_INTERVAL_S` jako atrybuty TEGO modułu (mock sieci/pollingu) — patchują
`caelo_core.backend_media`, nie `state`.
"""

from __future__ import annotations

import logging
import time
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

    def _run_image_job(self, job, cancel, *, strict_save: bool = False) -> list:
        # S31-a: obraz honoruje cancel_event (best-effort — pojedynczego blokującego POST
        # nie da się przerwać w locie, ale anulowanie PRZED/PO daje status cancelled, nie done).
        from caelo_core.genjobs import GenJobCancelled

        p = job.params
        prompt = p.get("prompt", "")
        n = int(p.get("n", 1) or 1)
        ratio = p.get("aspect_ratio", "auto")
        resolution = p.get("resolution", "1k")
        model = p.get("model") or None
        # `quality` (low|medium|auto) dotyczy tylko grok-imagine-image-2.0 — filtr jest
        # w `api_manager._apply_quality`, tu tylko podajemy dalej.
        quality = p.get("quality") or None
        if cancel.is_set():
            raise GenJobCancelled()
        from caelo_core.providers import ImageGenerationRequest

        provider_id = p.get("provider") or "xai"
        images = tuple(p.get("images") or ())
        if job.op != "text2img" and not images:
            raise ValueError("edit/variation requires at least one reference image")
        provider = self.get_provider(provider_id)
        generated = provider.generate_image(
            ImageGenerationRequest(
                prompt=prompt,
                operation=job.op,
                model=model,
                count=n,
                aspect_ratio=ratio,
                resolution=resolution,
                images=images,
                quality=quality,
                reference_roles=tuple(p.get("reference_roles") or ()),
                thinking_level=p.get("thinking_level") or None,
                search_grounding=bool(p.get("search_grounding", False)),
                mime_type=p.get("mime_type") or "image/png",
                output_format=p.get("output_format") or None,
                output_compression=p.get("output_compression"),
                background=p.get("background") or None,
                moderation=p.get("moderation") or None,
            )
        )
        # Lekki usage/request-id jest potrzebny warstwie aplikacyjnej do zamiany
        # kosztu szacowanego na faktycznie naliczony przez dostawce.
        job.remote_metadata = dict(generated.metadata or {})
        legacy_mode = "generate" if job.op == "text2img" else "edit"
        if cancel.is_set():
            raise GenJobCancelled()
        results = self.save_provider_outputs(
            generated.outputs,
            prompt,
            legacy_mode,
            ".png",
            project_id=job.project_id,
            meta_extra={
                "gen_op": job.op,
                "model": model or "",
                "provider": provider_id,
                # Zapisujemy ŻĄDANĄ rozdzielczość — bez niej nie da się później
                # sprawdzić, czy dostawca ją uszanował (patrz „thought" w Nano Banana).
                "resolution": resolution,
                "aspect_ratio": ratio,
                "provider_usage": generated.metadata.get("usage")
                if isinstance(generated.metadata, dict) else None,
            },
            strict=strict_save,
        )
        return [r["artifact_id"] for r in results if r.get("artifact_id")]

    def _run_video_job(self, job, cancel) -> list:
        from caelo_core.genjobs import GenJobCancelled

        p = job.params
        prompt = p.get("prompt", "")
        model = p.get("model") or None
        from caelo_core.providers import VideoGenerationRequest

        provider_id = p.get("provider") or "xai"
        provider = self.get_provider(provider_id)
        submission = provider.submit_video(
            VideoGenerationRequest(
                prompt=prompt,
                operation=job.op,
                model=model,
                duration=int(p.get("duration", 6) or 6),
                resolution=p.get("resolution", "480p"),
                aspect_ratio=p.get("aspect_ratio", "Original"),
                image=p.get("image"),
                last_image=p.get("last_image"),
                video=p.get("video"),
                reference_images=tuple(p.get("reference_images") or ()),
                reference_roles=tuple(p.get("reference_roles") or ()),
                generate_audio=bool(p.get("generate_audio", True)),
                seed=p.get("seed"),
                negative_prompt=p.get("negative_prompt") or None,
                previous_interaction_id=p.get("previous_interaction_id") or None,
            )
        )
        deadline = time.time() + VIDEO_JOB_DEADLINE_S
        while True:
            if cancel.is_set():
                raise GenJobCancelled()
            status = provider.poll_video(submission)
            if status.state == "succeeded":
                if status.output is None:
                    raise RuntimeError("video job finished without output")
                results = self.save_provider_outputs(
                    [status.output],
                    prompt,
                    "video",
                    ".mp4",
                    project_id=job.project_id,
                    meta_extra={
                        "gen_op": job.op,
                        "model": model or "",
                        "provider": provider_id,
                    },
                )
                return [r["artifact_id"] for r in results if r.get("artifact_id")]
            if status.state in ("failed", "expired"):
                raise RuntimeError(status.error_message or f"video job {status.state}")
            if time.time() > deadline:
                raise RuntimeError("video job timed out (still rendering)")
            # Czekaj, ale pozostań przerywalny: wait() wraca natychmiast po cancel.
            cancel.wait(VIDEO_POLL_INTERVAL_S)

    @staticmethod
    def _media_kind(legacy_mode: str, ext: str):
        """Zmapuj legacy tryb zapisu ('generate'/'edit'/'video'/'tts') + rozszerzenie
        na M9 (type, mode, mime). M9 mode ∈ {image, video, voice}."""
        e = (ext or "").lower().lstrip(".")
        audio_mime = {
            "mp3": "audio/mpeg",
            "wav": "audio/wav",
            "ogg": "audio/ogg",
            "m4a": "audio/mp4",
        }
        image_mime = {
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "webp": "image/webp",
            "gif": "image/gif",
        }
        if legacy_mode == "tts" or e in audio_mime:
            return "audio", "voice", audio_mime.get(e, "audio/mpeg")
        if legacy_mode == "video" or e in ("mp4", "mov", "webm"):
            return "video", "video", "video/mp4"
        return "image", "image", image_mime.get(e, "image/png")

    def _record_media_artifact(
        self,
        *,
        legacy_mode: str,
        ext: str,
        prompt: str,
        path,
        url,
        project_id=None,
        meta_extra=None,
    ):
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
        art = self.add_artifact(
            type=a_type,
            mode=a_mode,
            mime=mime,
            path=path or "",
            # Galeria wyświetla oryginał przez strumieniowany protokół `caelo-media`.
            # Nie duplikujemy każdego wyniku jako pliku miniatury w output-dir.
            thumb_path="",
            meta=meta,
            project_id=project_id,
        )
        # Metadane są już w lekkim rekordzie SQLite. Nie zapisujemy obok każdego
        # obrazu/wideo dodatkowego pliku JSON.
        self.record_event(
            mode=a_mode,
            text=prompt or "",
            artifact_id=(art.id if art else None),
            project_id=project_id,
        )
        return art

    # --- zapis mediów (auto-save jak ResultCard/_auto_save_video) ---
    def save_media_urls(
        self,
        urls,
        prompt: str,
        mode: str,
        ext: str,
        download: bool = True,
        project_id=None,
        meta_extra=None,
        strict: bool = False,
    ) -> list:
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
                    log.warning(
                        "Failed to download/save media from %s", url, exc_info=True
                    )
                    if strict:
                        raise
                    path = None
            try:
                self.history.save_to_history(mode, path or url, prompt)
            except Exception:
                log.warning("Failed to record media in history", exc_info=True)
            # M9-B2: artefakt + zdarzenie we wspólnej, przeszukiwalnej historii huba.
            # M11: zwracamy też artifact_id, by GenJob zarejestrował swoje wyjścia.
            art = self._record_media_artifact(
                legacy_mode=mode,
                ext=ext,
                prompt=prompt,
                path=path,
                url=url,
                project_id=project_id,
                meta_extra=meta_extra,
            )
            out.append(
                {"url": url, "path": path, "artifact_id": (art.id if art else None)}
            )
        return out

    def save_provider_outputs(
        self,
        outputs,
        prompt: str,
        mode: str,
        ext: str,
        project_id=None,
        meta_extra=None,
        strict: bool = False,
    ) -> list:
        """Zapisuje neutralne `MediaOutput` bez rozrozniania dostawcy w workerze."""
        out = []
        for output in outputs:
            output_ext = output.extension or ext
            if output.url:
                out.extend(
                    self.save_media_urls(
                        [output.url],
                        prompt,
                        mode,
                        output_ext,
                        project_id=project_id,
                        meta_extra=meta_extra,
                        strict=strict,
                    )
                )
            else:
                out.append(
                    self.save_media_bytes(
                        output.data or b"",
                        prompt,
                        mode,
                        output_ext,
                        project_id=project_id,
                        meta_extra=meta_extra,
                        strict=strict,
                    )
                )
        return out

    def _download_media(self, url: str, save_dir: Path, mode: str, ext: str) -> str:
        """P1-14: pobranie mediów z xAI BEZPIECZNIE — tylko `https` (blokuje SSRF do
        http/file/itp.), strumieniowo na dysk z TWARDYM limitem rozmiaru (bez
        buforowania całości w pamięci). Zwraca ścieżkę pliku albo rzuca wyjątek."""
        if urlparse(url).scheme != "https":
            raise ValueError("refused non-https media URL")
        from caelo_core.storage.files import WorkspaceFileManager

        files = WorkspaceFileManager(save_dir)
        target = files.allocate(mode, ext)
        total = 0
        try:
            # S31-j: nie podążaj za redirectami (https->http omijałby guard) i dodatkowo
            # re-waliduj schemat finalnego URL-a (defense in depth).
            with requests.get(
                url, timeout=180, stream=True, allow_redirects=False
            ) as r:
                if r.is_redirect or r.status_code in (301, 302, 303, 307, 308):
                    raise ValueError("refused redirected media URL")
                if urlparse(r.url).scheme != "https":
                    raise ValueError("refused non-https media URL (after redirect)")
                r.raise_for_status()
                cl = r.headers.get("Content-Length")
                if cl and cl.isdigit() and int(cl) > MAX_MEDIA_BYTES:
                    raise ValueError("media exceeds size cap")

                def checked_chunks():
                    nonlocal total
                    for chunk in r.iter_content(65536):
                        if not chunk:
                            continue
                        total += len(chunk)
                        if total > MAX_MEDIA_BYTES:
                            raise ValueError("media exceeds size cap")
                        yield chunk

                files.atomic_write(target, checked_chunks())
            return str(target)
        except Exception:
            try:
                if target.exists():
                    target.unlink()  # usuń częściowy plik
            except OSError:
                pass
            raise

    def save_media_bytes(
        self,
        data: bytes,
        prompt: str,
        mode: str,
        ext: str,
        project_id=None,
        meta_extra=None,
        strict: bool = False,
    ) -> dict:
        """Zapis gotowych bajtów (np. audio z TTS) do folderu wyjściowego + historia."""
        save_dir = Path(self.history.get_save_path())
        path = None
        try:
            if len(data) > MAX_MEDIA_BYTES:
                raise ValueError("media exceeds size cap")
            save_dir.mkdir(parents=True, exist_ok=True)
            from caelo_core.storage.files import WorkspaceFileManager

            files = WorkspaceFileManager(save_dir)
            target = files.allocate(mode, ext)
            files.atomic_write(target, (data,))
            path = str(target)
        except Exception:
            log.warning("Could not save media bytes to disk", exc_info=True)
            if strict:
                raise
            path = None
        try:
            self.history.save_to_history(mode, path or "", prompt)
        except Exception:
            log.warning("Failed to record media (bytes) in history", exc_info=True)
        # M9-B2: artefakt (np. audio TTS) + zdarzenie w historii huba.
        art = self._record_media_artifact(
            legacy_mode=mode,
            ext=ext,
            prompt=prompt,
            path=path,
            url=None,
            project_id=project_id,
            meta_extra=meta_extra,
        )
        return {"path": path, "artifact_id": (art.id if art else None)}
