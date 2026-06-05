"""System hooków — uogólniony `PermissionGate` (M14-B5).

Deterministyczne, NIEZALEŻNE OD MODELU reguły cyklu życia narzędzi:
  • `pre_tool`  — przed wykonaniem (może ZABLOKOWAĆ; np. `rm -rf`),
  • `post_tool` — po wykonaniu (np. auto-format po zapisie, log audytu),
  • `pre_session` — na starcie tury agenta (np. skrypt setup).

To NIE zastępuje `PermissionGate` (interaktywna zgoda) — działa OBOK i PRZED nim:
hook `pre_tool` blokujący `rm -rf` nie pozwala komendzie nawet dojść do bramki.
Nie rozluźnia NICZEGO (P0-1…P0-8 bez regresji) — tylko dokłada blokady/efekty.

Hooki wbudowane (domyślny config): `block_command` (groźne komendy) + `audit`
(JSONL log wszystkich wywołań). Hooki użytkownika: `run_script` (uruchom program
po pasującym narzędziu) — opt-in (domyślnie wyłączone), bo uruchamiają komendę
(scrubbed env + tree-kill + timeout, jak `run_command`).

Konfiguracja `grok_hooks.json` (atomowo + `load_json_or_backup`); audyt w
`grok_audit.log` (JSONL, z miękką rotacją). UI po angielsku.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import config  # type: ignore

from grok_core.agent.tools import _tree_kill, scrubbed_env

try:
    import regex as _rx  # silnik z timeoutem (jak grep) — wzorce mogą być od usera
    _RX_TIMEOUT = True
except Exception:  # pragma: no cover
    import re as _rx
    _RX_TIMEOUT = False

log = logging.getLogger(__name__)

EVENTS = ("pre_tool", "post_tool", "pre_session")
HOOK_TYPES = ("block_command", "block_path", "audit", "run_script")
AUDIT_MAX_BYTES = 2 * 1024 * 1024   # miękka rotacja logu audytu (→ .1)
SCRIPT_TIMEOUT_S = 60
_MATCH_TIMEOUT_S = 0.5              # budżet per-search (ReDoS) gdy `regex` dostępny

# Domyślny wzorzec „groźnych" komend (intencyjny — uzupełnia odrzucanie metaznaków
# z P0-1; bare `rm -rf workspace` to pojedyncza komenda, którą skaner metaznaków
# przepuszcza). Case-insensitive search po treści komendy.
DEFAULT_DANGEROUS = (
    r"\brm\s+-[a-z]*r[a-z]*f|\brm\s+-[a-z]*f[a-z]*r"   # rm -rf / -fr
    r"|\bdel\s+/[sq]|\brmdir\s+/s"                       # del /s /q, rmdir /s
    r"|\bformat\s|\bmkfs|\bdd\s+if=|\b:\(\)\s*\{"        # format, mkfs, dd, fork bomb
    r"|\bgit\s+push\s+.*--force|\bgit\s+reset\s+--hard"  # destrukcyjny git
    r"|\bshutdown\b|\breboot\b"
)


def _default_hooks() -> list[dict]:
    return [
        {"id": "block-dangerous-commands", "event": "pre_tool", "type": "block_command",
         "enabled": True, "pattern": DEFAULT_DANGEROUS,
         "description": "Block destructive shell commands (rm -rf, format, dd, force push…)."},
        {"id": "audit-all", "event": "post_tool", "type": "audit", "enabled": True,
         "description": "Append every tool call to the audit log."},
    ]


class HookManager:
    def __init__(self, config_path: Optional[Path] = None,
                 audit_path: Optional[Path] = None) -> None:
        self._path = config_path or config.HOOKS_FILE
        self._audit_path = audit_path or config.AUDIT_LOG_FILE
        self._lock = threading.RLock()
        self._audit_lock = threading.Lock()
        self._hooks: list[dict] = []
        self._load()

    # --- trwałość ---
    def _load(self) -> None:
        data = config.load_json_or_backup(self._path, None)
        hooks = data.get("hooks") if isinstance(data, dict) else None
        if hooks is None:
            self._hooks = _default_hooks()  # pierwszy raz / corrupt → wbudowane
        else:
            self._hooks = [h for h in hooks if isinstance(h, dict) and h.get("id")]

    def _save(self) -> None:
        try:
            config.atomic_write_text(self._path,
                                     json.dumps({"hooks": self._hooks}, indent=2, ensure_ascii=False))
        except Exception:  # noqa: BLE001
            log.warning("Failed to save %s", getattr(self._path, "name", self._path), exc_info=True)

    # --- zarządzanie (panel Hooks / F4) ---
    def list_hooks(self) -> list[dict]:
        with self._lock:
            return [dict(h) for h in self._hooks]

    def add_hook(self, cfg: dict) -> dict:
        event = (cfg.get("event") or "").lower()
        htype = (cfg.get("type") or "").lower()
        if event not in EVENTS:
            raise ValueError(f"event must be one of {EVENTS}")
        if htype not in HOOK_TYPES:
            raise ValueError(f"type must be one of {HOOK_TYPES}")
        hid = (cfg.get("id") or f"{htype}-{int(time.time())}").strip()
        clean = {
            "id": hid, "event": event, "type": htype,
            "enabled": bool(cfg.get("enabled", True)),
            "description": cfg.get("description") or "",
        }
        if htype in ("block_command", "block_path"):
            clean["pattern"] = cfg.get("pattern") or ""
        if htype == "run_script":
            cmd = cfg.get("command")
            if isinstance(cmd, str):
                cmd = cmd.split()
            clean["command"] = [str(x) for x in (cmd or [])]
            clean["match_tools"] = list(cfg.get("match_tools") or [])
        with self._lock:
            self._hooks = [h for h in self._hooks if h.get("id") != hid]
            self._hooks.append(clean)
            self._save()
        return clean

    def set_enabled(self, hid: str, enabled: bool) -> dict:
        with self._lock:
            for h in self._hooks:
                if h.get("id") == hid:
                    h["enabled"] = bool(enabled)
                    self._save()
                    return dict(h)
        raise ValueError("unknown hook")

    def remove_hook(self, hid: str) -> bool:
        with self._lock:
            n = len(self._hooks)
            self._hooks = [h for h in self._hooks if h.get("id") != hid]
            if len(self._hooks) != n:
                self._save()
                return True
        return False

    def _enabled(self, event: str) -> list[dict]:
        with self._lock:
            return [dict(h) for h in self._hooks if h.get("event") == event and h.get("enabled")]

    def _audit_active(self) -> bool:
        with self._lock:
            return any(h.get("type") == "audit" and h.get("enabled") for h in self._hooks)

    # --- punkty wejścia (wołane z AgentSession) ---
    def run_pre_session(self, text: str, *, workspace=None, emit=None) -> None:
        for hook in self._enabled("pre_session"):
            if hook["type"] == "run_script":
                self._run_script_hook(hook, {}, workspace, emit)
            elif hook["type"] == "audit":
                self._audit({"action": "session", "text": (text or "")[:200], "hook": hook["id"]})

    def run_pre_tool(self, name: str, args: dict, *, workspace=None, emit=None) -> Optional[str]:
        """Zwraca komunikat blokady (str) gdy któryś hook zablokował, inaczej None."""
        for hook in self._enabled("pre_tool"):
            msg = None
            if hook["type"] == "block_command" and name == "run_command":
                if self._matches(hook.get("pattern") or "", args.get("command") or ""):
                    msg = (hook.get("description") or "Command blocked by a pre-tool hook.")
            elif hook["type"] == "block_path" and name in ("write_file", "edit_file"):
                if self._matches(hook.get("pattern") or "", args.get("path") or ""):
                    msg = (hook.get("description") or "Path blocked by a pre-tool hook.")
            if msg:
                # Blokada jest zdarzeniem bezpieczeństwa → ZAWSZE do audytu (niezależnie
                # od hooka audit) + sygnał do UI.
                self._audit({"action": "blocked", "tool": name, "hook": hook["id"],
                             "detail": msg, "args": _arg_summary(args)})
                if emit:
                    try:
                        emit({"type": "hook", "event": "pre_tool", "hook": hook["id"],
                              "action": "blocked", "tool": name, "detail": msg})
                    except Exception:  # noqa: BLE001
                        pass
                return msg
        return None

    def run_post_tool(self, name: str, args: dict, *, ok: bool, result: str,
                      workspace=None, emit=None) -> None:
        if self._audit_active():
            self._audit({"action": "tool", "tool": name, "ok": bool(ok),
                         "args": _arg_summary(args), "result": (result or "")[:200]})
        for hook in self._enabled("post_tool"):
            if hook["type"] == "run_script":
                match = hook.get("match_tools") or []
                if match and name not in match:
                    continue
                self._run_script_hook(hook, args, workspace, emit)

    # --- helpery ---
    @staticmethod
    def _matches(pattern: str, text: str) -> bool:
        if not pattern:
            return False
        try:
            rx = _rx.compile(pattern, _rx.IGNORECASE)
            kw = {"timeout": _MATCH_TIMEOUT_S} if _RX_TIMEOUT else {}
            return bool(rx.search(text or "", **kw))
        except Exception:  # noqa: BLE001 (zły wzorzec/timeout → nie blokuj fałszywie)
            return False

    def _run_script_hook(self, hook: dict, args: dict, workspace, emit) -> None:
        """Uruchom skrypt hooka (np. formatter). Output → audyt + emit, NIE do modelu.
        Hardening jak run_command: scrubbed env, cwd=workspace, tree-kill, timeout."""
        command = hook.get("command") or []
        if not command:
            return
        # Podstaw {path} z argów narzędzia (typowy przypadek: format zapisanego pliku).
        path = args.get("path") or ""
        argv = [str(part).replace("{path}", path) for part in command]
        cwd = None
        try:
            cwd = str(workspace.root) if workspace is not None else None
        except Exception:  # noqa: BLE001
            cwd = None
        resolved = shutil.which(argv[0]) or argv[0]
        argv[0] = resolved
        if os.name == "nt" and resolved.lower().endswith((".cmd", ".bat")):
            argv = ["cmd", "/c", *argv]
        popen_kwargs: dict = {"env": scrubbed_env()}
        if os.name != "nt":
            popen_kwargs["start_new_session"] = True
        try:
            proc = subprocess.Popen(
                argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", **popen_kwargs)
        except Exception as exc:  # noqa: BLE001
            self._audit({"action": "hook_script", "hook": hook["id"], "ok": False,
                         "detail": f"cannot start: {exc}"})
            return
        try:
            out, _ = proc.communicate(timeout=SCRIPT_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            _tree_kill(proc)
            out = "(timed out)"
        ok = proc.returncode == 0
        self._audit({"action": "hook_script", "hook": hook["id"], "ok": ok,
                     "cmd": " ".join(argv)[:200], "out": (out or "")[:200]})
        if emit:
            try:
                emit({"type": "hook", "event": "post_tool", "hook": hook["id"],
                      "action": "script", "ok": ok})
            except Exception:  # noqa: BLE001
                pass

    # --- audyt ---
    def _audit(self, entry: dict) -> None:
        entry = {"ts": datetime.now().isoformat(timespec="seconds"), **entry}
        line = json.dumps(entry, ensure_ascii=False)
        with self._audit_lock:
            try:
                p = Path(self._audit_path)
                p.parent.mkdir(parents=True, exist_ok=True)
                # miękka rotacja, by log nie rósł bez końca
                if p.exists() and p.stat().st_size > AUDIT_MAX_BYTES:
                    try:
                        os.replace(p, p.with_suffix(p.suffix + ".1"))
                    except OSError:
                        pass
                with open(p, "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            except Exception:  # noqa: BLE001
                log.debug("audit write failed", exc_info=True)

    def audit_tail(self, limit: int = 200) -> list[dict]:
        p = Path(self._audit_path)
        if not p.exists():
            return []
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
        out: list[dict] = []
        for ln in lines[-max(1, limit):]:
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except Exception:  # noqa: BLE001
                continue
        return out

    def clear_audit(self) -> None:
        with self._audit_lock:
            try:
                p = Path(self._audit_path)
                if p.exists():
                    p.unlink()
            except OSError:
                pass


def _arg_summary(args: dict) -> dict:
    """Skrócone argi do audytu (bez ogromnych contentów)."""
    out = {}
    for k, v in (args or {}).items():
        s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str)
        out[k] = (s[:120] + "…") if len(s) > 120 else s
    return out
