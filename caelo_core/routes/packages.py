"""Trasy REST marketplace'u pakietów społeczności (M16).

Eksport/import pakietów `.caelopkg`, registry oparte o git/GitHub, szablony projektów
i sprawdzanie aktualizacji. Reżim bezpieczeństwa M14: **import nic nie uruchamia** —
`inspect` pokazuje deklarowane uprawnienia + integralność (karta zgody), a `install`
wymaga jawnego `consent`. Skille/serwery MCP lądują WYŁĄCZONE; szablony tworzą pliki
dopiero przez „New project from template". Fail-closed na tokenie (router pod
`require_token` w server.py). Payload pakietu przesyłany jako base64.
"""

from __future__ import annotations

import base64
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from caelo_core.packages.manifest import ManifestError
from caelo_core.state import Backend, get_backend

log = logging.getLogger(__name__)

router = APIRouter(prefix="/packages", tags=["packages"])


# --- modele żądań ---
class InspectReq(BaseModel):
    data_b64: Optional[str] = None   # zawartość .caelopkg (base64)
    url: Optional[str] = None        # albo zdalny URL pakietu (https)


class InstallReq(BaseModel):
    data_b64: Optional[str] = None
    url: Optional[str] = None
    consent: bool = False            # M16-2: instalacja TYLKO za jawną zgodą


class ExportReq(BaseModel):
    type: str                        # skill | command | mcp | template
    ref: str                         # id skilla/szablonu, nazwa komendy, id serwera MCP


class NewProjectReq(BaseModel):
    dest: str                        # katalog docelowy (zostaje workspace'em)
    name: Optional[str] = None       # nazwa projektu (M9-B5); domyślnie nazwa katalogu


def _decode(data_b64: str) -> bytes:
    try:
        return base64.b64decode(data_b64, validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="data_b64 is not valid base64")


def _err(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


# --- zainstalowane pakiety ---
@router.get("")
def list_packages(b: Backend = Depends(get_backend)) -> dict:
    return {"packages": b.packages.list_installed()}


# --- inspekcja (M16-2: BEZ instalacji) ---
@router.post("/inspect")
def inspect_package(req: InspectReq, b: Backend = Depends(get_backend)) -> dict:
    try:
        if req.data_b64:
            return {"report": b.packages.inspect(_decode(req.data_b64))}
        if req.url:
            return {"report": b.packages.inspect_from_url(req.url)}
    except (ManifestError, ValueError) as exc:
        raise _err(exc)
    raise HTTPException(status_code=400, detail="provide data_b64 or url")


# --- instalacja (M16-2: wymaga consent) ---
@router.post("/install")
def install_package(req: InstallReq, b: Backend = Depends(get_backend)) -> dict:
    if not req.consent:
        raise HTTPException(status_code=400, detail="installation requires explicit consent")
    try:
        if req.data_b64:
            rec = b.packages.install(_decode(req.data_b64), consent=True)
        elif req.url:
            rec = b.packages.install_from_url(req.url, consent=True)
        else:
            raise HTTPException(status_code=400, detail="provide data_b64 or url")
    except (ManifestError, ValueError) as exc:
        raise _err(exc)
    return {"installed": rec}


@router.delete("/{pid}")
def uninstall_package(pid: str, type: Optional[str] = None,
                      b: Backend = Depends(get_backend)) -> dict:
    if not b.packages.uninstall(pid, type):
        raise HTTPException(status_code=404, detail="Package not installed")
    return {"ok": True}


# --- eksport (M16-4) ---
@router.post("/export")
def export_package(req: ExportReq, b: Backend = Depends(get_backend)) -> dict:
    try:
        filename, data = b.packages.export(req.type, req.ref)
    except (ManifestError, ValueError) as exc:
        raise _err(exc)
    return {"filename": filename, "data_b64": base64.b64encode(data).decode("ascii"),
            "bytes": len(data)}


# --- registry (M16-3) + aktualizacje (M16-7) ---
@router.get("/registry")
def get_registry(url: Optional[str] = None, b: Backend = Depends(get_backend)) -> dict:
    try:
        return {"packages": b.packages.fetch_registry(url)}
    except (ManifestError, ValueError) as exc:
        raise _err(exc)
    except Exception as exc:  # noqa: BLE001 (sieć/registry niedostępne)
        log.warning("registry fetch failed", exc_info=True)
        raise HTTPException(status_code=502, detail=f"Could not load registry: {exc}")


@router.get("/updates")
def get_updates(url: Optional[str] = None, b: Backend = Depends(get_backend)) -> dict:
    try:
        return {"updates": b.packages.check_updates(registry_url=url)}
    except (ManifestError, ValueError) as exc:
        raise _err(exc)
    except Exception as exc:  # noqa: BLE001
        log.warning("update check failed", exc_info=True)
        raise HTTPException(status_code=502, detail=f"Could not check updates: {exc}")


# --- szablony projektów (M16-5) ---
@router.get("/templates")
def list_templates(b: Backend = Depends(get_backend)) -> dict:
    return {"templates": b.packages.list_templates()}


@router.post("/templates/{tid}/new-project")
def new_project_from_template(tid: str, req: NewProjectReq,
                              b: Backend = Depends(get_backend)) -> dict:
    """Zmaterializuj szablon w `dest` i zwiąż go jako workspace + projekt (M9-B5)."""
    try:
        result = b.packages.instantiate_template(tid, req.dest)
    except (ManifestError, ValueError) as exc:
        raise _err(exc)
    project = None
    try:
        ws = b.set_workspace(result["dest"])  # tworzy projekt + zapamiętuje recent
        if req.name:
            proj = b.create_project(req.name, root=ws.root.as_posix())
            project = {"id": proj.id, "name": proj.name}
        else:
            cur = b.current_project()
            project = {"id": cur.id, "name": cur.name} if cur else None
    except Exception:  # noqa: BLE001 (workspace/projekt niekrytyczne dla materializacji)
        log.warning("Could not bind new project for template %s", tid, exc_info=True)
    return {"template": result, "project": project}
