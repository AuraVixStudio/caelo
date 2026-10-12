"""Cienki klient xAI Files API dla publicznych linków (docs.x.ai „Public URLs", 2026-06).

Plik w Files API jest domyślnie PRYWATNY. `POST /v1/files/{id}/public-url` zamienia go
w stały, nieuwierzytelniony link na CDN xAI (`files-cdn.x.ai`) — każdy, kto ma link, może
go otworzyć. Odwołanie (`/public-url/revoke`) unieważnia link natychmiast, NIE kasując
pliku. Raw `requests`, bez SDK — jak cały kod xAI w repo (ADR-1).

Limity z dokumentacji: plik ≤ 50 MiB; typy png/jpeg/gif/webp/mp4/webm/pdf; wygaśnięcie
linku 1 h – 30 dni (albo brak = do odwołania); ≤ 1000 aktywnych linków na zespół.
Jeden aktywny link na plik — ponowne `create` zwraca ten sam token (inny `expires_after`
tylko przesuwa wygaśnięcie); po odwołaniu następny `create` daje nowy token.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

import requests

import config  # type: ignore

PUBLIC_URL_MAX_BYTES = 50 * 1024 * 1024
PUBLIC_URL_MIME_TYPES = frozenset({
    "image/png", "image/jpeg", "image/gif", "image/webp",
    "video/mp4", "video/webm", "application/pdf",
})
PUBLIC_URL_MIN_EXPIRY_S = 3600
PUBLIC_URL_MAX_EXPIRY_S = 2_592_000
TIMEOUT_UPLOAD = 300
TIMEOUT_CALL = 30


class XAIFilesClient:
    def __init__(self, api_key_provider: Callable[[], str]) -> None:
        self.get_api_key = api_key_provider

    def _auth(self) -> dict[str, str]:
        key = self.get_api_key()
        if not key:
            raise PermissionError("No xAI credential is configured.")
        return {"Authorization": f"Bearer {key}"}

    @staticmethod
    def _json(r: requests.Response) -> dict[str, Any]:
        if r.status_code == 404:
            # Plik usunięty/wygasły w Files API — wywołujący może wysłać go ponownie.
            raise FileNotFoundError(f"API Error: {r.text[:500]}")
        if r.status_code in (400, 409, 422):
            raise ValueError(f"API Error: {r.text[:500]}")
        r.raise_for_status()
        r.encoding = "utf-8"
        return r.json()

    def upload(self, path: Path, mime: str) -> str:
        """Wyślij lokalny plik (`purpose=assistants`) → `file_id`."""
        with open(path, "rb") as handle:
            r = requests.post(
                f"{config.API_BASE}/files", headers=self._auth(),
                data={"purpose": "assistants"},
                files={"file": (path.name, handle, mime)}, timeout=TIMEOUT_UPLOAD,
            )
        file_id = self._json(r).get("id")
        if not isinstance(file_id, str) or not file_id:
            raise ValueError("Files API returned no file id")
        return file_id

    def create_public_url(self, file_id: str,
                          expires_after: Optional[int] = None) -> dict[str, Any]:
        """→ `{"public_url": …, "expires_at": <unix>|None}`. Idempotentne po stronie xAI."""
        body: dict[str, Any] = {}
        if expires_after is not None:
            body["expires_after"] = int(expires_after)
        r = requests.post(f"{config.API_BASE}/files/{file_id}/public-url",
                          headers=self._auth(), json=body, timeout=TIMEOUT_CALL)
        data = self._json(r)
        url = data.get("public_url")
        if not isinstance(url, str) or not url.startswith("https://"):
            raise ValueError("Files API returned no public URL")
        return {"public_url": url, "expires_at": data.get("expires_at")}

    def revoke_public_url(self, file_id: str) -> bool:
        """Unieważnij link (plik zostaje w Files API). False = nie było aktywnego linku."""
        r = requests.post(f"{config.API_BASE}/files/{file_id}/public-url/revoke",
                          headers=self._auth(), timeout=TIMEOUT_CALL)
        return bool(self._json(r).get("revoked"))
