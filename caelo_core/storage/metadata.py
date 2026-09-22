from __future__ import annotations

import json
import os
import time
from pathlib import Path


def write_sidecar(media_path, metadata: dict) -> Path:
    target = Path(str(media_path) + ".json")
    partial = target.with_name(target.name + ".part")
    payload = {"schema_version": 1, "created_at": time.time(), **dict(metadata or {})}
    with open(partial, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(partial, target)
    return target
