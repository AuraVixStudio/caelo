"""GROK.md — auto-pamięć projektu (M13-B4), odpowiednik CLAUDE.md / AGENTS.md.

Na starcie tury agenta wczytujemy `GROK.md` z:
  (a) korzenia workspace  — reguły tego konkretnego projektu,
  (b) globalnego `DATA_DIR` — reguły wspólne dla wszystkich projektów,
i wstrzykujemy do system promptu. Workspace **nadpisuje/uzupełnia** globalny
(idzie później, z jawną adnotacją dla modelu). UTF-8, twardy cap rozmiaru,
brak pliku tolerowany.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

GROK_MD_NAME = "GROK.md"
MAX_GROK_MD_BYTES = 32 * 1024  # cap, by reguły projektu nie zjadły całego kontekstu


def _read_capped(p: Path) -> str:
    try:
        if not p.is_file():
            return ""
        data = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if len(data) > MAX_GROK_MD_BYTES:
        data = data[:MAX_GROK_MD_BYTES] + "\n… (truncated)"
    return data.strip()


def load_grok_md(workspace_root: Optional[str | Path],
                 global_dir: Optional[str | Path]) -> str:
    """Połączona treść GROK.md (global, potem workspace). Pusty string, gdy brak."""
    parts: list[str] = []
    g = _read_capped(Path(global_dir) / GROK_MD_NAME) if global_dir else ""
    w = _read_capped(Path(workspace_root) / GROK_MD_NAME) if workspace_root else ""
    if g:
        parts.append("## Global project rules\n" + g)
    if w:
        parts.append("## Workspace project rules\n" + w)
    return "\n\n".join(parts)


def build_system_prompt(base: str, workspace_root: Optional[str | Path],
                        global_dir: Optional[str | Path]) -> str:
    """Dopnij reguły GROK.md do bazowego system promptu (jeśli istnieją)."""
    extra = load_grok_md(workspace_root, global_dir)
    if not extra:
        return base
    return (
        base
        + "\n\n--- Project rules from GROK.md (ALWAYS follow; workspace rules "
          "override global ones) ---\n" + extra
    )
