"""Adapter pytest dla self-checków (P3-13).

Każdy samodzielny self-check (`tools/*_check.py`, `api_smoke`, `handshake_check`)
biegnie jako OSOBNY test pytest: jego `main()` zwraca `0` (OK) / `1` (FAIL). Daje to
discovery, `pytest -k <nazwa>`, jeden bieg i proste wpięcie w CI. `api_smoke.main()`
orkiestruje suitę rozbitą na `smoke_chat/media/routes/core` + `_smoke_common` (P3-13,
każdy plik < 600 linii) — adapter woła ją niezmiennie przez `main()`.

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
