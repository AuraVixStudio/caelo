"""Self-check marketplace'u pakietów (M16) — bez sieci.

Weryfikuje format/manifest (M16-1), bezpieczny import za zgodą + integralność
(M16-2), parsowanie registry (M16-3), eksport round-trip (M16-4), szablony
projektów (M16-5) oraz wersjonowanie/kompatybilność (M16-7):

1) Wersje: parse/compare + `requirement_satisfied` (operatory, prefiks, '*').
2) Integralność: `compute_integrity` deterministyczne; manipulacja payloadu → odrzucenie.
3) Manifest: walidacja (zły typ/id/wersja, schemat z przyszłości odrzucone).
4) Import: BEZ zgody odrzucony; skille/MCP instalują się WYŁĄCZONE (brak auto-run).
5) Limity/sandbox: za duży pakiet, za dużo plików, Zip-Slip odrzucone.
6) Registry: parsuje, pomija niepełne; `check_updates` flaguje has_update/compatible.
7) Szablony: wbudowane odkryte, instancjonują strukturę (bez nadpisywania), eksport.

Kod wyjścia 0 = wszystkie asercje OK.
"""

from __future__ import annotations

import io
import json
import logging
import os
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import config  # type: ignore  # noqa: E402

from caelo_core.commands import CommandRegistry  # noqa: E402
from caelo_core.mcp.manager import McpManager  # noqa: E402
from caelo_core.packages.manager import PackageError, PackageManager  # noqa: E402
from caelo_core.packages.manifest import (  # noqa: E402
    ManifestError,
    compute_integrity,
    parse_version,
    requirement_satisfied,
    validate_manifest,
    version_compare,
)

checks: list[tuple[str, bool]] = []


def check(name: str, passed: bool) -> None:
    checks.append((name, bool(passed)))


def _mgr(d: Path) -> PackageManager:
    return PackageManager(
        d / "caelo_packages.json", d / "skills", d / "templates",
        command_registry=CommandRegistry(d / "caelo_commands.json", d / "commands"),
        mcp_manager=McpManager(d / "caelo_mcp.json"),
        app_version="1.1")


def _tamper(data: bytes, target: str, extra: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as zin, zipfile.ZipFile(buf, "w") as zout:
        for it in zin.infolist():
            blob = zin.read(it)
            if it.filename == target:
                blob = blob + extra
            zout.writestr(it, blob)
    return buf.getvalue()


def test_versions() -> None:
    check("parse_version drops suffix", parse_version("1.2.3-rc1") == (1, 2, 3))
    check("version_compare numeric (not lexical)", version_compare("1.2.0", "1.10.0") == -1)
    check("version_compare equal", version_compare("1.0", "1.0.0") == 0)
    check("requires >= satisfied", requirement_satisfied(">=1.0", "1.1") is True)
    check("requires >= unsatisfied", requirement_satisfied(">=2.0", "1.1") is False)
    check("requires prefix match", requirement_satisfied("1", "1.4") is True)
    check("requires star always ok", requirement_satisfied("*", "0.0.1") is True)
    check("requires < bound", requirement_satisfied("<2.0", "1.9") is True)


def test_manifest() -> None:
    base = {"id": "x", "name": "X", "version": "1.0.0", "type": "skill"}
    ok = validate_manifest(base)
    check("validate_manifest normalizes", ok["type"] == "skill" and ok["requires"]["app"] == "*")
    for bad, why in (
        ({**base, "type": "bogus"}, "bad type"),
        ({**base, "id": "../escape"}, "bad id"),
        ({**base, "version": "not-a-version"}, "bad version"),
        ({**base, "schema": 999}, "future schema"),
    ):
        rejected = False
        try:
            validate_manifest(bad)
        except ManifestError:
            rejected = True
        check(f"manifest rejects {why}", rejected)
    check("compute_integrity deterministic",
          compute_integrity({"a": b"1", "b": b"2"}) == compute_integrity({"b": b"2", "a": b"1"}))
    check("compute_integrity sensitive to content",
          compute_integrity({"a": b"1"}) != compute_integrity({"a": b"2"}))


def test_skill_roundtrip(d: Path) -> None:
    pm = _mgr(d)
    payload = {"SKILL.md": "---\nname: Demo\ndescription: dd\n---\n# Demo\nbody"}
    data = pm.build_package(
        {"id": "demo", "name": "Demo", "version": "1.0.0", "type": "skill", "description": "dd"},
        payload)
    rep = pm.inspect(data)
    check("skill inspect: integrity ok", rep["integrity_ok"] is True)
    check("skill inspect: compatible", rep["compatible"] is True)
    check("skill inspect: low risk", rep["risk"] == "low")

    # bez zgody → odmowa
    refused = False
    try:
        pm.install(data, consent=False)
    except PackageError:
        refused = True
    check("install without consent refused", refused)

    rec = pm.install(data, consent=True)
    check("skill installed to disk", (d / "skills" / "demo" / "SKILL.md").is_file())
    check("skill install recorded", any(p["id"] == "demo" for p in pm.list_installed()))
    # M16-2: skill NIE jest auto-włączony (brak cichego wstrzyknięcia do agenta)
    from caelo_core.skills import SkillManager
    sm = SkillManager(d / "skills")
    check("imported skill is NOT enabled (no silent inject)", sm.injected_text() == "")
    check("install record carries version", rec["version"] == "1.0.0")

    # manipulacja payloadu → integrity fail → odmowa
    tampered = _tamper(data, "payload/SKILL.md", b"HACK")
    check("tamper -> integrity_ok False", pm.inspect(tampered)["integrity_ok"] is False)
    rejected = False
    try:
        pm.install(tampered, consent=True)
    except PackageError:
        rejected = True
    check("tampered package rejected on install", rejected)

    # odinstalowanie usuwa artefakt + rekord
    check("uninstall returns True", pm.uninstall("demo", "skill") is True)
    check("uninstall removed skill folder", not (d / "skills" / "demo").exists())
    check("uninstall removed record", not any(p["id"] == "demo" for p in pm.list_installed()))


def test_command_roundtrip(d: Path) -> None:
    pm = _mgr(d)
    pm._commands.add_command({"name": "deploy", "template": "Deploy {input}", "target": "agent"})
    fn, data = pm.export("command", "deploy")
    check("command export filename", fn.endswith(".caelopkg"))
    rep = pm.inspect(data)
    check("command inspect type", rep["manifest"]["type"] == "command")
    pm._commands.remove_command("deploy")
    pm.install(data, consent=True)
    check("command reinstalled into registry", pm._commands.get("deploy") is not None)


def test_mcp_import_disabled(d: Path) -> None:
    pm = _mgr(d)
    manifest = {"id": "fs", "name": "fs", "version": "1.0.0", "type": "mcp",
                "permissions": {"starts_process": True}}
    payload = {"server.json": json.dumps(
        {"name": "fs", "transport": "stdio", "command": ["npx", "server-fs"]})}
    data = pm.build_package(manifest, payload)
    rep = pm.inspect(data)
    check("mcp inspect: high risk", rep["risk"] == "high")
    check("mcp inspect: warns about process", any("MCP server" in w for w in rep["warnings"]))
    pm.install(data, consent=True)
    st = pm._mcp.status("fs")
    # KLUCZOWE (M16-2): zaimportowany serwer jest WYŁĄCZONY → nie wystartuje sam
    check("imported MCP server is DISABLED (no auto-start)", st["enabled"] is False)
    check("imported MCP server not running", st["status"] in ("stopped", "remote"))


def test_limits_and_sandbox(d: Path) -> None:
    pm = _mgr(d)
    # za duży plik
    big = b"x" * (config.MAX_PACKAGE_BYTES + 10)
    rejected = False
    try:
        pm.inspect(big)
    except PackageError:
        rejected = True
    check("oversized package rejected", rejected)

    # Zip-Slip: payload z '..'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps(
            {"id": "evil", "name": "e", "version": "1.0.0", "type": "skill",
             "integrity": "sha256:00"}))
        zf.writestr("payload/../escape.txt", b"pwned")
    slip = buf.getvalue()
    rejected = False
    try:
        pm.inspect(slip)
    except PackageError:
        rejected = True
    check("zip-slip path rejected", rejected)

    # za dużo plików
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps(
            {"id": "many", "name": "m", "version": "1.0.0", "type": "skill",
             "integrity": "sha256:00"}))
        for i in range(config.MAX_PACKAGE_FILES + 5):
            zf.writestr(f"payload/f{i}.txt", b"x")
    many = buf.getvalue()
    rejected = False
    try:
        pm.inspect(many)
    except PackageError:
        rejected = True
    check("too-many-files rejected", rejected)


def test_registry_and_updates(d: Path) -> None:
    pm = _mgr(d)
    raw = {"packages": [
        {"id": "good", "type": "skill", "name": "Good", "version": "2.0.0",
         "url": "https://x/good.caelopkg"},
        {"id": "", "type": "skill"},               # brak id → pominięty
        {"id": "badtype", "type": "nope"},          # zły typ → pominięty
    ]}
    entries = pm.parse_registry(raw)
    check("registry parses valid only", [e["id"] for e in entries] == ["good"])

    # zainstaluj good@1.0.0, sprawdź wykrycie aktualizacji do 2.0.0
    data = pm.build_package(
        {"id": "good", "name": "Good", "version": "1.0.0", "type": "skill"},
        {"SKILL.md": "---\nname: Good\n---\nbody"})
    pm.install(data, consent=True)
    ups = pm.check_updates(entries)
    good = next(u for u in ups if u["id"] == "good")
    check("check_updates flags has_update", good["has_update"] is True
          and good["installed_version"] == "1.0.0" and good["latest_version"] == "2.0.0")
    check("check_updates compatible", good["compatible"] is True)

    # niekompatybilny wpis (requires app >9) flagowany
    inc = pm.parse_registry({"packages": [
        {"id": "future", "type": "skill", "version": "1.0.0", "requires": {"app": ">=9.0"}}]})
    check("incompatible entry flagged", inc and
          requirement_satisfied(inc[0]["requires"]["app"], "1.1") is False)


def test_templates(d: Path) -> None:
    pm = _mgr(d)
    ids = {t["id"] for t in pm.list_templates()}
    check("builtin templates discovered", {"renpy-vn-starter", "daz-render-pipeline"} <= ids)

    dest = d / "newproj"
    res = pm.instantiate_template("renpy-vn-starter", str(dest))
    check("template instantiates files", (dest / "game" / "script.rpy").is_file()
          and len(res["created"]) >= 3)
    # re-instancjacja nie nadpisuje istniejących
    res2 = pm.instantiate_template("renpy-vn-starter", str(dest))
    check("template re-instantiate skips existing", res2["created"] == [] and len(res2["skipped"]) >= 3)

    # eksport + import szablonu round-trip
    fn, data = pm.export("template", "daz-render-pipeline")
    rep = pm.inspect(data)
    check("template export integrity ok", rep["integrity_ok"] and rep["manifest"]["type"] == "template")
    pm.install(data, consent=True)
    check("template installed to user dir",
          (d / "templates" / "daz-render-pipeline" / "template.json").is_file())

    # P1-15: korupcja meta szablonu jest LOGOWANA (warning), nie połykana po cichu (→ {}).
    bad = d / "templates" / "broken-tpl"
    bad.mkdir(parents=True, exist_ok=True)
    (bad / "template.json").write_text("{ this is not json", encoding="utf-8")
    seen: list = []
    handler = logging.Handler()
    handler.emit = seen.append  # type: ignore[assignment]
    mlog = logging.getLogger("caelo_core.packages.manager")
    mlog.addHandler(handler)
    try:
        meta = PackageManager._read_template_meta(bad)
    finally:
        mlog.removeHandler(handler)
    check("corrupt template meta logged, not swallowed (P1-15)",
          meta == {} and any(r.levelno >= logging.WARNING for r in seen))


def main() -> int:
    test_versions()
    test_manifest()
    with tempfile.TemporaryDirectory() as d1:
        test_skill_roundtrip(Path(d1))
    with tempfile.TemporaryDirectory() as d2:
        test_command_roundtrip(Path(d2))
    with tempfile.TemporaryDirectory() as d3:
        test_mcp_import_disabled(Path(d3))
    with tempfile.TemporaryDirectory() as d4:
        test_limits_and_sandbox(Path(d4))
    with tempfile.TemporaryDirectory() as d5:
        test_registry_and_updates(Path(d5))
    with tempfile.TemporaryDirectory() as d6:
        test_templates(Path(d6))

    print("\n=== Packages / marketplace self-check (M16) ===")
    ok = True
    for name, passed in checks:
        print(f"  [{'OK' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    print(f"\n{'ALL PASSED' if ok else 'SOME FAILED'} ({sum(p for _, p in checks)}/{len(checks)})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
