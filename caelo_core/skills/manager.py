"""Menedżer skilli (M14-B6): odkrywanie, włączanie, tworzenie, wstrzykiwanie.

Źródła (rosnące pierwszeństwo nadpisań): wbudowane (`builtin/`, pakowane) <
użytkownika (`config.SKILLS_DIR`) < **M19-B5 §1.3 interop**: globalne
`~/.claude/skills` < projektowe `<ws>/.claude/skills` i `<ws>/.grok/skills`. Skill
o tym samym id w źródle wyżej w hierarchii NADPISUJE niższe. Format `SKILL.md`
jest identyczny z Claude Code / Grok CLI, więc istniejące skille „po prostu działają".

Stan „enabled" trzymany centralnie w `SKILLS_DIR/_state.json` (po id, niezależnie od
źródła). Włączone skille → `injected_text()` (cap rozmiaru), wstrzykiwane do system
promptu agenta. Brak/uszkodzony/za duży SKILL.md tolerowany (skip-with-log).
**Pliki interop są tylko CZYTANE** — nigdy nie modyfikujemy cudzych katalogów (tworzenie/
usuwanie działa wyłącznie w `SKILLS_DIR`).
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import threading
from pathlib import Path
from typing import Optional

import config  # type: ignore

from caelo_core.markdown_meta import parse_frontmatter

log = logging.getLogger(__name__)

BUILTIN_DIR = Path(__file__).resolve().parent / "builtin"
SKILL_FILE = "SKILL.md"
MAX_SKILL_BYTES = 16 * 1024          # cap treści jednego skilla (kontekst)
MAX_INJECT_BYTES = 48 * 1024         # cap łącznej wstrzykniętej treści
_NAME_RX = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

SKILL_TEMPLATES = {
    "blank": ("New skill", "Describe when this skill applies.",
              "## Steps\n\n1. …\n2. …\n"),
    "workflow": ("New workflow", "A reusable, multi-step workflow.",
                 "## Steps\n\n1. …\n2. …\n"),
    "checklist": ("New checklist", "A checklist to run through when this applies.",
                  "## Checklist\n\n- [ ] …\n- [ ] …\n"),
}


class SkillManager:
    def __init__(self, user_dir: Optional[Path] = None, *,
                 workspace_root: Optional[Path] = None,
                 claude_home: Optional[Path] = None) -> None:
        self._user_dir = Path(user_dir) if user_dir else config.SKILLS_DIR
        self._state_path = self._user_dir / "_state.json"
        # M19-B5 §1.3 (interop): dodatkowe ŹRÓDŁA odkrywania (poza builtin + user_dir).
        # Jawne parametry — domyślnie None = brak interopu (czyste zachowanie testów;
        # Backend wstrzykuje realne `config.CLAUDE_HOME` + korzeń workspace).
        self._workspace_root = Path(workspace_root) if workspace_root else None
        self._claude_home = Path(claude_home) if claude_home else None
        self._lock = threading.RLock()

    @property
    def workspace_root(self) -> Optional[Path]:
        """Korzeń workspace, dla którego zbudowano menedżera (None = brak/global-only).
        Backend porównuje go, by przebudować menedżera przy zmianie workspace (jak LSP)."""
        return self._workspace_root

    # --- stan „enabled" ---
    def _state(self) -> dict:
        data = config.load_json_or_backup(self._state_path, {}) or {}
        return data if isinstance(data, dict) else {}

    def _enabled_set(self) -> set[str]:
        return set(self._state().get("enabled") or [])

    def _save_state(self, enabled: set[str]) -> None:
        try:
            self._user_dir.mkdir(parents=True, exist_ok=True)
            config.atomic_write_text(self._state_path,
                                     json.dumps({"enabled": sorted(enabled)}, indent=2))
        except Exception:  # noqa: BLE001
            log.warning("Failed to save skills state", exc_info=True)

    # --- odkrywanie ---
    def _read_skill(self, folder: Path, *, builtin: bool,
                    source: str = "user") -> Optional[dict]:
        sf = folder / SKILL_FILE
        if not sf.is_file():
            return None
        try:
            text = sf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        meta, body = parse_frontmatter(text)
        name = (meta.get("name") or folder.name).strip()
        if not _NAME_RX.match(folder.name):
            return None
        triggers = meta.get("triggers")
        if isinstance(triggers, str):
            triggers = [t.strip() for t in triggers.split(",") if t.strip()]
        return {
            "id": folder.name,
            "name": name,
            "description": meta.get("description") or "",
            "triggers": triggers or [],
            "builtin": builtin,
            # B5 §1.3: skąd przyszedł skill — "builtin"/"user"/"claude-global"/
            # "claude-project"/"grok-project". Tylko "user" jest usuwalny/edytowalny.
            "source": source,
            "body": body,
            "path": str(folder),
            "has_resources": any(p.name != SKILL_FILE for p in folder.iterdir()),
        }

    def _scan(self, base: Path, *, builtin: bool, source: str = "user") -> dict[str, dict]:
        out: dict[str, dict] = {}
        try:
            if not base.is_dir():
                return out
            for folder in sorted(base.iterdir()):
                if not folder.is_dir() or folder.name.startswith((".", "_")):
                    continue
                sk = self._read_skill(folder, builtin=builtin, source=source)
                if sk:
                    out[sk["id"]] = sk
        except Exception:  # noqa: BLE001
            log.warning("Failed to scan skills in %s", base, exc_info=True)
        return out

    def _all(self) -> dict[str, dict]:
        # Kolejność = rosnące pierwszeństwo (każdy update nadpisuje poprzednie po id):
        # builtin < user < claude-global < projekt (.claude < .grok).
        merged = self._scan(BUILTIN_DIR, builtin=True, source="builtin")
        merged.update(self._scan(self._user_dir, builtin=False, source="user"))
        if self._claude_home is not None:  # B5 §1.3: globalny ekosystem
            merged.update(self._scan(self._claude_home / "skills",
                                     builtin=False, source="claude-global"))
        if self._workspace_root is not None:  # B5 §1.3: ekosystem projektu
            merged.update(self._scan(self._workspace_root / ".claude" / "skills",
                                     builtin=False, source="claude-project"))
            merged.update(self._scan(self._workspace_root / ".grok" / "skills",
                                     builtin=False, source="grok-project"))
        enabled = self._enabled_set()
        for sk in merged.values():
            sk["enabled"] = sk["id"] in enabled
        return merged

    def list_skills(self) -> list[dict]:
        """Lista skilli BEZ ciała (lekka) — do biblioteki (F5)."""
        with self._lock:
            return [self._public(sk) for sk in
                    sorted(self._all().values(), key=lambda s: s["id"])]

    @staticmethod
    def _public(sk: dict) -> dict:
        out = {k: sk[k] for k in ("id", "name", "description", "triggers", "builtin",
                                  "enabled", "has_resources")}
        out["source"] = sk.get("source") or "user"  # B5 §1.3: builtin/user/claude-*/grok-*
        out["bytes"] = len(sk.get("body") or "")
        return out

    def get_skill(self, sid: str) -> Optional[dict]:
        with self._lock:
            sk = self._all().get(sid)
            if sk is None:
                return None
            body = sk.get("body") or ""
            if len(body) > MAX_SKILL_BYTES:
                body = body[:MAX_SKILL_BYTES] + "\n… (truncated)"
            out = self._public(sk)
            out["body"] = body
            return out

    def set_enabled(self, sid: str, enabled: bool) -> dict:
        with self._lock:
            if sid not in self._all():
                raise ValueError("unknown skill")
            cur = self._enabled_set()
            if enabled:
                cur.add(sid)
            else:
                cur.discard(sid)
            self._save_state(cur)
            sk = self._all()[sid]
        return self._public(sk)

    # --- wstrzykiwanie do kontekstu (agent) ---
    def injected_text(self, ids: Optional[list[str]] = None) -> str:
        """Złóż instrukcje WŁĄCZONYCH skilli (albo jawnie wskazanych `ids`) do
        wstrzyknięcia w system prompt. Cap łączny + per-skill (kontekst)."""
        with self._lock:
            alls = self._all()
            chosen = ([alls[i] for i in ids if i in alls] if ids
                      else [s for s in alls.values() if s["enabled"]])
        if not chosen:
            return ""
        parts: list[str] = []
        total = 0
        for sk in sorted(chosen, key=lambda s: s["id"]):
            body = (sk.get("body") or "").strip()
            if len(body) > MAX_SKILL_BYTES:
                body = body[:MAX_SKILL_BYTES] + "\n… (truncated)"
            block = f"### Skill: {sk['name']}\n{body}"
            if total + len(block) > MAX_INJECT_BYTES:
                break
            parts.append(block)
            total += len(block)
        if not parts:
            return ""
        return ("--- Active skills (reusable workflows; follow when relevant) ---\n\n"
                + "\n\n".join(parts))

    # --- tworzenie / usuwanie (użytkownika) ---
    def create_skill(self, sid: str, *, template: str = "blank",
                     name: str = "", description: str = "") -> dict:
        sid = (sid or "").strip()
        if not _NAME_RX.match(sid):
            raise ValueError("skill id must match [a-zA-Z0-9_-]{1,64}")
        tmpl = SKILL_TEMPLATES.get(template, SKILL_TEMPLATES["blank"])
        title = name or tmpl[0]
        desc = description or tmpl[1]
        body = tmpl[2]
        content = (f"---\nname: {title}\ndescription: {desc}\ntriggers: []\n---\n\n"
                   f"# {title}\n\n{desc}\n\n{body}")
        with self._lock:
            folder = (self._user_dir / sid)
            # sandbox: folder musi leżeć bezpośrednio pod user_dir
            if folder.resolve().parent != self._user_dir.resolve():
                raise ValueError("invalid skill id")
            folder.mkdir(parents=True, exist_ok=True)
            config.atomic_write_text(folder / SKILL_FILE, content)
            sk = self._read_skill(folder, builtin=False, source="user")
        if sk is None:
            raise ValueError("failed to create skill")
        return self._public({**sk, "enabled": False})

    def delete_skill(self, sid: str) -> bool:
        with self._lock:
            sk = self._all().get(sid)
            # Usuwamy WYŁĄCZNIE skille użytkownika (SKILLS_DIR). Wbudowane i interop
            # (claude-*/grok-*) leżą w cudzych/read-only katalogach → nie ruszamy.
            if sk is None or sk.get("source") != "user":
                return False
            folder = (self._user_dir / sid)
            try:
                if folder.resolve().parent == self._user_dir.resolve() and folder.is_dir():
                    shutil.rmtree(folder)
            except OSError:
                log.warning("Failed to delete skill %s", sid, exc_info=True)
                return False
            cur = self._enabled_set()
            if sid in cur:
                cur.discard(sid)
                self._save_state(cur)
        return True
