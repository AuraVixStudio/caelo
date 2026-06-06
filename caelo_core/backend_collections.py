"""Wiedza projektu / kolekcje — mixin `Backend` (P2-13, wydzielone ze `state.py`).

`CollectionsMixin`: lokalne dokumenty „wiedzy projektu" (M10-B5). xAI nie ma
serwerowych vector stores (`/v1/vector_stores` → 404), więc dokumenty trzymamy
LOKALNIE pod `config.PROJECT_DOCS_DIR/<project_id>` i dołączamy do wiadomości jako
`input_file` na żądanie („Attach all"). Ścieżki są sandboxowane do PROJECT_DOCS_DIR
(anty-traversal). Metody używają `self.history_store`/`self.current_project_id`
— rozwiązywane na `Backend` w runtime.
"""

from __future__ import annotations

import logging
import secrets
from pathlib import Path

import config  # type: ignore

log = logging.getLogger(__name__)


class CollectionsMixin:
    """Lokalne dokumenty wiedzy projektu (M10-B5). Mixin do `Backend`."""

    def _project_docs_dir(self, project_id: str) -> Path:
        d = Path(config.PROJECT_DOCS_DIR) / project_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def collection_upload(self, data: bytes, filename: str, mime: str = ""):
        """Zapisz dokument LOKALNIE w wiedzy AKTYWNEGO projektu. Zwraca CollectionFile.
        Brak aktywnego projektu → ValueError (wiedza jest per projekt)."""
        pid = self.current_project_id
        if not pid:
            raise ValueError("No active project — select or create one first")
        if self.history_store.get_project(pid) is None:
            raise ValueError("Unknown project")
        rid = secrets.token_hex(8)
        safe = Path(filename or "document").name  # tylko nazwa, bez ścieżki
        target = self._project_docs_dir(pid) / f"{rid}_{safe}"
        target.write_bytes(data)
        return self.history_store.add_collection_file(
            project_id=pid, name=safe, path=str(target), mime=mime or "",
            bytes=len(data or b""), id=rid)

    def collection_files(self):
        """Dokumenty wiedzy aktywnego projektu (pusta lista bez projektu)."""
        pid = self.current_project_id
        return self.history_store.list_collection_files(pid) if pid else []

    def collection_file_path(self, file_row_id: str):
        """Bezpieczna ścieżka pliku dokumentu (musi leżeć pod PROJECT_DOCS_DIR —
        anty-traversal). None, gdy nie znaleziono / poza katalogiem."""
        cf = self.history_store.get_collection_file(file_row_id)
        if cf is None or not cf.path:
            return None
        try:
            p = Path(cf.path).resolve()
            base = Path(config.PROJECT_DOCS_DIR).resolve()
            if base in p.parents and p.is_file():
                return cf
        except OSError:
            return None
        return None

    def collection_remove(self, file_row_id: str) -> bool:
        """Usuń dokument z wiedzy projektu (plik lokalny + rekord). False, gdy brak."""
        cf = self.history_store.get_collection_file(file_row_id)
        if cf is None:
            return False
        if cf.path:
            try:
                p = Path(cf.path).resolve()
                base = Path(config.PROJECT_DOCS_DIR).resolve()
                if base in p.parents and p.exists():
                    p.unlink()
            except OSError:
                log.warning("Could not delete project doc %s", cf.path, exc_info=True)
        self.history_store.remove_collection_file(file_row_id)
        return True
