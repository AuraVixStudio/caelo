"""Punkt wejścia PyInstaller dla sidecara caelo-core.

PyInstaller analizuje plik-skrypt (nie pakiet), więc dajemy mu cienki wrapper,
który po prostu woła `caelo_core.__main__.main()`. Logika handshake'u (port +
token na stdout) jest identyczna jak przy `python -m caelo_core` — Electron nie
rozróżnia, czy rozmawia z interpreterem dev, czy ze spakowanym .exe.
"""

from __future__ import annotations

import multiprocessing

from caelo_core.__main__ import main

if __name__ == "__main__":
    # Bez tego spakowany .exe mógłby rekurencyjnie respawnować się przy użyciu
    # multiprocessing (np. przez zależności uvicorna) — no-op w trybie dev.
    multiprocessing.freeze_support()
    main()
