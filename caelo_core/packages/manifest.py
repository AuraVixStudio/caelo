"""Format manifestu pakietu społeczności (M16-1) + logika wersji/kompatybilności.

Jeden wersjonowany format dla wszystkiego, co dzielone (skille / komendy /
konfiguracje MCP / szablony projektów). Pakiet `.caelopkg` to archiwum ZIP:

    manifest.json          # ten manifest (na korzeniu archiwum)
    payload/...            # zawartość zależna od typu (patrz niżej)

`integrity` w manifeście to **sha256 payloadu** (kanoniczna konkatenacja posortowanych
par `(arcname, bytes)` spod `payload/`) — NIE obejmuje samego manifestu (który ten hash
nosi). Import przelicza i porównuje (M16-2: cicha modyfikacja payloadu = odrzucenie).

`requires.app` to wymaganie wersji aplikacji w stylu `">=1.0"` / `"1.x"` / `"*"` —
sprawdzane przy inspekcji/aktualizacji (M16-7). Wszystko świadomie minimalne i bez
zależności (jak `markdown_meta` vs pełny YAML).
"""

from __future__ import annotations

import hashlib
import re
from typing import Optional, Tuple

SCHEMA_VERSION = 1
PACKAGE_TYPES = ("skill", "command", "mcp", "template")
PAYLOAD_PREFIX = "payload/"

# Nazwy id/typu — function-call-safe i bezpieczne jako nazwa folderu (anty-traversal).
_ID_RX = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
_VERSION_RX = re.compile(r"^\d+(\.\d+){0,3}([-+][0-9A-Za-z.-]+)?$")


class ManifestError(ValueError):
    """Manifest niepoprawny / nieobsługiwany (walidacja M16-1)."""


# --- wersje (M16-7) ----------------------------------------------------------
def parse_version(v: str) -> Tuple[int, ...]:
    """„1.2.3" → (1, 2, 3). Ignoruje sufiks pre-release/build. Brak/zły → (0,)."""
    if not v:
        return (0,)
    core = re.split(r"[-+]", str(v).strip(), maxsplit=1)[0]
    parts: list[int] = []
    for chunk in core.split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            break
    return tuple(parts) or (0,)


def version_compare(a: str, b: str) -> int:
    """-1 / 0 / 1 dla a<b / a==b / a>b (porównanie liczbowe po segmentach)."""
    pa, pb = parse_version(a), parse_version(b)
    width = max(len(pa), len(pb))
    pa += (0,) * (width - len(pa))
    pb += (0,) * (width - len(pb))
    return (pa > pb) - (pa < pb)


def requirement_satisfied(requirement: str, app_version: str) -> bool:
    """Czy `app_version` spełnia wymaganie typu `">=1.0"`, `"1.x"`, `"*"`, `"1.2.0"`.

    Obsługiwane operatory: `>=`, `>`, `<=`, `<`, `==`/`=`, brak operatora = `==`
    (dopasowanie po prefiksie, np. `"1"` pasuje do `1.4`). `*`/pusty → zawsze ok.
    Tolerancyjne: niezrozumiałe wymaganie → True (nie blokujemy fałszywie)."""
    req = (requirement or "").strip()
    if not req or req == "*":
        return True
    m = re.match(r"^(>=|<=|==|=|>|<)?\s*(.+)$", req)
    if not m:
        return True
    op = m.group(1) or "=="
    target = m.group(2).strip().rstrip(".x").strip(".")
    if not target or target == "*":
        return True
    cmp = version_compare(app_version, target)
    if op in (">=",):
        return cmp >= 0
    if op == ">":
        return cmp > 0
    if op == "<=":
        return cmp <= 0
    if op == "<":
        return cmp < 0
    # równość/prefiks: „1" spełnia 1.x; „1.2" spełnia 1.2.x
    av = parse_version(app_version)
    tv = parse_version(target)
    return av[: len(tv)] == tv


# --- integralność (M16-1) ----------------------------------------------------
def compute_integrity(payload_files: dict) -> str:
    """sha256 payloadu (`{arcname_bez_prefiksu: bytes}`) → "sha256:<hex>".

    Kanonicznie: posortowane nazwy, każdą poprzedza długość (zapobiega kolizjom
    przy konkatenacji). Deterministyczne — eksport i import liczą identycznie."""
    h = hashlib.sha256()
    for name in sorted(payload_files):
        data = payload_files[name]
        if isinstance(data, str):
            data = data.encode("utf-8")
        h.update(name.encode("utf-8"))
        h.update(b"\0")
        h.update(str(len(data)).encode("ascii"))
        h.update(b"\0")
        h.update(data)
        h.update(b"\0")
    return "sha256:" + h.hexdigest()


# --- permissions / zakres narzędzi (M16-1/M16-2) -----------------------------
def normalize_permissions(perm: Optional[dict]) -> dict:
    """Znormalizuj deklarowane uprawnienia/zakres. Wszystkie pola są DEKLARACJĄ
    autora (informacyjne dla importera) — egzekwowanie i tak idzie przez reżim M14
    (bramka, jawny start serwera, brak auto-run)."""
    p = perm if isinstance(perm, dict) else {}
    tools = p.get("tools")
    if isinstance(tools, str):
        tools = [t.strip() for t in tools.split(",") if t.strip()]
    return {
        "tools": [str(t) for t in (tools or [])][:64],
        "starts_process": bool(p.get("starts_process")),
        "writes_files": bool(p.get("writes_files")),
        "network": bool(p.get("network")),
    }


def risk_level(ptype: str, permissions: dict) -> str:
    """Heurystyka ryzyka do UI: 'high' (uruchamia proces / komendy), 'medium'
    (pisze pliki / sieć / komenda z akcją), 'low' (sam tekst/prompt)."""
    perm = normalize_permissions(permissions)
    if perm["starts_process"] or ptype == "mcp":
        return "high"
    if perm["writes_files"] or perm["network"] or ptype in ("template", "command"):
        return "medium"
    return "low"


# --- manifest (M16-1) --------------------------------------------------------
def validate_manifest(raw: dict) -> dict:
    """Zwaliduj + znormalizuj manifest. Rzuca `ManifestError` przy brakach/błędach.
    NIE sprawdza integralności (to robi manager, mając payload)."""
    if not isinstance(raw, dict):
        raise ManifestError("manifest must be an object")
    schema = raw.get("schema", SCHEMA_VERSION)
    try:
        schema = int(schema)
    except (TypeError, ValueError):
        raise ManifestError("manifest 'schema' must be an integer")
    if schema > SCHEMA_VERSION:
        raise ManifestError(
            f"package schema {schema} is newer than supported ({SCHEMA_VERSION}); update the app")
    ptype = (raw.get("type") or "").strip().lower()
    if ptype not in PACKAGE_TYPES:
        raise ManifestError(f"type must be one of {PACKAGE_TYPES}")
    pid = (raw.get("id") or "").strip()
    if not _ID_RX.match(pid):
        raise ManifestError("id must match [a-zA-Z0-9_-]{1,64}")
    version = str(raw.get("version") or "0.0.0").strip()
    if not _VERSION_RX.match(version):
        raise ManifestError("version must look like 1.2.3")
    requires = raw.get("requires") if isinstance(raw.get("requires"), dict) else {}
    out = {
        "schema": schema,
        "id": pid,
        "name": str(raw.get("name") or pid)[:200],
        "version": version,
        "type": ptype,
        "author": str(raw.get("author") or "")[:120],
        "description": str(raw.get("description") or "")[:2000],
        "requires": {
            "app": str(requires.get("app") or "*")[:40],
            "model": str(requires.get("model") or "")[:80],
        },
        "permissions": normalize_permissions(raw.get("permissions")),
        "source": str(raw.get("source") or "")[:500],
        "integrity": str(raw.get("integrity") or ""),
    }
    return out


def is_safe_payload_name(name: str) -> bool:
    """Czy `name` (arcname spod payload/) jest bezpieczny: względny, bez `..`,
    bez dysku/korzenia, bez bajtów null. Anty-Zip-Slip (M16-2)."""
    if not name or "\x00" in name:
        return False
    norm = name.replace("\\", "/")
    if norm.startswith("/") or re.match(r"^[A-Za-z]:", norm):
        return False
    parts = norm.split("/")
    return all(p not in ("", "..") for p in parts)
