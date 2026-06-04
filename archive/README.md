# Archiwum — stara aplikacja customtkinter (FALLBACK)

> **Status: DEPRECATED.** To pierwotna desktopowa aplikacja „AI Studio Pro" napisana
> w customtkinter (Python). Została zastąpiona przez nową architekturę
> **Electron + Python sidecar** w [`../desktop`](../desktop) + [`../grok_core`](../grok_core).
> Trzymamy ją jako **fallback** do czasu pełnej weryfikacji nowej aplikacji z ważnymi
> poświadczeniami xAI; po weryfikacji ten katalog zostanie usunięty (Faza 8 planu).

## Co tu jest
- `app.py` — cała aplikacja (klasa `AIStudioPro`, customtkinter): Chat, Generator, Edit, Video, History, Settings.
- `ui_utils.py` — pomocniki UI (`download_image`, `ResultCard`).
- `run.bat` — szybki start (`python app.py`).
- `build.ps1` + `GrokDesktopApp.spec` + `installer.iss` + `version_info.txt` — stara ścieżka pakowania (PyInstaller onefile + Inno Setup).
- `requirements.txt` — zależności starej apki (customtkinter, Pillow, requests, python-dotenv, tkinterdnd2).
- `DISTRIBUTION.md` — stara instrukcja dystrybucji.

## Uruchomienie
```powershell
cd archive
python app.py        # albo dwuklik run.bat
```
Wymaga interpretera Pythona z zależnościami z `requirements.txt`
(`pip install -r requirements.txt`). Testowany na Python 3.10 (ma customtkinter/Pillow/…).

## WAŻNE: współdzielony rdzeń pozostaje w korzeniu repo
Moduły **`config.py`, `api_manager.py`, `oauth_manager.py`, `chats_manager.py`,
`history_manager.py` NIE są tutaj** — leżą w korzeniu repo, bo reużywa ich również
backend `grok_core`. Dlatego `app.py` na samej górze dokłada korzeń repo do `sys.path`:

```python
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
```

Konsekwencje:
- **Ścieżki danych się nie zmieniły.** `config.DATA_DIR` zależy od położenia `config.py`
  (korzeń repo w trybie dev, `%LOCALAPPDATA%\AI Studio Pro` po spakowaniu), nie od `archive/`.
  Legacy i nowa aplikacja **współdzielą** `grok_settings.json`, `grok_chats.json`,
  `grok_auth.json`, `grok_config.json` (zob. reguły własności plików w pamięci projektu).
- Nie kopiuj rdzenia do `archive/` — rozjechałyby się dane i logika między apkami.

## Stara ścieżka pakowania (opcjonalna)
```powershell
cd archive
.\build.ps1          # make_icon (z ..\make_icon.py) + PyInstaller onefile -> archive\dist\AI Studio Pro.exe
```
`GrokDesktopApp.spec` ma `pathex=['..']`, żeby PyInstaller znalazł współdzielony rdzeń
w korzeniu repo. Nowa, docelowa ścieżka pakowania to electron-builder — patrz
[`../desktop/README.md`](../desktop/README.md) i [`../docs/REBUILD_PLAN.md`](../docs/REBUILD_PLAN.md).
