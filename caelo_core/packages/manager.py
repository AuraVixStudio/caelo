"""Menedżer pakietów społeczności (M16) — warstwa dystrybucji nad M14.

Buduje/eksportuje (`.caelopkg` = ZIP z manifest.json + payload/), **inspekcjonuje**
(manifest + deklarowane uprawnienia + integralność, BEZ instalacji) i **instaluje
za jawną zgodą** (M16-2). Registry oparte o git/GitHub (M16-3, zero infrastruktury),
szablony projektów (M16-5) i sprawdzanie aktualizacji/kompatybilności (M16-7).

Reżim bezpieczeństwa = ten sam co M14: import NIC nie uruchamia. Skille instalują się
WYŁĄCZONE (nie wstrzykiwane, dopóki user nie włączy), serwery MCP — WYŁĄCZONE (nie
startują; start to osobna, bramkowana akcja), komendy to tylko szablony promptu,
szablony instancjonują pliki dopiero na żądanie usera. Integralność (sha256 payloadu)
jest weryfikowana przed instalacją — cicha modyfikacja payloadu = odrzucenie.

Stan: `caelo_packages.json` (rejestr zainstalowanych, atomowo + `load_json_or_backup`,
gitignored przez siatkę `caelo_*.json`). Zależności (`command_registry`, `mcp_manager`)
są WSTRZYKIWANE — manager jest testowalny na stubach i nie tworzy cykli importu
(jak egzekutor w `genjobs.py`).
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import shutil
import threading
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import config  # type: ignore

from caelo_core.markdown_meta import parse_frontmatter
from caelo_core.packages.manifest import (
    PACKAGE_TYPES,
    PAYLOAD_PREFIX,
    SCHEMA_VERSION,
    ManifestError,
    compute_integrity,
    is_safe_payload_name,
    normalize_permissions,
    requirement_satisfied,
    risk_level,
    validate_manifest,
    version_compare,
)

log = logging.getLogger(__name__)

try:
    import requests  # type: ignore
except Exception:  # pragma: no cover
    requests = None  # type: ignore

BUILTIN_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates" / "builtin"
TEMPLATE_META_FILE = "template.json"
TEMPLATE_FILES_DIR = "files"
SKILL_FILE = "SKILL.md"
_ID_RX = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def resolve_app_version() -> str:
    """Wersja produktu do sprawdzeń kompatybilności (M16-7). Jak w `server.py`:
    env (Electron) → desktop/package.json → fallback. Standalone, by manager nie
    zależał od `server` (cykl importu)."""
    env_v = os.environ.get("CAELO_CORE_APP_VERSION")
    if env_v:
        return env_v
    try:
        pkg = Path(config.BASE_DIR) / "desktop" / "package.json"
        v = json.loads(pkg.read_text(encoding="utf-8")).get("version")
        if v:
            return str(v)
    except Exception:  # noqa: BLE001
        pass
    return getattr(config, "APP_VERSION", "0.0.0")


class PackageError(ValueError):
    """Błąd budowy/importu pakietu (komunikat trafia do UI)."""


class PackageManager:
    def __init__(
        self,
        packages_file: Optional[Path] = None,
        skills_dir: Optional[Path] = None,
        templates_dir: Optional[Path] = None,
        *,
        command_registry=None,
        mcp_manager=None,
        app_version: Optional[str] = None,
    ) -> None:
        self._path = packages_file or config.PACKAGES_FILE
        self._skills_dir = Path(skills_dir) if skills_dir else config.SKILLS_DIR
        self._templates_dir = Path(templates_dir) if templates_dir else config.TEMPLATES_DIR
        self._commands = command_registry
        self._mcp = mcp_manager
        self._app_version = app_version or resolve_app_version()
        self._lock = threading.RLock()

    # === rejestr zainstalowanych (caelo_packages.json) =======================
    def _installed(self) -> list[dict]:
        data = config.load_json_or_backup(self._path, {}) or {}
        items = data.get("packages") if isinstance(data, dict) else None
        return [p for p in (items or []) if isinstance(p, dict) and p.get("id")]

    def _save_installed(self, items: list[dict]) -> None:
        try:
            config.atomic_write_text(
                self._path, json.dumps({"packages": items}, indent=2, ensure_ascii=False))
        except Exception:  # noqa: BLE001
            log.warning("Failed to save %s", getattr(self._path, "name", self._path), exc_info=True)

    def list_installed(self) -> list[dict]:
        with self._lock:
            return [dict(p) for p in self._installed()]

    def _record_installed(self, manifest: dict) -> dict:
        record = {
            "id": manifest["id"],
            "type": manifest["type"],
            "name": manifest["name"],
            "version": manifest["version"],
            "author": manifest["author"],
            "source": manifest["source"],
            "requires": manifest["requires"],
            "permissions": manifest["permissions"],
            "integrity": manifest["integrity"],
            "installed_at": datetime.now().isoformat(timespec="seconds"),
        }
        with self._lock:
            items = [p for p in self._installed()
                     if not (p.get("id") == record["id"] and p.get("type") == record["type"])]
            items.append(record)
            self._save_installed(items)
        return record

    # === budowa / eksport (M16-1 / M16-4) ====================================
    @staticmethod
    def build_package(manifest_fields: dict, payload_files: dict) -> bytes:
        """Złóż `.caelopkg` (ZIP) z deklarowanych pól + payloadu (`{name: bytes|str}`).
        Liczy i wstawia integralność. Zwraca bajty archiwum."""
        clean_payload: dict[str, bytes] = {}
        for name, data in payload_files.items():
            if not is_safe_payload_name(name):
                raise PackageError(f"unsafe payload path: {name}")
            clean_payload[name] = data.encode("utf-8") if isinstance(data, str) else bytes(data)
        manifest = dict(manifest_fields)
        manifest["schema"] = SCHEMA_VERSION
        manifest["integrity"] = compute_integrity(clean_payload)
        manifest = validate_manifest(manifest)  # waliduj POST-hash (integrity ustawione)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
            for name in sorted(clean_payload):
                zf.writestr(PAYLOAD_PREFIX + name, clean_payload[name])
        return buf.getvalue()

    def export(self, ptype: str, ref: str) -> tuple[str, bytes]:
        """Wyeksportuj istniejący artefakt jako pakiet. Zwraca (filename, bytes)."""
        ptype = (ptype or "").lower()
        if ptype == "skill":
            manifest, payload = self._gather_skill(ref)
        elif ptype == "command":
            manifest, payload = self._gather_command(ref)
        elif ptype == "mcp":
            manifest, payload = self._gather_mcp(ref)
        elif ptype == "template":
            manifest, payload = self._gather_template(ref)
        else:
            raise PackageError(f"type must be one of {PACKAGE_TYPES}")
        data = self.build_package(manifest, payload)
        filename = f"{manifest['id']}-{manifest['version']}.caelopkg"
        return filename, data

    def _skill_folder(self, sid: str) -> Optional[Path]:
        try:
            from caelo_core.skills.manager import BUILTIN_DIR
        except Exception:  # noqa: BLE001
            BUILTIN_DIR = None
        user = self._skills_dir / sid
        if (user / SKILL_FILE).is_file():
            return user
        if BUILTIN_DIR is not None and (BUILTIN_DIR / sid / SKILL_FILE).is_file():
            return BUILTIN_DIR / sid
        return None

    def _gather_skill(self, sid: str) -> tuple[dict, dict]:
        if not _ID_RX.match(sid or ""):
            raise PackageError("invalid skill id")
        folder = self._skill_folder(sid)
        if folder is None:
            raise PackageError(f"unknown skill: {sid}")
        payload: dict[str, bytes] = {}
        total = 0
        for p in sorted(folder.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(folder).as_posix()
            if not is_safe_payload_name(rel) or rel.startswith("_"):
                continue
            data = p.read_bytes()
            total += len(data)
            if total > config.MAX_PACKAGE_UNPACKED_BYTES:
                raise PackageError("skill is too large to package")
            payload[rel] = data
        meta, _ = parse_frontmatter((folder / SKILL_FILE).read_text(encoding="utf-8", errors="replace"))
        manifest = {
            "id": sid,
            "name": str(meta.get("name") or sid),
            "version": str(meta.get("version") or "1.0.0"),
            "type": "skill",
            "author": str(meta.get("author") or ""),
            "description": str(meta.get("description") or ""),
            "permissions": {"writes_files": len(payload) > 1},
        }
        return manifest, payload

    def _gather_command(self, name: str) -> tuple[dict, dict]:
        if self._commands is None:
            raise PackageError("command registry unavailable")
        cmd = self._commands.get(name)
        if cmd is None:
            raise PackageError(f"unknown command: {name}")
        clean = {k: cmd[k] for k in ("name", "description", "template", "target")
                 if k in cmd}
        for k in ("mode", "action"):
            if cmd.get(k):
                clean[k] = cmd[k]
        manifest = {
            "id": re.sub(r"[^a-zA-Z0-9_-]", "-", clean["name"])[:64] or "command",
            "name": clean["name"],
            "version": "1.0.0",
            "type": "command",
            "description": clean.get("description") or "",
            "permissions": {"tools": [], "network": False},
        }
        return manifest, {"command.json": json.dumps(clean, indent=2, ensure_ascii=False)}

    def _gather_mcp(self, sid: str) -> tuple[dict, dict]:
        if self._mcp is None:
            raise PackageError("MCP manager unavailable")
        cfg = self._mcp.public_config(sid)  # już zamaskowane (bez authorization/env values)
        # Eksportujemy konfigurację BEZ sekretów; importer musi je uzupełnić sam.
        server = {k: cfg[k] for k in ("name", "transport", "command", "cwd", "url",
                                      "server_label", "env_keys") if k in cfg}
        manifest = {
            "id": re.sub(r"[^a-zA-Z0-9_-]", "-", cfg.get("id") or sid)[:64] or "mcp",
            "name": cfg.get("name") or sid,
            "version": "1.0.0",
            "type": "mcp",
            "description": f"MCP server ({cfg.get('transport')})",
            "permissions": {"starts_process": cfg.get("transport") == "stdio",
                            "network": cfg.get("transport") == "remote"},
        }
        return manifest, {"server.json": json.dumps(server, indent=2, ensure_ascii=False)}

    def _gather_template(self, tid: str) -> tuple[dict, dict]:
        folder = self._template_folder(tid)
        if folder is None:
            raise PackageError(f"unknown template: {tid}")
        meta = self._read_template_meta(folder) or {}
        payload: dict[str, bytes] = {}
        meta_path = folder / TEMPLATE_META_FILE
        if meta_path.is_file():
            payload[TEMPLATE_META_FILE] = meta_path.read_bytes()
        files_root = folder / TEMPLATE_FILES_DIR
        total = 0
        if files_root.is_dir():
            for p in sorted(files_root.rglob("*")):
                if not p.is_file():
                    continue
                rel = (TEMPLATE_FILES_DIR + "/" + p.relative_to(files_root).as_posix())
                if not is_safe_payload_name(rel):
                    continue
                data = p.read_bytes()
                total += len(data)
                if total > config.MAX_PACKAGE_UNPACKED_BYTES:
                    raise PackageError("template is too large to package")
                payload[rel] = data
        manifest = {
            "id": tid,
            "name": str(meta.get("name") or tid),
            "version": str(meta.get("version") or "1.0.0"),
            "type": "template",
            "author": str(meta.get("author") or ""),
            "description": str(meta.get("description") or ""),
            "permissions": {"writes_files": True},
        }
        return manifest, payload

    # === inspekcja (M16-2 — BEZ instalacji) ==================================
    def _read_archive(self, data: bytes) -> tuple[dict, dict]:
        """Rozpakuj `.caelopkg` → (manifest_raw, payload_files). Egzekwuje twarde
        limity i bezpieczeństwo nazw (anty zip-bomba / Zip-Slip)."""
        if not data:
            raise PackageError("empty package")
        if len(data) > config.MAX_PACKAGE_BYTES:
            raise PackageError("package file is too large")
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            raise PackageError("not a valid .caelopkg (zip) file")
        manifest_raw: Optional[dict] = None
        payload: dict[str, bytes] = {}
        total = 0
        count = 0
        with zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                name = info.filename.replace("\\", "/")
                count += 1
                if count > config.MAX_PACKAGE_FILES:
                    raise PackageError("package has too many files")
                if info.file_size > config.MAX_PACKAGE_UNPACKED_BYTES:
                    raise PackageError("package entry is too large")
                if name == "manifest.json":
                    try:
                        manifest_raw = json.loads(zf.read(info).decode("utf-8"))
                    except Exception:
                        raise PackageError("manifest.json is not valid JSON")
                    continue
                if not name.startswith(PAYLOAD_PREFIX):
                    continue  # ignoruj cokolwiek poza payload/ i manifestem
                rel = name[len(PAYLOAD_PREFIX):]
                if not is_safe_payload_name(rel):
                    raise PackageError(f"unsafe path in package: {rel}")
                blob = zf.read(info)
                total += len(blob)
                if total > config.MAX_PACKAGE_UNPACKED_BYTES:
                    raise PackageError("package payload is too large (zip bomb?)")
                payload[rel] = blob
        if manifest_raw is None:
            raise PackageError("package is missing manifest.json")
        return manifest_raw, payload

    def inspect(self, data: bytes) -> dict:
        """Zbadaj pakiet BEZ instalacji: manifest, deklarowane uprawnienia, ryzyko,
        zgodność integralności, kompatybilność z wersją aplikacji i czy już
        zainstalowany. To karta zgody (M16-2) — instalacja jest osobnym krokiem."""
        manifest_raw, payload = self._read_archive(data)
        manifest = validate_manifest(manifest_raw)
        recomputed = compute_integrity(payload)
        integrity_ok = bool(manifest.get("integrity")) and (manifest["integrity"] == recomputed)
        compatible = requirement_satisfied(manifest["requires"]["app"], self._app_version)
        warnings: list[str] = []
        if not integrity_ok:
            warnings.append("Integrity check FAILED — the payload was modified after signing.")
        if not compatible:
            warnings.append(
                f"Requires app {manifest['requires']['app']} (you have {self._app_version}).")
        if manifest["permissions"]["starts_process"] or manifest["type"] == "mcp":
            warnings.append("Contains an MCP server that can run a local process — "
                            "imported DISABLED; you must start it manually (gated).")
        installed = self._find_installed(manifest["id"], manifest["type"])
        if installed:
            cmp = version_compare(manifest["version"], installed.get("version") or "0")
            warnings.append(
                f"Already installed (v{installed.get('version')}); importing "
                + ("an older" if cmp < 0 else "the same" if cmp == 0 else "a newer") + " version.")
        return {
            "manifest": manifest,
            "integrity_ok": integrity_ok,
            "compatible": compatible,
            "risk": risk_level(manifest["type"], manifest["permissions"]),
            "warnings": warnings,
            "payload_names": sorted(payload),
            "already_installed": bool(installed),
        }

    # === instalacja (M16-2 — wymaga jawnej zgody) ============================
    def install(self, data: bytes, *, consent: bool = False) -> dict:
        """Zainstaluj pakiet — TYLKO za jawną zgodą i przy poprawnej integralności.
        NIC nie uruchamia: skille/serwery MCP lądują WYŁĄCZONE, szablony tylko
        zapisane, komendy to szablony. Zwraca rekord instalacji."""
        if not consent:
            raise PackageError("installation requires explicit consent")
        manifest_raw, payload = self._read_archive(data)
        manifest = validate_manifest(manifest_raw)
        if manifest["integrity"] != compute_integrity(payload):
            raise PackageError("integrity check failed — refusing to install a modified package")
        ptype = manifest["type"]
        if ptype == "skill":
            self._install_skill(manifest, payload)
        elif ptype == "command":
            self._install_command(manifest, payload)
        elif ptype == "mcp":
            self._install_mcp(manifest, payload)
        elif ptype == "template":
            self._install_template(manifest, payload)
        else:  # nie powinno wystąpić (validate_manifest gwarantuje)
            raise PackageError(f"unsupported package type: {ptype}")
        return self._record_installed(manifest)

    def _install_skill(self, manifest: dict, payload: dict) -> None:
        if SKILL_FILE not in payload:
            raise PackageError("skill package is missing SKILL.md")
        sid = manifest["id"]
        dest = (self._skills_dir / sid).resolve()
        if dest.parent != self._skills_dir.resolve():
            raise PackageError("invalid skill destination")
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        dest.mkdir(parents=True, exist_ok=True)
        for rel, blob in payload.items():
            target = (dest / rel).resolve()
            if dest not in target.parents and target != dest:
                raise PackageError(f"unsafe skill path: {rel}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(blob)
        # Świadomie NIE włączamy skilla (M16-2: brak cichego wstrzyknięcia do agenta).

    def _install_command(self, manifest: dict, payload: dict) -> None:
        if self._commands is None:
            raise PackageError("command registry unavailable")
        try:
            cmd = json.loads((payload.get("command.json") or b"{}").decode("utf-8"))
        except Exception:
            raise PackageError("command.json is not valid JSON")
        if not isinstance(cmd, dict) or not cmd.get("name"):
            raise PackageError("command package has no command definition")
        self._commands.add_command(cmd)  # tylko szablon promptu; wykonanie = akcja usera

    def _install_mcp(self, manifest: dict, payload: dict) -> None:
        if self._mcp is None:
            raise PackageError("MCP manager unavailable")
        try:
            server = json.loads((payload.get("server.json") or b"{}").decode("utf-8"))
        except Exception:
            raise PackageError("server.json is not valid JSON")
        if not isinstance(server, dict):
            raise PackageError("server.json must be an object")
        server["id"] = manifest["id"]
        server["enabled"] = False  # KLUCZOWE (M16-2): nie wystartuje przy autostarcie
        server.pop("authorization", None)
        server.pop("env", None)     # sekrety i tak nie były w pakiecie
        self._mcp.add_server(server)  # add_server NIE startuje serwera

    def _install_template(self, manifest: dict, payload: dict) -> None:
        tid = manifest["id"]
        dest = (self._templates_dir / tid).resolve()
        if dest.parent != self._templates_dir.resolve():
            raise PackageError("invalid template destination")
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        dest.mkdir(parents=True, exist_ok=True)
        for rel, blob in payload.items():
            target = (dest / rel).resolve()
            if dest not in target.parents and target != dest:
                raise PackageError(f"unsafe template path: {rel}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(blob)

    # === odinstalowanie ======================================================
    def uninstall(self, pid: str, ptype: Optional[str] = None) -> bool:
        with self._lock:
            record = self._find_installed(pid, ptype)
            if record is None:
                return False
            rtype = record["type"]
            try:
                if rtype == "skill":
                    folder = self._skills_dir / pid
                    if folder.resolve().parent == self._skills_dir.resolve() and folder.is_dir():
                        shutil.rmtree(folder, ignore_errors=True)
                elif rtype == "template":
                    folder = self._templates_dir / pid
                    if folder.resolve().parent == self._templates_dir.resolve() and folder.is_dir():
                        shutil.rmtree(folder, ignore_errors=True)
                elif rtype == "command" and self._commands is not None:
                    self._commands.remove_command(record.get("name") or pid)
                elif rtype == "mcp" and self._mcp is not None:
                    self._mcp.remove_server(pid)
            except Exception:  # noqa: BLE001
                log.warning("uninstall artifact cleanup failed for %s", pid, exc_info=True)
            items = [p for p in self._installed()
                     if not (p.get("id") == pid and p.get("type") == rtype)]
            self._save_installed(items)
        return True

    def _find_installed(self, pid: str, ptype: Optional[str]) -> Optional[dict]:
        for p in self._installed():
            if p.get("id") == pid and (ptype is None or p.get("type") == ptype):
                return p
        return None

    # === szablony projektów (M16-5) ==========================================
    def _template_folder(self, tid: str) -> Optional[Path]:
        if not _ID_RX.match(tid or ""):
            return None
        user = self._templates_dir / tid
        if (user / TEMPLATE_META_FILE).is_file() or (user / TEMPLATE_FILES_DIR).is_dir():
            return user
        builtin = BUILTIN_TEMPLATES_DIR / tid
        if (builtin / TEMPLATE_META_FILE).is_file() or (builtin / TEMPLATE_FILES_DIR).is_dir():
            return builtin
        return None

    @staticmethod
    def _read_template_meta(folder: Path) -> Optional[dict]:
        p = folder / TEMPLATE_META_FILE
        if not p.is_file():
            return {}
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:  # noqa: BLE001
            log.warning("Could not read template meta %s", p, exc_info=True)
            return {}

    def _scan_templates(self, base: Path, *, builtin: bool) -> list[dict]:
        out: list[dict] = []
        if not base.is_dir():
            return out
        try:
            for folder in sorted(base.iterdir()):
                if not folder.is_dir() or folder.name.startswith((".", "_")):
                    continue
                if not _ID_RX.match(folder.name):
                    continue
                meta = self._read_template_meta(folder) or {}
                files_root = folder / TEMPLATE_FILES_DIR
                file_count = sum(1 for p in files_root.rglob("*") if p.is_file()) \
                    if files_root.is_dir() else 0
                out.append({
                    "id": folder.name,
                    "name": str(meta.get("name") or folder.name),
                    "description": str(meta.get("description") or ""),
                    "version": str(meta.get("version") or "1.0.0"),
                    "builtin": builtin,
                    "file_count": file_count,
                })
        except Exception:  # noqa: BLE001
            log.warning("Failed to scan templates in %s", base, exc_info=True)
        return out

    def list_templates(self) -> list[dict]:
        with self._lock:
            by_id: dict[str, dict] = {}
            for t in self._scan_templates(BUILTIN_TEMPLATES_DIR, builtin=True):
                by_id[t["id"]] = t
            for t in self._scan_templates(self._templates_dir, builtin=False):
                by_id[t["id"]] = t  # user nadpisuje builtin
            return sorted(by_id.values(), key=lambda t: t["id"])

    def instantiate_template(self, tid: str, dest_dir: str) -> dict:
        """Zmaterializuj pliki szablonu w `dest_dir` (tworzony, jeśli trzeba). Nie
        nadpisuje istniejących plików (zwraca je jako `skipped`). Sandboxowane:
        każdy plik musi wylądować pod `dest_dir`."""
        folder = self._template_folder(tid)
        if folder is None:
            raise PackageError(f"unknown template: {tid}")
        dest = Path(dest_dir).expanduser().resolve()
        dest.mkdir(parents=True, exist_ok=True)
        files_root = folder / TEMPLATE_FILES_DIR
        created: list[str] = []
        skipped: list[str] = []
        if files_root.is_dir():
            for p in sorted(files_root.rglob("*")):
                if not p.is_file():
                    continue
                rel = p.relative_to(files_root).as_posix()
                if not is_safe_payload_name(rel):
                    continue
                target = (dest / rel).resolve()
                if dest not in target.parents:
                    raise PackageError(f"unsafe template path: {rel}")
                if target.exists():
                    skipped.append(rel)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(p.read_bytes())
                created.append(rel)
        meta = self._read_template_meta(folder) or {}
        return {"id": tid, "name": str(meta.get("name") or tid),
                "dest": str(dest), "created": created, "skipped": skipped}

    # === registry oparte o git/GitHub (M16-3) ================================
    @staticmethod
    def parse_registry(raw) -> list[dict]:
        """Sparsuj indeks registry (obiekt z `packages: [...]` albo goła lista).
        Każdy wpis: id/type/name/version/author/description + `url` (manifest/pakiet)
        i opcjonalny `source`. Tolerancyjny — pomija niepełne wpisy."""
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8", errors="replace")
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                raise PackageError("registry is not valid JSON")
        items = raw.get("packages") if isinstance(raw, dict) else raw
        out: list[dict] = []
        for it in items or []:
            if not isinstance(it, dict):
                continue
            pid = (it.get("id") or "").strip()
            url = (it.get("url") or it.get("manifest_url") or it.get("package_url") or "").strip()
            ptype = (it.get("type") or "").strip().lower()
            if not pid or ptype not in PACKAGE_TYPES:
                continue
            out.append({
                "id": pid,
                "type": ptype,
                "name": str(it.get("name") or pid),
                "version": str(it.get("version") or ""),
                "author": str(it.get("author") or ""),
                "description": str(it.get("description") or ""),
                "url": url,
                "source": str(it.get("source") or ""),
                "requires": it.get("requires") if isinstance(it.get("requires"), dict) else {},
            })
        return out

    def _https_get(self, url: str, *, cap: int) -> bytes:
        """Pobierz https-only z twardym limitem rozmiaru (jak `_download_media`)."""
        if requests is None:
            raise PackageError("network unavailable (requests not installed)")
        from urllib.parse import urlparse
        if urlparse(url).scheme != "https":
            raise PackageError("refused non-https URL")
        total = 0
        chunks: list[bytes] = []
        with requests.get(url, timeout=60, stream=True) as r:
            r.raise_for_status()
            cl = r.headers.get("Content-Length")
            if cl and cl.isdigit() and int(cl) > cap:
                raise PackageError("remote resource exceeds size cap")
            for chunk in r.iter_content(65536):
                if not chunk:
                    continue
                total += len(chunk)
                if total > cap:
                    raise PackageError("remote resource exceeds size cap")
                chunks.append(chunk)
        return b"".join(chunks)

    def fetch_registry(self, url: Optional[str] = None) -> list[dict]:
        url = url or config.PACKAGES_REGISTRY_URL
        raw = self._https_get(url, cap=4 * 1024 * 1024)
        entries = self.parse_registry(raw)
        installed = {(p["id"], p["type"]): p for p in self._installed()}
        for e in entries:
            inst = installed.get((e["id"], e["type"]))
            e["installed"] = bool(inst)
            e["installed_version"] = inst.get("version") if inst else None
            e["has_update"] = bool(inst and e["version"]
                                   and version_compare(e["version"], inst.get("version") or "0") > 0)
            req_app = (e.get("requires") or {}).get("app") or "*"
            e["compatible"] = requirement_satisfied(req_app, self._app_version)
        return entries

    def fetch_package(self, url: str) -> bytes:
        return self._https_get(url, cap=config.MAX_PACKAGE_BYTES)

    def install_from_url(self, url: str, *, consent: bool = False) -> dict:
        data = self.fetch_package(url)
        return self.install(data, consent=consent)

    def inspect_from_url(self, url: str) -> dict:
        data = self.fetch_package(url)
        out = self.inspect(data)
        out["source_url"] = url
        return out

    # === aktualizacje / kompatybilność (M16-7) ===============================
    def check_updates(self, registry_entries: Optional[list[dict]] = None,
                      registry_url: Optional[str] = None) -> list[dict]:
        """Porównaj zainstalowane pakiety z registry. Zwraca listę z flagami
        `has_update` (nowsza wersja dostępna) i `compatible` (requires app)."""
        if registry_entries is None:
            registry_entries = self.fetch_registry(registry_url)
        by_key = {(e["id"], e["type"]): e for e in registry_entries}
        out: list[dict] = []
        for inst in self._installed():
            key = (inst.get("id"), inst.get("type"))
            entry = by_key.get(key)
            latest = entry.get("version") if entry else None
            req_app = ((entry or {}).get("requires") or inst.get("requires") or {}).get("app") or "*"
            out.append({
                "id": inst.get("id"),
                "type": inst.get("type"),
                "name": inst.get("name"),
                "installed_version": inst.get("version"),
                "latest_version": latest,
                "has_update": bool(latest and version_compare(latest, inst.get("version") or "0") > 0),
                "compatible": requirement_satisfied(req_app, self._app_version),
                "url": entry.get("url") if entry else None,
            })
        return out
