import json
import logging
import os
import sys
from pathlib import Path

_log = logging.getLogger("caelo.config")

APP_NAME = "Caelo"
# Nazwa katalogu danych użytkownika w wersji spakowanej (np. %LOCALAPPDATA%\Caelo).
# M15 (rebranding): poprzednio "AI Studio Pro" — migrację starego katalogu i plików
# stanu (grok_* → caelo_*) obsługuje _migrate_legacy_data() poniżej, bez utraty danych.
_LEGACY_APP_NAME = "AI Studio Pro"
# Wersja NOWEGO produktu (Electron + sidecar) ma JEDNO źródło prawdy w
# desktop/package.json i jest raportowana przez caelo_core/server.py
# (env CAELO_CORE_APP_VERSION ← Electron, z odczytem package.json jako fallbackiem).
APP_VERSION = "1.1"

# --- API Configuration ---
API_BASE = "https://api.x.ai/v1"

# --- paths ---
BASE_DIR = Path(__file__).resolve().parent
IS_FROZEN = getattr(sys, "frozen", False)


def _user_data_base() -> Path:
    """Bazowy katalog danych użytkownika per-OS (bez nazwy aplikacji).
    Windows → %LOCALAPPDATA%; macOS → ~/Library/Application Support;
    Linux/inne → $XDG_DATA_HOME (lub ~/.local/share)."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(base)


def _user_data_dir(app_name: str = APP_NAME) -> Path:
    """Zapisywalny katalog danych użytkownika (używany w wersji spakowanej)."""
    return _user_data_base() / app_name


# W wersji spakowanej (.exe) dane trzymamy w profilu użytkownika, bo obok aplikacji
# (Program Files / katalog tymczasowy) nie wolno / nie da się zapisywać.
# W trybie deweloperskim zostają obok źródeł (jak dotąd) — nie ruszamy istniejących danych.
DATA_DIR = _user_data_dir() if IS_FROZEN else BASE_DIR
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _migrate_legacy_data() -> None:
    """M15 (rebranding): przenieś dane sprzed zmiany nazwy bez ich utraty.
      (a) wersja spakowana — stary katalog danych „AI Studio Pro" → „Caelo";
      (b) pliki stanu grok_*.json/db/log → caelo_* (dev: korzeń repo; frozen: po (a)).
    Idempotentne: przenosi tylko, gdy źródło istnieje, a cel jeszcze nie — więc
    bezpiecznie odpala się przy każdym imporcie."""
    # (a) stary katalog (tylko frozen — w dev DATA_DIR = korzeń repo, nie zależy od APP_NAME)
    if IS_FROZEN:
        try:
            old_dir = _user_data_dir(_LEGACY_APP_NAME)
            if old_dir != DATA_DIR and old_dir.is_dir():
                for item in old_dir.iterdir():
                    dest = DATA_DIR / item.name
                    if not dest.exists():
                        try:
                            os.replace(item, dest)
                        except OSError as exc:
                            _log.warning("legacy data-dir migration: %s failed: %s", item.name, exc)
        except Exception as exc:  # noqa: BLE001
            _log.warning("legacy data-dir migration skipped: %s", exc)
    # (b) pliki grok_* → caelo_* (nazwy poniżej obejmują też pliki poboczne SQLite WAL)
    legacy_pairs = [
        ("grok_config.json", "caelo_config.json"),
        ("grok_settings.json", "caelo_settings.json"),
        ("grok_auth.json", "caelo_auth.json"),
        ("grok_chats.json", "caelo_chats.json"),
        ("grok_permissions.json", "caelo_permissions.json"),
        ("grok_mcp.json", "caelo_mcp.json"),
        ("grok_commands.json", "caelo_commands.json"),
        ("grok_hooks.json", "caelo_hooks.json"),
        ("grok_subagents.json", "caelo_subagents.json"),
        ("grok_audit.log", "caelo_audit.log"),
        ("grok_history.db", "caelo_history.db"),
        ("grok_history.db-wal", "caelo_history.db-wal"),
        ("grok_history.db-shm", "caelo_history.db-shm"),
    ]
    for old_name, new_name in legacy_pairs:
        old = DATA_DIR / old_name
        new = DATA_DIR / new_name
        if old.exists() and not new.exists():
            try:
                os.rename(old, new)
            except OSError as exc:
                _log.warning("legacy data migration: %s -> %s failed: %s", old_name, new_name, exc)


_migrate_legacy_data()

HISTORY_DIR = DATA_DIR / "generated_history"
HISTORY_DIR.mkdir(exist_ok=True)
CONFIG_FILE = DATA_DIR / "caelo_config.json"      # HistoryManager (history/chat/save_path)
SETTINGS_FILE = DATA_DIR / "caelo_settings.json"  # API key (fallback) + chat model
AUTH_FILE = DATA_DIR / "caelo_auth.json"          # OAuth tokens (do NOT commit)
CHATS_FILE = DATA_DIR / "caelo_chats.json"        # conversations
PERMISSIONS_FILE = DATA_DIR / "caelo_permissions.json"  # agent allowlist ("Always allow")
# M9-B1: kręgosłup huba — magazyn artefaktów + historii (SQLite + FTS5). Własny plik,
# NIE dotyka caelo_config.json (HistoryManager). Cross-platform (sqlite3 ze stdlib).
HISTORY_DB_FILE = DATA_DIR / "caelo_history.db"   # artifacts + history (caelo_core.history_store)
# M10-B5: lokalne dokumenty „wiedzy projektu" (xAI nie ma vector stores). Per projekt
# podkatalog; dołączane do wiadomości jako input_file na żądanie ("Attach all").
PROJECT_DOCS_DIR = DATA_DIR / "project_docs"
# M14 (rozszerzalność) — własne pliki stanu, wszystkie przez load_json_or_backup +
# atomic_write_text (jak pozostałe). Nie dotykają caelo_config.json (HistoryManager).
MCP_FILE = DATA_DIR / "caelo_mcp.json"            # M14-B1: skonfigurowane serwery MCP
COMMANDS_FILE = DATA_DIR / "caelo_commands.json"  # M14-B4: komendy użytkownika (slash)
HOOKS_FILE = DATA_DIR / "caelo_hooks.json"        # M14-B5: konfiguracja hooków cyklu życia narzędzi
AUDIT_LOG_FILE = DATA_DIR / "caelo_audit.log"     # M14-B5: log audytu wywołań narzędzi (JSONL)
SKILLS_DIR = DATA_DIR / "skills"                 # M14-B6: lokalne pakiety skilli (<name>/SKILL.md)
# M17 (subagenci) — role + limity zespołu (własny plik, jak M14). Atomowe zapisy +
# load_json_or_backup. Worktrees mutujących subagentów = kopie workspace (jak checkpoint
# M13, bez gita) trzymane POZA workspace (nie brudzą drzewa usera); sprzątane po scaleniu/odrzuceniu.
SUBAGENTS_FILE = DATA_DIR / "caelo_subagents.json"  # M17-F4: definicje ról + limity zespołu
WORKTREES_DIR = DATA_DIR / "worktrees"             # M17-B3: izolowane kopie workspace per subagent


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


def load_json_or_backup(path, default=None):
    """Wczytaj JSON z `path`. Brak pliku → `default`. Przy KORUPCJI (niepoprawny
    JSON / błąd odczytu): przenieś uszkodzony plik do `<path>.corrupt` (zachowanie
    danych do ręcznego odzysku), zaloguj i zwróć `default` (P1-11).

    Wspólne dla PIĘCIU czytników stanu (settings/chats/history/auth/permissions),
    by korupcja jednego pliku nie kasowała danych po cichu (wcześniej tylko
    `read_settings` robił backup; pozostałe cztery resetowały do pustych)."""
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        _log.error("Corrupt %s (%s); backing up to .corrupt and using default",
                   path.name, exc)
        try:
            backup = path.with_suffix(path.suffix + ".corrupt")
            os.replace(path, backup)
        except OSError:
            pass
        return default


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
# M12-B1: strumieniowe STT na żywo (wss://api.x.ai/v1/stt). Most sidecara dokłada
# nagłówek Authorization (przeglądarka nie może ustawiać nagłówków WS); partiale +
# finalny transkrypt wracają tą samą ścieżką. Batch idzie przez POST /v1/stt.
STT_STREAM_URL = API_BASE.replace("http", "ws") + "/stt"

# M12-B5: stawki kosztu audio (BYO-key; widoczne dla usera, jak licznik czatu/genjobs).
# STT rozliczane za czas (xAI: batch $0.10/h, stream na żywo $0.20/h). TTS za znaki —
# cena znakowa nie jest publicznie podana, więc TTS_COST_PER_1K_CHARS to STROJALNY
# szacunek (jak placeholdery kosztów w genjobs.py); licznik znaków jest dokładny.
STT_COST_PER_HOUR_BATCH = 0.10
STT_COST_PER_HOUR_STREAM = 0.20
TTS_COST_PER_1K_CHARS = 0.015

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
