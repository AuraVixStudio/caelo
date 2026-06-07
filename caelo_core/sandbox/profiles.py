"""Profile sandboxa OS (M19-B7) — model + ładowanie konfiguracji.

Profil opisuje, co proces potomny `run_command`/MCP/LSP może czytać/pisać i czy ma
sieć. Cztery wbudowane (jak Grok CLI):
- `off`      — brak sandboxa (no-op; `wrap()` zwraca argv bez zmian),
- `workspace`— read WSZĘDZIE, write tylko: korzeń (CWD/workspace) + /tmp + DATA_DIR,
- `read-only`— read wszędzie, write tylko DATA_DIR (workspace tylko do odczytu),
- `strict`   — read/write TYLKO korzeń; **bez sieci** dziecka.

Ścieżki wrażliwe (`~/.ssh`/`~/.aws`/`~/.gnupg`/`DATA_DIR/caelo_auth.json`) są ZAWSZE
na deny-liście, niezależnie od profilu.

Konfiguracja (opcjonalna): `DATA_DIR/sandbox.json` (globalna) + `<ws>/.caelo/sandbox.json`
(projektowa, nadpisuje) — **JSON** przez `config.load_json_or_backup` (konwencja repo, jak
`lsp.json`/`permissions.json`; NIE TOML). Klucze: `default_profile`, `read_only` (extra read),
`read_write` (extra write), `deny` (extra deny), `restrict_network` (bool).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import config  # type: ignore

log = logging.getLogger(__name__)

VALID_PROFILES = ("off", "workspace", "read-only", "strict")


@dataclass
class Profile:
    """Rozwinięty profil (po scaleniu wbudowanego szkieletu + configu)."""
    name: str
    read_all: bool = False                       # czytaj wszędzie (workspace/read-only)
    read_paths: List[str] = field(default_factory=list)   # gdy NIE read_all (strict)
    write_paths: List[str] = field(default_factory=list)  # zapisywalne korzenie
    deny_paths: List[str] = field(default_factory=list)   # zawsze zabronione (wrażliwe)
    restrict_network: bool = False               # odetnij sieć dziecku (strict)


def sensitive_paths() -> List[str]:
    """Ścieżki ZAWSZE chronione (sekrety) — niezależnie od profilu."""
    home = Path.home()
    out = [str(home / ".ssh"), str(home / ".aws"), str(home / ".gnupg")]
    try:
        out.append(str(Path(config.DATA_DIR) / "caelo_auth.json"))
    except Exception:  # noqa: BLE001
        pass
    return out


def _norm_list(v) -> List[str]:
    return [str(x) for x in v if str(x)] if isinstance(v, (list, tuple)) else []


def build_profile(name: str, *, root: Optional[str] = None,
                  extra_read: Optional[List[str]] = None,
                  extra_write: Optional[List[str]] = None,
                  deny: Optional[List[str]] = None,
                  restrict_network: Optional[bool] = None) -> Profile:
    """Zbuduj `Profile` z nazwy wbudowanej + (opcjonalnych) rozszerzeń z configu.
    Nieznana nazwa → `off` (fail-safe: brak sandboxa zamiast błędu)."""
    name = name if name in VALID_PROFILES else "off"
    data_dir = str(getattr(config, "DATA_DIR", "") or "")
    root = str(root) if root else ""
    deny_paths = sensitive_paths() + _norm_list(deny)

    if name == "off":
        return Profile("off", deny_paths=deny_paths)
    if name == "workspace":
        prof = Profile("workspace", read_all=True,
                       write_paths=[p for p in (root, "/tmp", data_dir) if p],
                       deny_paths=deny_paths, restrict_network=False)
    elif name == "read-only":
        prof = Profile("read-only", read_all=True,
                       write_paths=[p for p in (data_dir,) if p],
                       deny_paths=deny_paths, restrict_network=False)
    else:  # strict
        prof = Profile("strict", read_all=False,
                       read_paths=[p for p in (root,) if p],
                       write_paths=[p for p in (root,) if p],
                       deny_paths=deny_paths, restrict_network=True)
    prof.read_paths += _norm_list(extra_read)
    prof.write_paths += _norm_list(extra_write)
    if restrict_network is not None:
        prof.restrict_network = bool(restrict_network)
    return prof


def _load_json(path: Path) -> dict:
    data = config.load_json_or_backup(path, {}) or {}
    return data if isinstance(data, dict) else {}


def _global_config() -> dict:
    try:
        return _load_json(Path(config.DATA_DIR) / "sandbox.json")
    except Exception:  # noqa: BLE001
        return {}


def _project_config(root: Optional[str]) -> dict:
    if not root:
        return {}
    # M19-B14: scal `.caelo/sandbox.json` z łańcucha korzeń-repo→workspace (deeper wygrywa
    # per klucz). Pojedynczy root (GUI / brak repo) → jeden plik (jak przed B14).
    try:
        from caelo_core.agent.project import project_dir_chain
        merged: dict = {}
        for d in project_dir_chain(root):
            cfg = _load_json(Path(d) / ".caelo" / "sandbox.json")
            if isinstance(cfg, dict):
                merged.update(cfg)
        return merged
    except Exception:  # noqa: BLE001
        return {}


def resolve_profile(*, root: Optional[str] = None) -> Profile:
    """Rozstrzygnij aktywny profil: nazwa = projekt > globalny plik > `config.SANDBOX_PROFILE`
    (env `CAELO_SANDBOX`). Listy read/write/deny/network scalane (projekt rozszerza globalny).
    Brak configu/„off" → profil `off` (no-op)."""
    g = _global_config()
    proj = _project_config(root)
    name = (proj.get("default_profile") or g.get("default_profile")
            or getattr(config, "SANDBOX_PROFILE", "off") or "off")
    return build_profile(
        str(name).strip().lower(), root=root,
        extra_read=_norm_list(g.get("read_only")) + _norm_list(proj.get("read_only")),
        extra_write=_norm_list(g.get("read_write")) + _norm_list(proj.get("read_write")),
        deny=_norm_list(g.get("deny")) + _norm_list(proj.get("deny")),
        restrict_network=(proj.get("restrict_network")
                          if proj.get("restrict_network") is not None
                          else g.get("restrict_network")),
    )
