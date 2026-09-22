"""Lekkie reprezentacje parametrów mediów do historii i odpowiedzi API.

Duże data-URI są potrzebne workerowi, ale nie powinny trafiać do SQLite. Są więc
zapisywane jako zarządzane pliki w katalogu danych aplikacji i materializowane
dopiero tuż przed wywołaniem dostawcy.
"""

from __future__ import annotations

import base64
import binascii
import mimetypes
import os
import shutil
from pathlib import Path
from typing import Any


BLOB_PARAM_KEYS = ("images", "image", "last_image", "video", "reference_images")
FILE_MARKER_KEY = "_caelo_input_file"


def _is_file_marker(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get(FILE_MARKER_KEY), str)
        and isinstance(value.get("mime"), str)
    )


def strip_blob_params(params: dict | None, *, mark_compacted: bool = False) -> dict:
    """Zastąp data-URI krótkim opisem, zachowując prompt, model i pozostałe metadane."""
    out = dict(params or {})
    changed = False

    def compact(value: Any) -> Any:
        nonlocal changed
        if isinstance(value, str) and value.startswith("data:"):
            changed = True
            return f"<data-uri {len(value)} bytes omitted>"
        if _is_file_marker(value):
            changed = True
            return "<stored input omitted>"
        return value

    for key in BLOB_PARAM_KEYS:
        if key not in out:
            continue
        value = out[key]
        out[key] = [compact(item) for item in value] if isinstance(value, list) else compact(value)
    if mark_compacted and changed:
        out["_input_blobs_compacted"] = True
    return out


class JobPayloadStore:
    """Plikowy magazyn wejść generacji, poza bazą i folderem wynikowym."""

    def __init__(self, root) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def externalize(self, job_id: str, params: dict | None) -> dict:
        """Zastąp data-URI markerami małych plików należących do zadania."""
        out = dict(params or {})
        for key in BLOB_PARAM_KEYS:
            if key not in out:
                continue
            value = out[key]
            if isinstance(value, list):
                out[key] = [self._store_value(job_id, key, i, item) for i, item in enumerate(value)]
            else:
                out[key] = self._store_value(job_id, key, 0, value)
        return out

    def materialize(self, params: dict | None) -> dict:
        """Odtwórz data-URI z markerów na czas pojedynczego wywołania providera."""
        out = dict(params or {})
        for key in BLOB_PARAM_KEYS:
            if key not in out:
                continue
            value = out[key]
            if isinstance(value, list):
                out[key] = [self._load_value(item) for item in value]
            else:
                out[key] = self._load_value(value)
        return out

    def cleanup(self, job_id: str) -> None:
        target = self._job_dir(job_id, create=False)
        if target.exists():
            shutil.rmtree(target)

    def _store_value(self, job_id: str, key: str, index: int, value: Any) -> Any:
        if _is_file_marker(value):
            source = self._resolve_marker(value)
            mime = str(value["mime"])
            return self._copy_file(job_id, key, index, source, mime)
        if not isinstance(value, str) or not value.startswith("data:"):
            return value
        header, sep, encoded = value.partition(",")
        if not sep or ";base64" not in header:
            return value
        mime = header[5:].split(";", 1)[0] or "application/octet-stream"
        try:
            data = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            return value
        suffix = mimetypes.guess_extension(mime) or ".bin"
        target = self._job_dir(job_id) / f"{key}_{index}{suffix}"
        self._atomic_write(target, data)
        return {FILE_MARKER_KEY: target.relative_to(self.root).as_posix(), "mime": mime}

    def _copy_file(self, job_id: str, key: str, index: int, source: Path, mime: str) -> dict:
        suffix = source.suffix or mimetypes.guess_extension(mime) or ".bin"
        target = self._job_dir(job_id) / f"{key}_{index}{suffix}"
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + ".part")
        shutil.copyfile(source, partial)
        os.replace(partial, target)
        return {FILE_MARKER_KEY: target.relative_to(self.root).as_posix(), "mime": mime}

    def _load_value(self, value: Any) -> Any:
        if not _is_file_marker(value):
            return value
        source = self._resolve_marker(value)
        encoded = base64.b64encode(source.read_bytes()).decode("ascii")
        return f"data:{value['mime']};base64,{encoded}"

    def _resolve_marker(self, marker: dict) -> Path:
        path = (self.root / str(marker[FILE_MARKER_KEY])).resolve()
        if self.root not in path.parents:
            raise ValueError("job input path escapes payload store")
        return path

    def _job_dir(self, job_id: str, *, create: bool = True) -> Path:
        safe = "".join(ch for ch in str(job_id) if ch.isalnum() or ch in "-_")
        if not safe or safe != str(job_id):
            raise ValueError("invalid job id")
        path = (self.root / safe).resolve()
        if self.root not in path.parents:
            raise ValueError("job path escapes payload store")
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _atomic_write(target: Path, data: bytes) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + ".part")
        try:
            with open(partial, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(partial, target)
        except Exception:
            partial.unlink(missing_ok=True)
            raise
