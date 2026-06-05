"""Trasy uwierzytelniania (xAI OAuth) — opakowanie OAuthManager."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from caelo_core.errors import upstream_error
from caelo_core.state import Backend, get_backend

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/status")
def auth_status(b: Backend = Depends(get_backend)) -> dict:
    return {
        "authenticated": b.is_authenticated(),
        "oauth": b.oauth.is_authenticated(),
        "account": b.oauth.get_account(),
        "has_api_key": b.has_api_key(),
    }


@router.post("/login")
def auth_login(b: Backend = Depends(get_backend)) -> dict:
    """Pełny przepływ OAuth PKCE (otwiera przeglądarkę + lokalny callback).

    Endpoint jest synchroniczny (`def`), więc FastAPI uruchamia go w puli
    wątków — blokujące oczekiwanie na logowanie nie zatrzymuje pętli zdarzeń.
    """
    try:
        account = b.oauth.login(timeout=300)
    except Exception as exc:
        # P1-13: nie zwracaj surowego str(exc) — komunikaty z wymiany tokenu mogą
        # zawierać `r.text` z auth.x.ai (szczegóły). Loguj surowy, zwróć ogólny.
        raise upstream_error(exc, public="Sign-in failed (see server log for details)", status=400)
    return {"ok": True, "account": account}


@router.post("/logout")
def auth_logout(b: Backend = Depends(get_backend)) -> dict:
    b.oauth.logout()
    return {"ok": True}
