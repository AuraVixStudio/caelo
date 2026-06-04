import os
import sys
from pathlib import Path

APP_NAME = "AI Studio Pro"
# UWAGA (P3-4): to wersja LEGACY archiwalnej apki customtkinter — używana WYŁĄCZNIE
# przez archive/app.py (tytuł okna). Wersja NOWEGO produktu (Electron + sidecar) ma
# JEDNO źródło prawdy w desktop/package.json i jest raportowana przez grok_core/server.py
# (env GROK_CORE_APP_VERSION ← Electron, z odczytem package.json jako fallbackiem).
APP_VERSION = "1.1"

# --- API Configuration ---
API_BASE = "https://api.x.ai/v1"

# --- paths ---
BASE_DIR = Path(__file__).resolve().parent
IS_FROZEN = getattr(sys, "frozen", False)


def _user_data_dir():
    """Zapisywalny katalog danych użytkownika (używany w wersji spakowanej)."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(base) / APP_NAME


# W wersji spakowanej (.exe) dane trzymamy w profilu użytkownika, bo obok aplikacji
# (Program Files / katalog tymczasowy) nie wolno / nie da się zapisywać.
# W trybie deweloperskim zostają obok źródeł (jak dotąd) — nie ruszamy istniejących danych.
DATA_DIR = _user_data_dir() if IS_FROZEN else BASE_DIR
DATA_DIR.mkdir(parents=True, exist_ok=True)

HISTORY_DIR = DATA_DIR / "generated_history"
HISTORY_DIR.mkdir(exist_ok=True)
CONFIG_FILE = DATA_DIR / "grok_config.json"      # HistoryManager (history/chat/save_path)
SETTINGS_FILE = DATA_DIR / "grok_settings.json"  # API key (fallback) + chat model
AUTH_FILE = DATA_DIR / "grok_auth.json"          # OAuth tokens (do NOT commit)
CHATS_FILE = DATA_DIR / "grok_chats.json"        # conversations
PERMISSIONS_FILE = DATA_DIR / "grok_permissions.json"  # agent allowlist ("Always allow")


def atomic_write_text(path, text: str) -> None:
    """Zapis atomowy tekstu/JSON-a (P1-7): temp w tym samym katalogu + os.replace.
    Czytelnik zawsze widzi albo stary, albo nowy KOMPLETNY plik — brak korupcji
    przy przerwanym zapisie (pliki współdzielone: nowa apka + legacy)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except Exception:
            pass
        raise


def resource_path(rel):
    """Ścieżka do zasobu dołączonego do paczki (działa w dev i w .exe)."""
    base = getattr(sys, "_MEIPASS", str(BASE_DIR))
    return os.path.join(base, rel)


ICON_FILE = resource_path("appicon.ico")

# --- OAuth: logowanie przez konto xAI (SuperGrok / X Premium+), jak grok-cli / Hermes ---
# Endpointy potwierdzone z https://auth.x.ai/.well-known/openid-configuration
OAUTH_AUTHORIZE_URL = "https://auth.x.ai/oauth2/authorize"
OAUTH_TOKEN_URL = "https://auth.x.ai/oauth2/token"
OAUTH_USERINFO_URL = "https://auth.x.ai/oauth2/userinfo"
# Publiczny klient PKCE (bez sekretu) używany przez grok-cli / Hermes Agent.
OAUTH_CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
OAUTH_SCOPES = "openid profile email offline_access grok-cli:access api:access"
OAUTH_REDIRECT_PORT = 56121
OAUTH_REDIRECT_PATH = "/callback"

# --- Modele czatu (lista zapasowa, gdy /v1/models się nie powiedzie) ---
# "Grok Build" = wybór modelu grok-build-0.1.
DEFAULT_CHAT_MODELS = [
    "grok-4.3",
    "grok-4.20-0309-non-reasoning",
    "grok-4.20-0309-reasoning",
    "grok-4.20-multi-agent-0309",
    "grok-build-0.1",
    "grok-4",
    "grok-3",
]
DEFAULT_CHAT_MODEL = "grok-4.3"

# --- Modele obrazu (zakładka Image: generowanie + edycja) ---
# "quality" daje lepszą jakość za wyższą cenę; standard jest tańszy i jest domyślny.
IMAGE_MODELS = [
    "grok-imagine-image",
    "grok-imagine-image-quality",
]
DEFAULT_IMAGE_MODEL = "grok-imagine-image"

# --- Modele wideo (zakładka Video + komendy czatu /video, narzędzie generate_video) ---
# Nowszy model preview daje lepszą jakość; starszy zostawiamy jako wybór wsteczny.
VIDEO_MODELS = [
    "grok-imagine-video-1.5-preview",
    "grok-imagine-video",
]
DEFAULT_VIDEO_MODEL = "grok-imagine-video-1.5-preview"

# --- Voice (TTS / STT / realtime) ---
# Pięć wbudowanych głosów Grok TTS/Voice; zakładka Voice + przyciski w czacie.
VOICE_VOICES = ["eve", "ara", "rex", "sal", "leo"]
DEFAULT_VOICE = "eve"
# Model agenta głosowego realtime (wss://api.x.ai/v1/realtime).
VOICE_REALTIME_MODEL = "grok-voice-latest"
# URL WebSocket realtime wyprowadzony z API_BASE ("https://…/v1" -> "wss://…/v1/realtime").
REALTIME_URL = API_BASE.replace("http", "ws") + "/realtime"

# --- Design Tokens (AI Studio Pro) ---
COLORS = {
    "background": "#0f1323",         # Deep Navy
    "glass": "rgba(255, 255, 255, 0.03)",
    "primary": "#6366f1",            # Indigo 500 (modern accent)
    "primary_hover": "#4f46e5",      # Indigo 600
    "text": "#f8fafc",               # Slate 50
    "text_secondary": "#9aa6bd",     # Soft slate
    "border": "#29334a",             # Softer slate border
    "success": "#10b981",            # Emerald 500
    "error": "#ef4444",              # Red 500
    "surface": "#141a2e",            # Card / panel
    "surface_alt": "#1b2236"         # Elevated surface (bubbles, chips)
}

FONTS = {
    "h1": ("Inter", 28, "bold"),
    "h2": ("Inter", 18, "bold"),
    "body": ("Inter", 13),
    "small": ("Inter", 11, "bold"),
    "mono": ("Consolas", 11)
}

# --- Default Settings ---
ASPECT_RATIOS = ["auto", "1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "2:1", "1:2", "19.5:9", "9:19.5", "20:9", "9:20"]
RESOLUTIONS = ["1k", "2k"]
VIDEO_RESOLUTIONS = ["480p", "720p"]
