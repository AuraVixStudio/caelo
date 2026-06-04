"""Punkt wejścia PyInstaller dla sidecara grok-core.

PyInstaller analizuje plik-skrypt (nie pakiet), więc dajemy mu cienki wrapper,
który po prostu woła `grok_core.__main__.main()`. Logika handshake'u (port +
token na stdout) jest identyczna jak przy `python -m grok_core` — Electron nie
rozróżnia, czy rozmawia z interpreterem dev, czy ze spakowanym .exe.
"""

from __future__ import annotations

import multiprocessing

from grok_core.__main__ import main

if __name__ == "__main__":
    # Bez tego spakowany .exe mógłby rekurencyjnie respawnować się przy użyciu
    # multiprocessing (np. przez zależności uvicorna) — no-op w trybie dev.
    multiprocessing.freeze_support()
    main()
