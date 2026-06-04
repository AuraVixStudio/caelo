"""Pomocnik błędów HTTP (P1-6).

`HTTPException(detail=str(exc))` przekazywał surowy tekst błędu z xAI prosto do
renderera (potencjalny wyciek szczegółów). Tutaj logujemy surowy wyjątek na
stderr (do diagnostyki), a do klienta zwracamy ogólny, bezpieczny komunikat.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException

log = logging.getLogger("grok_core.upstream")


def upstream_error(exc: Exception, public: str = "Upstream request failed",
                   status: int = 502) -> HTTPException:
    """Loguje surowy wyjątek i zwraca HTTPException z ogólnym komunikatem."""
    log.error("%s: %s", public, exc, exc_info=True)
    return HTTPException(status_code=status, detail=public)
