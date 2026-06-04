# -*- mode: python ; coding: utf-8 -*-
# Budowa (PORTABLE, jeden plik .exe):
#   python make_icon.py
#   python -m PyInstaller --noconfirm --clean GrokDesktopApp.spec
# Wynik: dist\AI Studio Pro.exe  (działa z dowolnej lokalizacji)
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []
for pkg in ('customtkinter', 'tkinterdnd2', 'PIL'):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# Ikona dołączona do paczki (używana też jako ikona okna w czasie działania)
datas += [('appicon.ico', '.')]

a = Analysis(
    ['app.py'],
    pathex=['..'],   # współdzielony rdzeń (config, api_manager…) jest w korzeniu repo (archive/..)
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# Tryb ONEFILE: wszystkie binaria/dane wchodzą do jednego pliku .exe (brak COLLECT).
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='AI Studio Pro',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                # UPX off — mniej fałszywych alarmów antywirusów
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,            # aplikacja okienkowa (bez konsoli)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='appicon.ico',
    version='version_info.txt',   # osadza wersję 1.1 w metadanych .exe
)
