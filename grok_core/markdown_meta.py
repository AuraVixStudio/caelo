"""Minimalny parser frontmatter Markdown (M14-B4/B6) — bez zależności YAML.

Obsługuje blok `--- ... ---` na początku pliku z prostymi liniami `klucz: wartość`.
Wartości w `[a, b, c]` → lista; `true/false` → bool; reszta → string (zdjęte cudzysłowy).
Świadomie minimalny (komendy/skille mają płaskie metadane) — nie pełny YAML."""

from __future__ import annotations

from typing import Tuple


def _coerce(value: str):
    v = value.strip()
    if len(v) >= 2 and v[0] in "\"'" and v[-1] == v[0]:
        return v[1:-1]
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        if not inner:
            return []
        return [p.strip().strip("\"'") for p in inner.split(",") if p.strip()]
    return v


def parse_frontmatter(text: str) -> Tuple[dict, str]:
    """Zwraca (meta, body). Brak frontmatter → ({}, cały tekst)."""
    if not text:
        return {}, ""
    norm = text.lstrip("﻿")  # zdejmij BOM
    if not norm.startswith("---"):
        return {}, text
    lines = norm.splitlines()
    # pierwsza linia to '---'; szukaj zamykającego '---'
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, text
    meta: dict = {}
    for ln in lines[1:end]:
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        if ":" not in ln:
            continue
        key, _, val = ln.partition(":")
        meta[key.strip()] = _coerce(val)
    body = "\n".join(lines[end + 1:]).strip("\n")
    return meta, body
