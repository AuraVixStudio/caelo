# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec sidecara caelo-core (tryb ONEDIR — szybki start jako sidecar).

Budowa (z venv zawierającego zależności backendu, patrz build_sidecar.ps1):
    python -m PyInstaller --noconfirm --clean caelo_core.spec
Wynik: dist\\caelo-core\\caelo-core.exe  (+ katalog _internal/ z bibliotekami).

Electron pakuje cały katalog dist\\caelo-core jako `extraResources` (resources/caelo-core)
i uruchamia caelo-core.exe zamiast `python -m caelo_core` (patrz desktop/src/main/index.ts).

ONEDIR (nie ONEFILE) celowo: brak rozpakowywania do tempa przy każdym starcie =
szybszy start i brak migotania, co ma znaczenie dla nadzorowanego sidecara.
"""
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

datas, binaries, hiddenimports = [], [], []


def _collect(pkg):
    """collect_all odporny na brak opcjonalnego pakietu."""
    try:
        d, b, h = collect_all(pkg)
        datas.extend(d)
        binaries.extend(b)
        hiddenimports.extend(h)
    except Exception as exc:  # noqa: BLE001
        print(f"[caelo_core.spec] collect_all({pkg!r}) pominięte: {exc}")


# Stos serwera: uvicorn + FastAPI + Starlette + (an)io + pydantic + websockets.
for pkg in ("uvicorn", "fastapi", "starlette", "anyio", "pydantic", "websockets"):
    _collect(pkg)

# uvicorn ładuje implementacje protokołów dynamicznie — dociągnij całość pakietu.
hiddenimports += collect_submodules("uvicorn")
hiddenimports += [
    "h11", "httptools", "wsproto", "sniffio", "click", "certifi", "idna",
    "urllib3", "charset_normalizer", "pydantic_core",
    "regex",  # silnik grep z timeoutem (P0-3); import w tools.py jest w try/except
]

# Pakiet sidecara + jego podmoduły (trasy importowane są dynamicznie w server.py).
hiddenimports += collect_submodules("caelo_core")

# M14-B6: wbudowane skille (SKILL.md) to pliki DANYCH — collect_submodules ich nie
# bierze. BUILTIN_DIR rozwiązuje się względem __file__ (→ <bundle>/caelo_core/skills/builtin).
datas += collect_data_files("caelo_core", includes=["skills/builtin/**/*.md"])

# Legacy moduły z korzenia repo: caelo_core/__init__.py dokłada korzeń do sys.path
# DOPIERO w czasie działania, więc statyczna analiza PyInstallera ich nie widzi —
# deklarujemy je jawnie (pathex=['.'] pozwala je znaleźć przy budowie).
hiddenimports += [
    "config", "api_manager", "oauth_manager", "chats_manager", "history_manager",
]
# Zależności tych modułów (klient xAI + obrazy).
hiddenimports += ["requests", "PIL", "PIL.Image"]

# Terminal (WS /terminal) — opcjonalny pywinpty (pakiet importowany jako `winpty`).
_collect("winpty")


a = Analysis(
    ["caelo_core_sidecar.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Backend nie ma GUI — nie wciągaj toolkitu okienkowego legacy app.
        "tkinter", "customtkinter", "tkinterdnd2",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,          # ONEDIR: binaria/dane idą do COLLECT, nie do .exe
    name="caelo-core",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                      # UPX off — mniej fałszywych alarmów AV
    console=True,                   # potrzebny stdout (handshake); okno ukrywa Electron (windowsHide)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="caelo-core",
)
