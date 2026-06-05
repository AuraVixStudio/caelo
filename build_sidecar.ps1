<#
  build_sidecar.ps1 — buduje sidecar caelo-core do dist\caelo-core\ (PyInstaller onedir).

  Używa interpretera z caelo_core\.venv (ma zależności backendu: fastapi/uvicorn/…).
  Dba o obecność PyInstallera i pywinpty (terminal), po czym uruchamia spec.

  Użycie:   pwsh -File build_sidecar.ps1
  Wynik:    dist\caelo-core\caelo-core.exe (+ _internal\)
#>
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$venvPy = Join-Path $root 'caelo_core\.venv\Scripts\python.exe'

if (-not (Test-Path $venvPy)) {
    Write-Host "Brak caelo_core\.venv — tworzę i instaluję zależności…" -ForegroundColor Yellow
    python -m venv (Join-Path $root 'caelo_core\.venv')
    & $venvPy -m pip install --upgrade pip
    & $venvPy -m pip install -r (Join-Path $root 'caelo_core\requirements.txt')
}

# Narzędzia budowania (PyInstaller) + opcjonalny pywinpty dla terminala.
& $venvPy -m pip install --upgrade pyinstaller
& $venvPy -m pip install "pywinpty>=2.0"

Write-Host "Buduję sidecar (PyInstaller onedir)…" -ForegroundColor Cyan
Push-Location $root
try {
    & $venvPy -m PyInstaller --noconfirm --clean (Join-Path $root 'caelo_core.spec')
}
finally {
    Pop-Location
}

$exe = Join-Path $root 'dist\caelo-core\caelo-core.exe'
if (Test-Path $exe) {
    Write-Host "OK: $exe" -ForegroundColor Green
} else {
    throw "Build nie wyprodukował $exe"
}
