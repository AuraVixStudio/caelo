"""Bramka uprawnień agenta (model „zatwierdzania zmian" jak w Claude Code).

- Narzędzia READONLY nie wymagają zgody.
- Narzędzia MUTATING (write/edit/run) wymagają zgody użytkownika, chyba że
  zostały wcześniej dopuszczone ("Always allow") — allowlista jest utrwalana
  w `grok_permissions.json`, więc przeżywa restart aplikacji. Użytkownik może
  ją w każdej chwili wyczyścić z panelu Permissions (DELETE /permissions).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional


READONLY = {"read_file", "list_dir", "glob", "grep"}
MUTATING = {"write_file", "edit_file", "run_command"}

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


def command_metachars(command: str) -> set[str]:
    """Zwraca zbiór metaznaków powłoki, które w `command` mogłyby spowodować
    łańcuchowanie/wstrzyknięcie. Pusty zbiór = komenda to pojedyncze wywołanie
    programu (bezpieczna do uruchomienia z ``shell=True``).

    Świadomy cudzysłowów (parsuje wg reguł cmd.exe — środowiska docelowego:
    cudzysłów podwójny `"` przełącza tryb literalny, `'` i `\\` są zwykłymi
    znakami). Dzięki temu `python -c "print(1)"` czy `cd "C:\\Program Files"`
    przechodzą, a `git status && rm -rf x`, `a | b`, `$(...)` są odrzucane.

    UWAGA (platforma): poprawne i bezpieczne dla cmd.exe (Windows = cel aplikacji,
    `shell=True` → cmd). Na POSIX-owym `sh` `\\` jest znakiem ucieczki, więc
    sekwencja `\\"` mogłaby ukryć operator łańcuchujący przed tym skanerem
    (np. `echo "\\"" && rm`). Jeśli sidecar miałby działać na Linux/Mac, na tej
    platformie uruchamiać run_command z `shell=False` + argv (shlex) albo dodać
    obsługę `\\`-escape tutaj.
    """
    found: set[str] = set()
    in_quote = False
    for ch in command:
        if ch == '"':
            in_quote = not in_quote
            continue
        if ch in _META_ALWAYS:
            found.add(ch)
        elif not in_quote and ch in _META_UNQUOTED:
            found.add(ch)
    if in_quote:
        found.add('"')  # niezbalansowany cudzysłów → niejednoznaczne, odrzuć
    return found


class PermissionGate:
    def __init__(self, store_path: Optional[Path] = None) -> None:
        self._store_path = store_path
        self._allowed: set[str] = set()
        self._load()

    # --- trwałość (grok_permissions.json) ---
    def _load(self) -> None:
        if not self._store_path or not self._store_path.exists():
            return
        try:
            data = json.loads(self._store_path.read_text(encoding="utf-8")) or {}
            self._allowed = set(data.get("allowed") or [])
        except Exception:
            self._allowed = set()

    def _save(self) -> None:
        if not self._store_path:
            return
        try:
            self._store_path.write_text(
                json.dumps({"allowed": sorted(self._allowed)}, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

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

    # --- przegląd / zarządzanie (panel Permissions) ---
    def rules(self) -> list[str]:
        return sorted(self._allowed)

    def clear(self) -> None:
        self._allowed.clear()
        self._save()
