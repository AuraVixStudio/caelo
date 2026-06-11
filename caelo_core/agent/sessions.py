"""Trwałe sesje agenta kodowania — współdzielone przez tryb headless (M19-B1) i
WebSocket `/agent/stream`.

Sesja = pełna historia rozmowy LLM (role user/assistant/tool) zapisana w
`DATA_DIR/sessions/<id>.json`, dzięki czemu da się ją WZNOWIĆ z kontekstem
(`AgentRunner.resume_session`) albo odtworzyć transkrypt w UI. Format v2:

    {"v":2, "id", "cwd", "project_id", "title", "model",
     "created_at", "updated_at", "history":[ {role, content, ...}, ... ]}

`project_id` (M9-B5) pozwala filtrować listę sesji po projekcie. Loader toleruje
STARY headless format `{"id","cwd","history"}` (brak `v`/pól → project_id=None,
title wyliczony z 1. wiadomości user, czas z mtime pliku).

Zasady projektu: `config.DATA_DIR` czytane LIVE (testy je podmieniają), zapis
ATOMOWY (`config.atomic_write_text`), odczyt korupcjo-tolerancyjny
(`config.load_json_or_backup`), `ensure_ascii=False` (znaki spoza ASCII).
Moduł jest transport-neutralny — NIE importuje `state`/`api_manager` (zero cykli).
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import List, Optional

import config  # type: ignore  # repo-root (sys.path z caelo_core/__init__.py)

log = logging.getLogger(__name__)

# P1-A: walidacja id sesji — bez tego `..\..\caelo_auth` (backslash na Windows)
# albo `../../x` z surowego JSON WS wychodzi z DATA_DIR/sessions i pozwala na
# odczyt/usunięcie/NADPIS dowolnego *.json. Literał jak `_NAME_RX` w skills/manager.py;
# generowane id to `secrets.token_urlsafe(8)` = [A-Za-z0-9_-], więc nic realnego nie odpada.
_SID_RX = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def valid_id(sid) -> bool:
    """True gdy `sid` to bezpieczna nazwa pliku sesji (bez separatorów/traversal)."""
    return isinstance(sid, str) and _SID_RX.match(sid) is not None


def sessions_dir() -> Path:
    return Path(config.DATA_DIR) / "sessions"  # DATA_DIR czytane LIVE


def session_path(sid: str) -> Path:
    # PURE — bez podnoszenia wyjątku (load() nie ma try wokół, headless woła .exists()).
    # Bezpieczeństwo egzekwują load/save/delete przez valid_id().
    return sessions_dir() / f"{sid}.json"


def _content_text(content) -> str:
    """Tekst wiadomości: string wprost albo sklejone części tekstowe (multimodal)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            p.get("text", "") for p in content
            if isinstance(p, dict) and p.get("type") == "text" and p.get("text")
        )
    return ""


def title_from_history(history: list) -> Optional[str]:
    """Tytuł sesji z pierwszej wiadomości użytkownika (jak `titleFromText` w czacie)."""
    for m in history or []:
        if isinstance(m, dict) and m.get("role") == "user":
            t = _content_text(m.get("content")).strip().replace("\n", " ")
            if t:
                return (t[:60] + "…") if len(t) > 60 else t
    return None


def _message_count(history: list) -> int:
    """Liczba wiadomości rozmowy (user/assistant) — bez wpisów `tool` i system."""
    return sum(1 for m in history
               if isinstance(m, dict) and m.get("role") in ("user", "assistant"))


def load(sid: str) -> dict:
    """Znormalizowany dict sesji (z kluczem `history`); `{}` gdy brak/uszkodzona.

    Toleruje stary headless format — uzupełnia brakujące pola (project_id=None,
    title z historii, czasy z mtime). Nie podbija `v` przy odczycie (dopiero `save`)."""
    if not valid_id(sid):  # P1-A: spreparowany id -> brak sesji (clean miss, nie 500)
        return {}
    p = session_path(sid)
    if not p.exists():
        return {}
    data = config.load_json_or_backup(p, {}) or {}
    hist = data.get("history")
    history = hist if isinstance(hist, list) else []
    try:
        mtime = int(p.stat().st_mtime)
    except OSError:
        mtime = 0
    return {
        "v": data.get("v") or 1,
        "id": data.get("id") or sid,
        "cwd": data.get("cwd") or "",
        "project_id": data.get("project_id"),
        "title": data.get("title") or title_from_history(history),
        "model": data.get("model"),
        "created_at": data.get("created_at") or mtime,
        "updated_at": data.get("updated_at") or mtime,
        "history": history,
    }


def load_history(sid: str) -> list:
    """Sama historia rozmowy (lista wiadomości) — `[]` gdy brak. Wygodne dla
    headless/`AgentRunner.resume_session`, które potrzebują tylko `history`."""
    return load(sid).get("history") or []


def save(*, id: str, cwd: str, history: list, project_id: Optional[str] = None,
         model: Optional[str] = None, title: Optional[str] = None,
         created_at: Optional[int] = None) -> None:
    """Zapisz sesję (v2) atomowo. Przy istniejącym pliku ZACHOWUJE `created_at`
    i wcześniejsze `project_id`/`title`/`model` (gdy nowe nie podane), ustawia
    `updated_at = teraz`. Best-effort — błąd logowany i połykany (jak headless)."""
    if not valid_id(id):  # P1-A: nie persistuj pod spreparowaną ścieżką (resume->_persist_session)
        log.warning("Refusing to save agent session with invalid id")
        return
    try:
        d = sessions_dir()
        d.mkdir(parents=True, exist_ok=True)
        p = session_path(id)
        existing = config.load_json_or_backup(p, {}) if p.exists() else {}
        existing = existing if isinstance(existing, dict) else {}
        now = int(time.time())
        payload = {
            "v": 2,
            "id": id,
            "cwd": cwd,
            "project_id": project_id if project_id is not None else existing.get("project_id"),
            "title": title or title_from_history(history) or existing.get("title"),
            "model": model or existing.get("model"),
            "created_at": created_at or existing.get("created_at") or now,
            "updated_at": now,
            "history": history,
        }
        config.atomic_write_text(p, json.dumps(payload, ensure_ascii=False))
    except Exception:  # noqa: BLE001
        log.warning("Could not persist agent session %s", id, exc_info=True)


def list_meta(project_id: Optional[str] = None) -> List[dict]:
    """Metadane wszystkich sesji (BEZ `history`), najnowsze pierwsze. Z `project_id`
    filtruje po projekcie (M9-B5); `None` = wszystkie (też sesje bez projektu)."""
    d = sessions_dir()
    if not d.exists():
        return []
    out: List[dict] = []
    for f in d.glob("*.json"):
        data = config.load_json_or_backup(f, {}) or {}
        if not isinstance(data, dict):
            continue
        hist = data.get("history")
        history = hist if isinstance(hist, list) else []
        pid = data.get("project_id")
        if project_id is not None and pid != project_id:
            continue
        try:
            mtime = int(f.stat().st_mtime)
        except OSError:
            mtime = 0
        out.append({
            "id": data.get("id") or f.stem,
            "title": data.get("title") or title_from_history(history) or "Untitled session",
            "project_id": pid,
            "cwd": data.get("cwd") or "",
            "model": data.get("model"),
            "created_at": data.get("created_at") or mtime,
            "updated_at": data.get("updated_at") or mtime,
            "message_count": _message_count(history),
        })
    out.sort(key=lambda m: m.get("updated_at") or 0, reverse=True)
    return out


def delete(sid: str) -> bool:
    """Usuń plik sesji. True gdy usunięto, False gdy nie istniał / błąd."""
    if not valid_id(sid):  # P1-A: spreparowany id -> brak usunięcia
        return False
    p = session_path(sid)
    try:
        if p.exists():
            p.unlink()
            return True
    except OSError:
        log.warning("Could not delete agent session %s", sid, exc_info=True)
    return False


def latest() -> Optional[str]:
    """Id najświeższej sesji (po mtime) lub None."""
    d = sessions_dir()
    if not d.exists():
        return None
    files = sorted(d.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    return files[0].stem if files else None
