import itertools
import json
import logging
import os
import sys
import time
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
#
# P1-E: override CAELO_CORE_DATA_DIR ma PIERWSZEŃSTWO przed obiema gałęziami — self-checki
# (api_smoke/handshake_check/sidecar_smoke) ustawiają go na katalog tymczasowy, by NIE
# chodzić po realnym DATA_DIR użytkownika (dev = korzeń repo; `DELETE /genjobs` w smoke
# kasowałby realną listę zadań). Electron (main/index.ts) i caelo_core.spec NIE ustawiają
# tej zmiennej → w produkcji ścieżka jest nietknięta. Wszystkie stałe pochodne (HISTORY_DIR,
# SETTINGS_FILE, HISTORY_DB_FILE, …) liczą się PONIŻEJ z DATA_DIR, więc dziedziczą override.
_DATA_DIR_OVERRIDE = os.environ.get("CAELO_CORE_DATA_DIR", "").strip()
if _DATA_DIR_OVERRIDE:
    DATA_DIR = Path(_DATA_DIR_OVERRIDE)
else:
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
# M16 (społeczność / marketplace) — warstwa dystrybucji nad M14. Pakiety (.caelopkg =
# ZIP z manifest.json) skilli/komend/konfiguracji-MCP/szablonów: eksport, bezpieczny
# import za zgodą (declared permissions + integralność sha256), registry oparte o git.
# Własny plik rejestru zainstalowanych pakietów (atomowo + load_json_or_backup, jak M14)
# i katalog zainstalowanych szablonów projektów (wbudowane leżą w pakiecie, read-only).
PACKAGES_FILE = DATA_DIR / "caelo_packages.json"  # M16-1: rejestr zainstalowanych pakietów
TEMPLATES_DIR = DATA_DIR / "templates"            # M16-5: zainstalowane szablony projektów (<id>/)
# Domyślny indeks registry społeczności (git/GitHub, zero infrastruktury). Surowy JSON
# z listą pakietów + linkami do manifestów/źródeł. Nadpisywalny w UI (pole „registry URL").
PACKAGES_REGISTRY_URL = (
    "https://raw.githubusercontent.com/grooverpty/caelo-packages/main/registry.json"
)
# Twarde limity importu (anty-zip-bomba / anty-OOM, w duchu MAX_MEDIA_BYTES). Pakiet to
# tekstowe artefakty (skille/komendy/szablony) — nie potrzebuje być duży.
MAX_PACKAGE_BYTES = 8 * 1024 * 1024        # rozmiar pliku .caelopkg
MAX_PACKAGE_UNPACKED_BYTES = 32 * 1024 * 1024  # suma rozpakowanych payloadów (zip-bomba)
MAX_PACKAGE_FILES = 512                     # liczba plików w payloadzie

# M19-Tier2 B5 (interop ekosystemu Claude Code / Grok CLI) — odkrywamy konfigurację z
# plików ekosystemu, by istniejące projekty „po prostu działały" (format = schemat
# Anthropica). Import NIC nie uruchamia: serwery MCP z tych plików wchodzą WYŁĄCZONE
# (reżim M16); start = osobna, gejtowana akcja. `~/.claude.json` = globalny plik MCP
# użytkownika (klucz `mcpServers`); projektowy `<ws>/.mcp.json` czytany per workspace.
CLAUDE_JSON = Path.home() / ".claude.json"  # M19-B5 §1.2: globalna konfiguracja MCP (mcpServers)
CLAUDE_HOME = Path.home() / ".claude"       # M19-B5 §1.3: globalny katalog ekosystemu (skills/)

# M19-B8 (pamięć hybrydowa: FTS5 + embeddingi) — semantyczny recall ponad pełnotekstowy
# FTS5 + wstrzyknięcie najtrafniejszych wspomnień na 1. turze agenta. Embeddingi liczy
# cienki klient xAI (`caelo_core/embeddings.py`), wektory leżą w `caelo_history.db`
# (tabela `event_embeddings`), KNN to brute-force cosine w Pythonie (bez `sqlite-vec`/
# torch — „tylko Grok", bez ciężkich zależności). **Opt-in** (koszt embeddingów +
# prywatność): domyślnie OFF; włącz przez env `CAELO_MEMORY=1` lub headless flagą.
MEMORY_ENABLED = os.environ.get("CAELO_MEMORY", "").strip().lower() in ("1", "true", "yes", "on")
MEMORY_MAX_RESULTS = 5            # ile wspomnień wstrzykiwanych na 1. turze
MEMORY_MIN_SCORE = 0.55           # próg podobieństwa cosinusowego (0..1) dla recall/inject
EMBED_MODEL = "embedding-beta-3-small"  # model embeddingów xAI (wymiary ~1024; live = spike §9)

# M19-B7 (sandbox OS-kernel) — DODATKOWA warstwa nad istniejącą fosą (`Workspace.resolve`
# + `scrubbed_env` + tree-kill): izolacja procesów potomnych `run_command`/MCP/LSP na
# poziomie jądra (Linux `bwrap`, macOS `sandbox-exec`; Windows best-effort no-op). **Opt-in,
# domyślnie OFF** — `off` nie zmienia zachowania. Profil globalny z env `CAELO_SANDBOX`
# (off|workspace|read-only|strict), nadpisywalny przez `DATA_DIR/sandbox.json` (globalny) i
# `<ws>/.caelo/sandbox.json` (projekt; jak `lsp.json`/`permissions.json` — JSON, NIE TOML,
# by trzymać konwencję repo: `load_json_or_backup`). Ścieżki wrażliwe (`~/.ssh`/`~/.aws`/
# `~/.gnupg`/`caelo_auth.json`) są ZAWSZE na deny-liście.
SANDBOX_PROFILE = os.environ.get("CAELO_SANDBOX", "off").strip().lower() or "off"

# M19-B10 (auto-compact kontekstu agenta) — gdy historia tury przekroczy próg znaków,
# najstarsze ZAMKNIĘTE tury (granica = wiadomość `user`) są zwijane w jeden blok-
# streszczenie (deterministycznie, BEZ sieci — digest skrócony), zachowując balans
# tool_call↔tool (kontrakt xAI). Chroni długie sesje (headless `-c`, ACP, wielotura)
# przed nieograniczonym wzrostem kontekstu/kosztu. **Opt-in, domyślnie OFF** — `off`
# nie zmienia zachowania. Włącz env `CAELO_AUTOCOMPACT=1`.
AGENT_AUTOCOMPACT = os.environ.get("CAELO_AUTOCOMPACT", "").strip().lower() in ("1", "true", "yes", "on")
AGENT_COMPACT_THRESHOLD_CHARS = 48000  # próg rozmiaru historii (znaki) uruchamiający zwijanie

# M19-B12 (realne git worktree dla mutujących subagentów) — OPCJA obok kopii katalogu
# (M17): gdy workspace jest top-level repo git, użyj `git worktree add` (szybsze, naturalny
# `git diff`, respektuje .gitignore). **Opt-in, domyślnie OFF** — kopia zostaje domyślna
# (działa też poza repo). Włącz env `CAELO_GIT_WORKTREE=1` lub headless flagą `--worktree`.
AGENT_GIT_WORKTREE = os.environ.get("CAELO_GIT_WORKTREE", "").strip().lower() in ("1", "true", "yes", "on")

# M19-B13 (web tools w agencie) — narzędzie `web_fetch` (pobranie treści URL) dla agenta
# kodowania. Egress sieciowy POD BRAMKĄ (mutujące: approval w WS / reguła `WebFetch(...)`
# z B4 / fail-closed w headless) + https-only + opcjonalna twarda allowlista hostów +
# cap rozmiaru + SSRF-guard (blok loopback/sieci prywatnych). **Opt-in, domyślnie OFF**
# (jak inne M19) — narzędzie UKRYTE przed modelem, gdy wyłączone. Włącz `CAELO_WEB_FETCH=1`.
# `CAELO_WEB_FETCH_DOMAINS` (CSV hostów) = dodatkowa twarda restrykcja na poziomie
# egzekutora (pusta = bez restrykcji tam; decyduje bramka/reguły). Pokrewne `web_search`
# (live search BEZ bramki) jest niżej — Faza-G/TOP1 (M19-Tier3 §11 odkładał je za prostym,
# gated `web_fetch`; teraz wdrożone).
WEB_FETCH_ENABLED = os.environ.get("CAELO_WEB_FETCH", "").strip().lower() in ("1", "true", "yes", "on")
WEB_FETCH_ALLOW_DOMAINS = [d.strip().lower() for d in
                          os.environ.get("CAELO_WEB_FETCH_DOMAINS", "").split(",") if d.strip()]
WEB_FETCH_MAX_BYTES = 512 * 1024   # cap pobranej treści (bajty przed dekodowaniem)
WEB_FETCH_TIMEOUT_S = 20           # timeout pojedynczego pobrania (sekundy)

# Faza-G / TOP1 (web_search w agencie) — narzędzie `web_search` dla agenta kodowania:
# live web/X search REUŻYWAJĄCE `responses_client` (te same serwerowe narzędzia
# `web_search`/`x_search`, których używa czat M10). READONLY → BEZ bramki (jak `lsp`): tylko
# pobiera i CYTUJE, nic nie mutuje. Zwraca syntezę + listę „Sources" (cytowania) do modelu.
# Płatne wywołanie xAI (BYO-key), ale model woła je tylko na żądanie zadania (świeże info /
# wersje API / błędy). **Domyślnie ON** (jak `CHAT_MEDIA_TOOLS` — koszt = klucz usera);
# wyłącz `CAELO_WEB_SEARCH=0`. Gdy off — narzędzie UKRYTE przed modelem.
WEB_SEARCH_ENABLED = os.environ.get("CAELO_WEB_SEARCH", "1").strip().lower() in ("1", "true", "yes", "on")
WEB_SEARCH_MAX_SOURCES = 8         # ile cytowań skleić w listę „Sources" zwracaną modelowi

# M20: narzędzia generowania mediów w czacie (image/video) jako function-calling.
# Grok robi to natywnie, ale Responses API NIE ma serwerowego image-gen → własne
# narzędzia (reuse backend_media/genjobs). Domyślnie **ON** (model woła je tylko na
# żądanie usera; koszt = BYO-key). Wyłącz przez `CAELO_CHAT_MEDIA=0`.
CHAT_MEDIA_TOOLS = os.environ.get("CAELO_CHAT_MEDIA", "1").strip().lower() in ("1", "true", "yes", "on")


_atomic_tmp_seq = itertools.count()


def atomic_write_text(path, text: str) -> None:
    """Zapis atomowy tekstu/JSON-a (P1-7): temp w tym samym katalogu + os.replace.
    Czytelnik zawsze widzi albo stary, albo nowy KOMPLETNY plik — brak korupcji
    przy przerwanym zapisie (pliki współdzielone: nowa apka + legacy).

    Nazwa temp jest UNIKALNA (pid + licznik) — stały `<name>.tmp` kolidował przy
    równoległych zapisach tego samego pliku (Windows: `PermissionError` na .tmp
    zablokowanym przez drugi wątek/proces; obserwowane na caelo_settings.json.tmp)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Retry z backoffem: na Windows `os.replace` do wspolnego celu (albo zapis .tmp)
    # potrafi dac przejsciowy `PermissionError`/sharing violation, gdy inny watek/
    # proces chwilowo trzyma plik (obserwowane na caelo_settings.json). Przejsciowe
    # -> ponow; trwale (np. brak uprawnien do katalogu) -> rzuc po wyczerpaniu prob.
    last_exc: Exception | None = None
    for attempt in range(6):
        tmp = path.parent / f"{path.name}.tmp.{os.getpid()}.{next(_atomic_tmp_seq)}"
        try:
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, path)
            return
        except OSError as exc:
            last_exc = exc
            try:
                tmp.unlink()
            except OSError:
                pass
            time.sleep(0.04 * (attempt + 1))
    raise last_exc if last_exc else OSError(f"atomic_write_text failed: {path}")


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
    # S31-e: oddziel BŁĄD ODCZYTU (OSError: brak uprawnień, sharing violation na Windows,
    # plik trzymany przez antywirusa, przejściowe I/O) od KORUPCJI (niepoprawny JSON).
    # Wcześniej blankietowy `except Exception` przenosił ZDROWY plik do `.corrupt` przy
    # przejściowym OSError — a tu żyją tokeny OAuth / klucz API, więc user był po cichu
    # wylogowywany / tracił config. OSError → default BEZ ruszania pliku.
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        _log.warning("Could not read %s (%s); using default (file left intact)",
                     path.name, exc)
        return default
    try:
        return json.loads(text)
    except ValueError as exc:  # JSONDecodeError/UnicodeDecodeError = faktyczna korupcja
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

# Przybliżony rozmiar okna kontekstowego modelu (do miernika UI agenta). To SZACUNEK
# (xAI nie udostępnia tego stabilnie per-model) — używany tylko do paska „X/Y (Z%)".
_CONTEXT_WINDOW_DEFAULT = 256_000


def context_window_for(model: str) -> int:
    """Przybliżony rozmiar okna kontekstowego (tokeny) dla miernika UI. Szacunek —
    rodzina grok-3 ma mniejsze okno; grok-4.x / grok-build / nieznane → duże okno."""
    m = (model or "").lower()
    if m.startswith("grok-3"):
        return 131_072
    return _CONTEXT_WINDOW_DEFAULT

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
# Model wideo dla CZATU (narzedzie generate_video). Celowo BAZOWY, nie preview:
# 1.5-preview ma mniej mozliwosci (np. brak edit/extend) niz bazowy grok-imagine-video.
# Panel Video nadal pozwala wybrac dowolny model (domyslnie 1.5-preview).
# Override: env CAELO_CHAT_VIDEO_MODEL.
CHAT_VIDEO_MODEL = (os.environ.get("CAELO_CHAT_VIDEO_MODEL", "").strip()
                    or "grok-imagine-video")

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
