"""Silnik agenta kodowania (Faza 4).

Składniki:
- workspace.py    — katalog roboczy + sandbox ścieżek,
- permissions.py  — bramka zatwierdzania (read-only bez zgody, mutacje za zgodą),
- tools.py        — narzędzia plikowe (schematy + egzekutory + podgląd diff),
- llm.py          — streaming czatu z tool-calls na xAI (akumulacja delt),
- session.py      — pętla agenta (model → narzędzia → wynik → powtórz).
"""
