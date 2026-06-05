"""CAELO.md — auto-pamięć projektu (M13-B4), odpowiednik CLAUDE.md / AGENTS.md.

Na starcie tury agenta wczytujemy `CAELO.md` z:
  (a) korzenia workspace  — reguły tego konkretnego projektu,
  (b) globalnego `DATA_DIR` — reguły wspólne dla wszystkich projektów,
i wstrzykujemy do system promptu. Workspace **nadpisuje/uzupełnia** globalny
(idzie później, z jawną adnotacją dla modelu). UTF-8, twardy cap rozmiaru,
brak pliku tolerowany.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

CAELO_MD_NAME = "CAELO.md"
# Wsteczna zgodność: stare repozytoria (sprzed rebrandu M15) mają GROK.md.
# Czytamy je, gdy CAELO.md nie istnieje; zapis zawsze idzie do CAELO.md.
LEGACY_MD_NAME = "GROK.md"
MAX_CAELO_MD_BYTES = 32 * 1024  # cap, by reguły projektu nie zjadły całego kontekstu


def _read_capped(p: Path) -> str:
    try:
        if not p.is_file():
            return ""
        data = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if len(data) > MAX_CAELO_MD_BYTES:
        data = data[:MAX_CAELO_MD_BYTES] + "\n… (truncated)"
    return data.strip()


def _read_dir_md(base: Optional[str | Path]) -> str:
    """Wczytaj CAELO.md z katalogu, z fallbackiem na starą nazwę GROK.md."""
    if not base:
        return ""
    primary = _read_capped(Path(base) / CAELO_MD_NAME)
    if primary:
        return primary
    return _read_capped(Path(base) / LEGACY_MD_NAME)  # wsteczna zgodność


def load_caelo_md(workspace_root: Optional[str | Path],
                 global_dir: Optional[str | Path]) -> str:
    """Połączona treść CAELO.md (global, potem workspace). Pusty string, gdy brak."""
    parts: list[str] = []
    g = _read_dir_md(global_dir)
    w = _read_dir_md(workspace_root)
    if g:
        parts.append("## Global project rules\n" + g)
    if w:
        parts.append("## Workspace project rules\n" + w)
    return "\n\n".join(parts)


def build_system_prompt(base: str, workspace_root: Optional[str | Path],
                        global_dir: Optional[str | Path]) -> str:
    """Dopnij reguły CAELO.md do bazowego system promptu (jeśli istnieją)."""
    extra = load_caelo_md(workspace_root, global_dir)
    if not extra:
        return base
    return (
        base
        + "\n\n--- Project rules from CAELO.md (ALWAYS follow; workspace rules "
          "override global ones) ---\n" + extra
    )
