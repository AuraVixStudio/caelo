"""Reguły uprawnień jako globy (M19-B4) — `ToolPrefix(glob)`, deny > allow.

Składnia zgodna z Grok CLI / Claude Code:
  `Bash(npm*)` · `Edit(src/**)` · `Write(...)` · `Read(...)` · `Grep(...)` ·
  `WebFetch(domain:docs.rs)` · `MCPTool(server__tool*)`
- Goły prefiks bez nawiasów = wszystkie wywołania danego typu (np. `Bash`).
- Dla prefiksów ŚCIEŻKOWYCH (Edit/Write/Read/Grep): dopasowanie SEGMENTOWE — `*`
  łapie w obrębie jednego segmentu (bez `/`), `**` łapie ≥0 segmentów rekursywnie.
- Dla prefiksów STRINGOWYCH (Bash/MCPTool): target to komenda / nazwa narzędzia, więc
  `*`/`**` dopasowują dowolne znaki (bez segmentacji) — `Bash(npm*)` łapie `npm install x`.
- `WebFetch(domain:host)` dopasowuje host URL (bez `www.`, case-insensitive, też subdomeny).
- **deny ma pierwszeństwo nad allow.**

Warstwa NAD istniejącą allowlistą „Always allow" (`caelo_permissions.json`): reguły są
oceniane pierwsze (deny → twarda odmowa, allow → auto-akceptacja), brak dopasowania spada
do dotychczasowej logiki. **P0-1** (metaznaki `run_command`) NIGDY nie jest obchodzone
regułą allow — egzekwowane przy integracji w `session.py` (`_gate_mutation`).

Brak importu z `permissions.py` (uniknięcie cyklu: to `permissions.py` importuje stąd `RuleSet`).
"""

from __future__ import annotations

import fnmatch
import os
from typing import List, Optional, Tuple
from urllib.parse import urlsplit

# Prefiksy ścieżkowe (dopasowanie segmentowe) vs stringowe (dopasowanie płaskie).
PATH_PREFIXES = {"Edit", "Write", "Read", "Grep"}
STRING_PREFIXES = {"Bash", "MCPTool", "WebFetch"}
PREFIXES = PATH_PREFIXES | STRING_PREFIXES

Rule = Tuple[str, str]  # (prefix, pattern)


def parse_rule(spec: str) -> Optional[Rule]:
    """`'Bash(npm*)'` → `('Bash','npm*')`; `'Bash'` → `('Bash','**')`. None gdy niepoprawne
    (zły prefiks, brak domykającego nawiasu)."""
    if not isinstance(spec, str):
        return None
    s = spec.strip()
    if not s:
        return None
    if "(" not in s:
        prefix, pattern = s, "**"
    else:
        if not s.endswith(")"):
            return None
        i = s.index("(")
        prefix = s[:i].strip()
        pattern = s[i + 1:-1].strip() or "**"
    if prefix not in PREFIXES:
        return None
    return (prefix, pattern)


def _norm_path(path: str) -> str:
    """Znormalizuj ścieżkę do dopasowania (POSIX-owe `/`, bez `./`). Lokalna kopia —
    bez importu z permissions.py (cykl)."""
    p = (path or "").strip()
    if not p:
        return ""
    return os.path.normpath(p).replace("\\", "/")


# --- dopasowanie ----------------------------------------------------------------

def _seg_match(pats: List[str], tgts: List[str]) -> bool:
    """Dopasowanie list segmentów. `**` pochłania ≥0 segmentów; pojedynczy segment
    przez `fnmatch` (`*` = dowolne znaki w segmencie, bez `/`)."""
    if not pats:
        return not tgts
    head = pats[0]
    if head == "**":
        if _seg_match(pats[1:], tgts):
            return True
        return bool(tgts) and _seg_match(pats, tgts[1:])
    if not tgts:
        return False
    if fnmatch.fnmatchcase(tgts[0], head):
        return _seg_match(pats[1:], tgts[1:])
    return False


def _match_path(pattern: str, target: str) -> bool:
    if not target:
        return False
    pats = [p for p in pattern.split("/") if p != ""]
    tgts = [t for t in target.split("/") if t != ""]
    if not pats:       # wzorzec pusty / sam separator → łap wszystko
        return True
    return _seg_match(pats, tgts)


def _match_string(pattern: str, target: str) -> bool:
    if pattern in ("**", "*", ""):
        return True
    return fnmatch.fnmatchcase(target or "", pattern)


def _url_host(url: str) -> str:
    try:
        netloc = urlsplit(url if "://" in url else "//" + url).netloc
        return netloc.split("@")[-1].split(":")[0]
    except Exception:
        return ""


def _strip_www(host: str) -> str:
    return host[4:] if host.lower().startswith("www.") else host


def _match_webfetch(pattern: str, target: str) -> bool:
    if pattern.startswith("domain:"):
        pat = _strip_www(pattern[len("domain:"):].strip().lower())
        host = _strip_www(_url_host(target).lower())
        if not pat:
            return False
        return host == pat or host.endswith("." + pat) or fnmatch.fnmatchcase(host, pat)
    return _match_string(pattern, target)


def _match(prefix: str, pattern: str, target: str) -> bool:
    if prefix in PATH_PREFIXES:
        return _match_path(pattern, target)
    if prefix == "WebFetch":
        return _match_webfetch(pattern, target)
    return _match_string(pattern, target)  # Bash, MCPTool


def targets_for_tool(name: str, args: Optional[dict], *, is_mcp: bool = False) -> List[Rule]:
    """(prefix, target) do sprawdzenia dla danego narzędzia. Pusta lista = reguły nie
    dotyczą (np. `delegate`). `write_file` mapuje się na Write I Edit (sprawdzane oba)."""
    args = args or {}
    if is_mcp:
        return [("MCPTool", name)]
    if name == "run_command":
        return [("Bash", (args.get("command") or "").strip())]
    if name == "write_file":
        p = _norm_path(args.get("path", ""))
        return [("Write", p), ("Edit", p)]
    if name == "edit_file":
        return [("Edit", _norm_path(args.get("path", "")))]
    if name in ("read_file", "list_dir"):
        return [("Read", _norm_path(args.get("path", "")))]
    if name == "grep":
        return [("Grep", _norm_path(args.get("path", ".")))]
    if name == "glob":
        return [("Read", _norm_path(args.get("pattern", "")))]
    if name == "web_fetch":  # M19-B13: dopasowanie po hoście/URL (WebFetch(domain:…) / glob)
        return [("WebFetch", (args.get("url") or "").strip())]
    return []


class RuleSet:
    """Zbiór reguł allow/deny. Niepoprawne wpisy są pomijane przy budowie (REST waliduje
    osobno przez `parse_rule`, by zwrócić 400)."""

    def __init__(self, allow: Optional[List[str]] = None, deny: Optional[List[str]] = None) -> None:
        self.allow: List[Rule] = self._parse(allow)
        self.deny: List[Rule] = self._parse(deny)

    @staticmethod
    def _parse(specs: Optional[List[str]]) -> List[Rule]:
        out: List[Rule] = []
        for s in (specs or []):
            r = parse_rule(s)
            if r is not None:
                out.append(r)
        return out

    @property
    def empty(self) -> bool:
        return not self.allow and not self.deny

    @staticmethod
    def _hits(rules: List[Rule], pairs: List[Rule]) -> bool:
        for rp, pat in rules:
            for tp, target in pairs:
                if rp == tp and _match(rp, pat, target):
                    return True
        return False

    def evaluate_tool(self, name: str, args: Optional[dict], *, is_mcp: bool = False) -> Optional[str]:
        """Zwraca 'deny' / 'allow' / None dla wywołania narzędzia (deny > allow)."""
        pairs = targets_for_tool(name, args, is_mcp=is_mcp)
        if not pairs:
            return None
        if self._hits(self.deny, pairs):
            return "deny"
        if self._hits(self.allow, pairs):
            return "allow"
        return None

    def as_strings(self) -> dict:
        def fmt(r: Rule) -> str:
            return f"{r[0]}({r[1]})"
        return {"allow": [fmt(r) for r in self.allow], "deny": [fmt(r) for r in self.deny]}
