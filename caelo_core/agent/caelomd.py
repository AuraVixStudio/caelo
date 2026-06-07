"""CAELO.md — auto-pamięć projektu (M13-B4), odpowiednik CLAUDE.md / AGENTS.md.

Na starcie tury agenta wczytujemy reguły projektu z:
  (a) korzenia workspace  — reguły tego konkretnego projektu,
  (b) globalnego `DATA_DIR` — reguły wspólne dla wszystkich projektów,
i wstrzykujemy do system promptu. Workspace **nadpisuje/uzupełnia** globalny
(idzie później, z jawną adnotacją dla modelu). UTF-8, twardy cap rozmiaru
(per plik), brak pliku tolerowany.

**Interop ekosystemu (M19-Tier2 B5 §1.1):** w katalogu WORKSPACE czytamy NIE tylko
natywny `CAELO.md`, ale też pliki konwencji Claude Code / Grok CLI — `AGENTS.md`
i `CLAUDE.md` (z wariantami) — by istniejące projekty „po prostu działały".
Wszystkie istniejące pliki są **sklejane** w kolejności pierwszeństwa
(natywne → AGENTS.md → CLAUDE.md), każdy capowany osobno, z adnotacją źródła.
Zapis (REST `/caelo-md`) zawsze idzie do natywnego `CAELO.md`.

⚠️ **Interop dotyczy TYLKO workspace, NIE globalnego `DATA_DIR`.** Globalnie bierzemy
wyłącznie natywny `CAELO.md` — w trybie dev `DATA_DIR == repo Caelo`, którego
`CLAUDE.md` (instrukcje dewelopera) inaczej wyciekałby do każdej sesji agenta nad
dowolnym, obcym projektem.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from caelo_core.agent.project import project_dir_chain

CAELO_MD_NAME = "CAELO.md"
# Wsteczna zgodność: stare repozytoria (sprzed rebrandu M15) mają GROK.md.
# Czytamy je, gdy CAELO.md nie istnieje; zapis zawsze idzie do CAELO.md.
LEGACY_MD_NAME = "GROK.md"
# B5 (interop): dodatkowe nazwy z ekosystemu, czytane PO natywnym pliku, w tej
# kolejności pierwszeństwa. AGENTS.md = konwencja Grok CLI / społeczności,
# CLAUDE.md = Claude Code. Warianty wielkości liter dla systemów case-sensitive
# (na Windows i tak deduplikujemy przez normcase).
INTEROP_MD_NAMES = (
    "AGENTS.md", "AGENT.md", "Agents.md",
    "CLAUDE.md", "Claude.md",
)
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


def _read_dir_md(base: Optional[str | Path], *, include_interop: bool = True) -> str:
    """Wczytaj i sklej reguły projektu z katalogu.

    Najpierw plik natywny (`CAELO.md`, a gdy go brak — legacy `GROK.md`), potem —
    gdy `include_interop` — wszystkie istniejące pliki interop (`AGENTS.md`/`CLAUDE.md`
    + warianty) w kolejności pierwszeństwa. Każdy plik jest capowany osobno i opatrzony
    adnotacją źródła. Deduplikacja po `normcase` ścieżki łapie kolizje wielkości
    liter na case-insensitive FS (Windows: `AGENTS.md` == `Agents.md`), a na
    case-sensitive FS (Linux) traktuje warianty jako osobne pliki — zgodnie z FS.

    **`include_interop=False` dla katalogu GLOBALNEGO (`DATA_DIR`).** Interop
    (`CLAUDE.md`/`AGENTS.md`) to konwencja PER-PROJEKT — czytamy ją tylko z workspace.
    Globalnie bierzemy WYŁĄCZNIE natywny `CAELO.md`, bo w trybie dev `DATA_DIR == repo
    Caelo`, którego `CLAUDE.md` (instrukcje dewelopera) wyciekałby do KAŻDEJ sesji
    agenta — także nad zupełnie obcym projektem (poważny błąd izolacji).
    """
    if not base:
        return ""
    base_path = Path(base)
    parts: list[str] = []
    seen: set[str] = set()

    def _add(name: str) -> None:
        p = base_path / name
        key = os.path.normcase(str(p))
        if key in seen:
            return
        seen.add(key)
        text = _read_capped(p)
        if text:
            parts.append(f"### From {name}\n{text}")

    # Natywny plik: CAELO.md ma pierwszeństwo; gdy go brak — legacy GROK.md.
    native = CAELO_MD_NAME if (base_path / CAELO_MD_NAME).is_file() else LEGACY_MD_NAME
    _add(native)
    # Interop (AGENTS.md/CLAUDE.md) TYLKO dla workspace/projektu, nie dla DATA_DIR.
    if include_interop:
        for name in INTEROP_MD_NAMES:
            _add(name)
    return "\n\n".join(parts)


def load_caelo_md(workspace_root: Optional[str | Path],
                 global_dir: Optional[str | Path]) -> str:
    """Połączona treść CAELO.md: global → przodkowie projektu → workspace. Pusty string,
    gdy brak.

    M19-B14: zamiast czytać tylko `workspace_root`, idziemy łańcuchem od korzenia repo
    (najbliższy `.git` w górę) DO workspace — przodkowie najpierw, workspace ostatni
    (deeper-wins; model widzi reguły bliższe workspace jako nadrzędne, zgodnie z nagłówkiem
    wstrzyknięcia). Gdy workspace jest korzeniem repo / nie ma repo → łańcuch to sam
    workspace (zachowanie sprzed B14)."""
    parts: list[str] = []
    # Globalny DATA_DIR: TYLKO natywny CAELO.md (bez interopu) — patrz _read_dir_md:
    # w dev DATA_DIR == repo Caelo, wiec jego CLAUDE.md NIE moze trafic do agenta.
    g = _read_dir_md(global_dir, include_interop=False)
    if g:
        parts.append("## Global project rules\n" + g)
    chain = project_dir_chain(workspace_root) if workspace_root else []
    for idx, d in enumerate(chain):
        w = _read_dir_md(d)
        if not w:
            continue
        if idx == len(chain) - 1:  # najgłębszy = workspace
            parts.append("## Workspace project rules\n" + w)
        else:                       # przodek (monorepo)
            parts.append(f"## Project rules (ancestor: {d.name})\n" + w)
    return "\n\n".join(parts)


def build_system_prompt(base: str, workspace_root: Optional[str | Path],
                        global_dir: Optional[str | Path]) -> str:
    """Dopnij reguły CAELO.md do bazowego system promptu (jeśli istnieją)."""
    extra = load_caelo_md(workspace_root, global_dir)
    if not extra:
        return base
    return (
        base
        + "\n\n--- Project rules from CAELO.md / AGENTS.md / CLAUDE.md (ALWAYS "
          "follow; workspace rules override global ones) ---\n" + extra
    )
