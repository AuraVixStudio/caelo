"""Pakiety społeczności / marketplace (M16) — warstwa dystrybucji nad M14.

Eksport/import wersjonowanych pakietów `.caelopkg` (skille / komendy / konfiguracje
MCP / szablony projektów) z manifestem + integralnością, bezpieczny import za zgodą,
registry oparte o git/GitHub i sprawdzanie aktualizacji. Patrz `manager.PackageManager`
oraz `manifest` (format/walidacja/wersje).
"""

from caelo_core.packages.manager import PackageError, PackageManager

__all__ = ["PackageManager", "PackageError"]
