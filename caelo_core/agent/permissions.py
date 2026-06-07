"""Bramka uprawnień agenta (model „zatwierdzania zmian" jak w Claude Code).

- Narzędzia READONLY nie wymagają zgody.
- Narzędzia MUTATING (write/edit/run) wymagają zgody użytkownika, chyba że
  zostały wcześniej dopuszczone ("Always allow") — allowlista jest utrwalana
  w `caelo_permissions.json`, więc przeżywa restart aplikacji. Użytkownik może
  ją w każdej chwili wyczyścić z panelu Permissions (DELETE /permissions).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

import config  # type: ignore  # repo-root (sys.path z caelo_core/__init__.py)

from caelo_core.agent.permission_rules import RuleSet

log = logging.getLogger(__name__)


READONLY = {"read_file", "list_dir", "glob", "grep", "lsp"}  # M19-B3: lsp = intel kodu (read-only)
# M19-B13: web_fetch = egress sieciowy → bramkowane (NIE readonly). „Always allow" per-host.
MUTATING = {"write_file", "edit_file", "run_command", "web_fetch"}

# --- polityka bezpieczeństwa run_command (P0-1) ---
# Metaznaki powłoki zawsze niebezpieczne (podstawianie poleceń/zmiennych, nowe
# linie) — wykrywane także wewnątrz cudzysłowów, bo `sh` nadal je interpretuje
# w "...". Metaznaki niebezpieczne tylko POZA cudzysłowem (łańcuchowanie,
# przekierowania, grupowanie) — wewnątrz "..." są literalne i w cmd.exe, i w sh.
_META_ALWAYS = "$`\n\r"
_META_UNQUOTED = "&|;<>(){}"


def _norm_path(path: str) -> str:
    """P0-7: znormalizuj ścieżkę do klucza allowlisty, by `src/a.txt`,
    `./src/a.txt`, `src/./a.txt` i `src\\a.txt` dawały ten sam klucz."""
    path = (path or "").strip()
    if not path:
        return ""
    return os.path.normpath(path).replace("\\", "/")


def command_metachars(command: str, posix: Optional[bool] = None) -> set[str]:
    """Zwraca zbiór metaznaków powłoki, które w `command` mogłyby spowodować
    łańcuchowanie/wstrzyknięcie. Pusty zbiór = komenda to pojedyncze wywołanie
    programu.

    Świadomy cudzysłowów. Domyślnie model dopasowany do platformy
    (`posix=None` → `os.name != 'nt'`):

    - **cmd.exe** (Windows): `"` przełącza tryb literalny; `'` i `\\` to zwykłe
      znaki. Stąd `python -c "print(1)"` i `cd "C:\\Program Files"` przechodzą,
      a `git && rm`, `a | b`, `$(...)` są odrzucane.
    - **POSIX `sh`** (P0-10): dodatkowo `\\` ESKAPUJE następny znak (oba stają się
      literalne — w szczególności `\\"` NIE przełącza cudzysłowu, jak w `sh`),
      a `'...'` to twardy literał (metaznaki w środku są martwe). Domyka to dziurę
      parzystości cudzysłowów (`git \\" && echo hi"` było puste dla cmd.exe, a `sh`
      wykonałoby `&&`). Niezależnie od tego `run_command` na POSIX uruchamia
      `shell=False` + argv — skaner jest tam zachowawczym pre-filtrem, nie jedyną
      obroną.

    `posix` można wymusić jawnie (testy).
    """
    if posix is None:
        posix = os.name != "nt"
    found: set[str] = set()
    in_quote = False  # tryb cudzysłowu podwójnego
    i, n = 0, len(command)
    while i < n:
        ch = command[i]
        if posix and ch == "\\":
            # POSIX: `\` eskapuje następny znak → oba literalne (pomiń parę).
            i += 2
            continue
        if posix and not in_quote and ch == "'":
            # POSIX: '...' literalne — przeskocz do zamykającego apostrofu.
            j = command.find("'", i + 1)
            if j == -1:
                found.add("'")  # niezbalansowany apostrof → odrzuć
                break
            i = j + 1
            continue
        if ch == '"':
            in_quote = not in_quote
            i += 1
            continue
        if ch in _META_ALWAYS:
            found.add(ch)
        elif not in_quote and ch in _META_UNQUOTED:
            found.add(ch)
        i += 1
    if in_quote:
        found.add('"')  # niezbalansowany cudzysłów → niejednoznaczne, odrzuć
    return found


class PermissionGate:
    def __init__(self, store_path: Optional[Path] = None,
                 rules: Optional[RuleSet] = None) -> None:
        self._store_path = store_path
        self._allowed: set[str] = set()
        self._load()
        # M19-B4: warstwa reguł glob (allow/deny, deny>allow) NAD allowlistą „Always
        # allow". Pusty zbiór = brak wpływu (zachowanie sprzed B4). Budowany przez
        # Backend z caelo_settings.json + <ws>/.caelo/permissions.json.
        self.ruleset: RuleSet = rules if rules is not None else RuleSet()

    # --- trwałość (caelo_permissions.json) ---
    def _load(self) -> None:
        if not self._store_path:
            return
        # P1-11: korupcja → backup .corrupt + pusta allowlista (wcześniej cichy
        # reset kasował wszystkie reguły „Always allow" bez śladu).
        data = config.load_json_or_backup(self._store_path, {}) or {}
        self._allowed = set(data.get("allowed") or [])

    def _save(self) -> None:
        if not self._store_path:
            return
        # P1-11: zapis ATOMOWY (był prosty write_text z połykaniem błędu — crash
        # w trakcie korumpował allowlistę, a kolejny _load cicho ją zerował).
        try:
            config.atomic_write_text(
                self._store_path,
                json.dumps({"allowed": sorted(self._allowed)}, indent=2),
            )
        except Exception:
            log.warning("Failed to save %s",
                        getattr(self._store_path, "name", self._store_path), exc_info=True)

    @staticmethod
    def _key(name: str, args: dict) -> Optional[str]:
        if name == "run_command":
            command = (args.get("command") or "").strip()
            # P0-1: nigdy nie kluczuj po samej nazwie exe — to pozwalało regule
            # `cmd:git` autoryzować `git && rm -rf ...`. Klucz = pełna,
            # znormalizowana komenda. Komendy z metaznakami powłoki nie mają
            # klucza (None) → nie da się ich dopuścić („Always allow").
            if not command or command_metachars(command):
                return None
            return "cmd:" + " ".join(command.split())
        if name == "web_fetch":
            # M19-B13: „Always allow" web_fetch PER-HOST (nie per-URL i nie globalnie),
            # by zatwierdzenie jednego pobrania nie autoryzowało dowolnego hosta.
            url = (args.get("url") or "").strip()
            try:
                host = urlsplit(url if "://" in url else "//" + url).netloc.split("@")[-1].split(":")[0].lower()
            except Exception:  # noqa: BLE001
                host = ""
            return f"webfetch:{host}" if host else None
        return f"tool:{name}:{_norm_path(args.get('path', ''))}"

    def needs_approval(self, name: str, args: dict) -> bool:
        if name not in MUTATING:
            return False
        key = self._key(name, args)
        if key is None:
            return True  # niekluczowalna (np. łańcuchowanie) → zawsze pytaj
        return key not in self._allowed

    def allow(self, name: str, args: dict) -> None:
        key = self._key(name, args)
        if key is None:
            return  # nie utrwalaj na allowliście komendy z metaznakami
        self._allowed.add(key)
        self._save()

    # --- klucze dowolne (M14-B2: narzędzia MCP „Always allow" per-narzędzie) ---
    # Narzędzia MCP nie mają ścieżki/komendy do kluczowania jak edycje plików; ich
    # allowlistę trzymamy per nazwa narzędzia (klucz `mcp:<qualified_name>`), w tym
    # samym magazynie `caelo_permissions.json` (panel Permissions pokazuje/czyści je tak samo).
    def needs_approval_key(self, key: str) -> bool:
        return key not in self._allowed

    def allow_key(self, key: str) -> None:
        if not key:
            return
        self._allowed.add(key)
        self._save()

    # --- przegląd / zarządzanie (panel Permissions) ---
    def rules(self) -> list[str]:
        return sorted(self._allowed)

    def clear(self) -> None:
        self._allowed.clear()
        self._save()

    # --- reguły glob (M19-B4) — warstwa NAD allowlistą; deny>allow ---
    def set_rules(self, allow: Optional[list[str]] = None,
                  deny: Optional[list[str]] = None) -> None:
        """Przebuduj zbiór reguł (z ustawień globalnych + projektowych). Niepoprawne
        wpisy są pomijane (REST waliduje osobno)."""
        self.ruleset = RuleSet(allow, deny)

    def evaluate_rules(self, name: str, args: dict, *, is_mcp: bool = False) -> Optional[str]:
        """'deny' / 'allow' / None dla wywołania narzędzia. None gdy brak reguł — wtedy
        wołający spada do allowlisty/zatwierdzenia (zachowanie sprzed B4)."""
        if self.ruleset.empty:
            return None
        return self.ruleset.evaluate_tool(name, args, is_mcp=is_mcp)

    def rule_strings(self) -> dict:
        """Reguły w formie tekstowej (`ToolPrefix(glob)`) — dla REST/UI."""
        return self.ruleset.as_strings()
