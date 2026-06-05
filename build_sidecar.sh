#!/usr/bin/env bash
# build_sidecar.sh — buduje sidecar caelo-core do dist/caelo-core/ (PyInstaller onedir),
# odpowiednik build_sidecar.ps1 dla macOS / Linux (M15-9, cross-platform packaging).
#
# Cross-compile PyInstallera jest niepraktyczny — URUCHAMIAJ NA DOCELOWYM OS
# (lokalnie albo na runnerze CI per-OS, patrz .github/workflows/release.yml).
#
# Użycie:  bash build_sidecar.sh
# Wynik:   dist/caelo-core/caelo-core (+ _internal/)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$ROOT/caelo_core/.venv"
if [ -d "$VENV/bin" ]; then
  PY="$VENV/bin/python"
else
  PY="$VENV/Scripts/python"   # na wypadek venv w stylu Windows
fi

if [ ! -x "$PY" ] && [ ! -f "$PY" ]; then
  echo "Brak caelo_core/.venv — tworzę i instaluję zależności…"
  python3 -m venv "$VENV"
  PY="$VENV/bin/python"
  "$PY" -m pip install --upgrade pip
  "$PY" -m pip install -r "$ROOT/caelo_core/requirements.txt"
fi

# Narzędzie budowania (PyInstaller). pywinpty NIE jest potrzebne poza Windows —
# terminal używa stdlib `pty` (M15-5), a spec pomija winpty (collect_all w try/except).
"$PY" -m pip install --upgrade pyinstaller

echo "Buduję sidecar (PyInstaller onedir)…"
cd "$ROOT"
"$PY" -m PyInstaller --noconfirm --clean "$ROOT/caelo_core.spec"

BIN="$ROOT/dist/caelo-core/caelo-core"
if [ -f "$BIN" ]; then
  echo "OK: $BIN"
else
  echo "Build nie wyprodukował $BIN" >&2
  exit 1
fi
