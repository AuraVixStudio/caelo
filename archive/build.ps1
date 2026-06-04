# Build skrypt (LEGACY) — pakuje starą aplikację customtkinter do .exe.
# DEPRECATED: docelowo zastępowane przez desktop/ (electron-builder + sidecar) —
# patrz ..\docs\REBUILD_PLAN.md. Wynik: archive\dist\AI Studio Pro.exe (portable, onefile).
# Wymaga Pythona z pakietami z requirements.txt (customtkinter/Pillow/…).
Set-Location $PSScriptRoot   # współdzielony rdzeń (config, api_manager…) jest w ..\

Write-Host "== AI Studio Pro :: build (legacy) ==" -ForegroundColor Green

# 1. Zależności
Write-Host "[1/3] Instalacja zależności..." -ForegroundColor Cyan
python -m pip install -r requirements.txt

# 2. Ikona (make_icon.py pozostał w korzeniu — współdzielony z desktop/)
Write-Host "[2/3] Generowanie ikony (appicon.ico)..." -ForegroundColor Cyan
python ..\make_icon.py

# 3. Build (PORTABLE one-file)
Write-Host "[3/3] Budowanie portable .exe (PyInstaller, onefile)..." -ForegroundColor Cyan
python -m PyInstaller --noconfirm --clean "GrokDesktopApp.spec"

if (Test-Path "dist\AI Studio Pro.exe") {
    Write-Host "Gotowe! Portable: archive\dist\AI Studio Pro.exe" -ForegroundColor Green
    Write-Host "Mozesz skopiowac ten JEDEN plik gdziekolwiek i uruchomic." -ForegroundColor Green
} else {
    Write-Host "BLAD: nie znaleziono dist\AI Studio Pro.exe. Sprawdz logi powyzej." -ForegroundColor Red
}
