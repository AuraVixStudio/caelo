# Distribution — AI Studio Pro

> **Uwaga:** ten dokument dotyczy **aplikacji legacy** (customtkinter, `app.py`).
> Pakowanie nowej aplikacji Electron + Python sidecar to **Faza 7** (PyInstaller
> onedir sidecar + electron-builder NSIS) — zob. [`docs/REBUILD_PLAN.md`](docs/REBUILD_PLAN.md).

How to package the app into a normal Windows program (`.exe`), and optionally an installer.

## Requirements
- Windows + Python 3.10/3.11
- Dependencies from `requirements.txt` (installed automatically by the build script)

## 1. Build the .exe (one command)
```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
```
This will:
1. install dependencies,
2. generate the app icon (`appicon.ico` via `make_icon.py`),
3. build with PyInstaller using `GrokDesktopApp.spec` (one-folder, windowed).

**Output:** `dist\AI Studio Pro.exe` — a **single portable file**.
Copy this one `.exe` anywhere (Desktop, USB stick, another PC) and double‑click — no other files needed. First launch is a few seconds slower (it self‑extracts to a temp folder).

## 2. (Optional) Build a real installer
For a Start‑Menu entry, desktop shortcut and uninstaller:
1. Install **Inno Setup**: https://jrsoftware.org/isdl.php
2. Compile `installer.iss` (open it in Inno Setup → Compile, or `iscc installer.iss`).
3. **Output:** `Output\AI-Studio-Pro-Setup.exe` — a standard Windows installer.

## Where user data is stored
When run as the packaged `.exe`, all user data lives in the user profile (writable, survives updates):
```
%LOCALAPPDATA%\AI Studio Pro\
  grok_chats.json      (conversations)
  grok_settings.json   (API key fallback + chat model)
  grok_auth.json       (OAuth tokens — keep private)
  grok_config.json     (media history / output folder)
  generated_history\   (saved images/videos)
```
When run from source (`python app.py`), data stays next to the source files (unchanged).

## Notes
- **Sign‑in**: the app uses xAI account OAuth (SuperGrok / X Premium+); no API key required. An API key field remains as a fallback.
- **SmartScreen**: an unsigned `.exe`/installer may trigger a Windows SmartScreen warning ("More info → Run anyway"). To remove it, sign the binary with a code‑signing certificate.
- **Antivirus**: PyInstaller one‑folder builds (UPX disabled) minimize false positives.
- **Drag & drop** needs `tkinterdnd2` (bundled automatically in the build).
