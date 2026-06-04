"""Trasy uwierzytelniania (xAI OAuth) — opakowanie OAuthManager."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from grok_core.state import Backend, get_backend

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
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "account": account}


@router.post("/logout")
def auth_logout(b: Backend = Depends(get_backend)) -> dict:
    b.oauth.logout()
    return {"ok": True}
