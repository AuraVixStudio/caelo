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

# ROAD-TOP2 / Faza B Krok 6.3: opcjonalny podpis Authenticode sidecara. electron-builder
# podpisuje powłokę Electron + instalator, ale NIE obejmuje spakowanego `caelo-core.exe`
# (extraResources) — to domyka „exe sidecara" z DoD TOP2. NO-OP, dopóki nie ustawisz
# $env:CAELO_SIGN_THUMBPRINT (thumbprint certu SimplySign ze sklepu Windows; wymaga
# aktywnego SimplySign Desktop). Bez zmiennej skrypt działa dokładnie jak dotąd.
if ($env:CAELO_SIGN_THUMBPRINT) {
    $signtool = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if (-not $signtool) {
        Write-Warning "CAELO_SIGN_THUMBPRINT set but signtool.exe not found in PATH (Windows SDK) - skipping sidecar signing."
    } else {
        Write-Host "Signing sidecar (cert $env:CAELO_SIGN_THUMBPRINT)..." -ForegroundColor Cyan
        & $signtool.Source sign /sha1 $env:CAELO_SIGN_THUMBPRINT /fd sha256 /tr http://time.certum.pl /td sha256 $exe
        if ($LASTEXITCODE -ne 0) { throw "Sidecar signing failed (signtool exit $LASTEXITCODE)" }
        Write-Host "OK: sidecar signed" -ForegroundColor Green
    }
}
