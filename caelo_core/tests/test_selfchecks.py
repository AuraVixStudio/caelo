"""Adapter pytest dla self-checków (P3-13).

Każdy samodzielny self-check (`tools/*_check.py`, `api_smoke`, `handshake_check`)
biegnie jako OSOBNY test pytest: jego `main()` zwraca `0` (OK) / `1` (FAIL). Daje to
discovery, `pytest -k <nazwa>`, jeden bieg i proste wpięcie w CI — BEZ przepisywania
~2,5 tys. linii asercji (zachowujemy sprawdzoną siatkę bezpieczeństwa). Pełny,
mechaniczny rozbiór `api_smoke.py` (2218 linii → `test_routes_*`) jest osobnym
podetapem — patrz nota P3-13 w `docs/PLAN_NAPRAWY_3.md`.

`sidecar_smoke` celowo pominięty — wymaga SPAKOWANEGO `.exe` (osobny krok wydania).
Każda suita drukuje własne `[PASS]/[FAIL]`; pytest przechwytuje to i pokazuje przy błędzie.
"""

import importlib

import pytest

# Kolejność jak w CI/README. Lekkie (mock) przed ciężkimi (spawn sidecara).
SUITES = [
    "crossplatform_check",
    "mcp_check",
    "genjobs_check",
    "history_check",
    "packages_check",
    "agent_selfcheck",
    "handshake_check",
    "api_smoke",
]


@pytest.mark.parametrize("suite", SUITES)
def test_selfcheck(suite: str) -> None:
    mod = importlib.import_module(f"caelo_core.tools.{suite}")
    rc = mod.main()
    assert rc == 0, f"{suite}.main() returned {rc} (zob. przechwycone wyjście powyżej)"
