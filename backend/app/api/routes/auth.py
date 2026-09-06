"""Upstox OAuth routes used by the Q-FAE frontend."""

import logging
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import RedirectResponse

from app.core.config import get_settings
from app.services.upstox_auth import AuthConfigurationError, OAuthStateError, OAuthStateStore, UpstoxAuthService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth/upstox", tags=["authentication"])
_state_store = OAuthStateStore()


def get_auth_service() -> UpstoxAuthService:
    return UpstoxAuthService(get_settings(), _state_store)


def _frontend_redirect(result: str) -> RedirectResponse:
    destination = f"{get_settings().qfae_frontend_url.rstrip('/')}/?{urlencode({'auth': result})}"
    return RedirectResponse(destination, status_code=status.HTTP_303_SEE_OTHER)


@router.get("/login")
def start_upstox_login() -> RedirectResponse:
    """Create one OAuth state value and redirect the browser to Upstox."""
    try:
        return RedirectResponse(get_auth_service().login_url(), status_code=status.HTTP_303_SEE_OTHER)
    except AuthConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.get("/callback")
def complete_upstox_login(
    code: str | None = Query(default=None),
    state_value: str | None = Query(default=None, alias="state"),
    error: str | None = Query(default=None),
) -> RedirectResponse:
    """Validate the OAuth callback, cache the token, then return to the UI."""
    if error or not code or not state_value:
        return _frontend_redirect("cancelled")
    try:
        get_auth_service().complete_authorization(code, state_value)
    except (AuthConfigurationError, OAuthStateError, ValueError, httpx.HTTPError) as exc:
        logger.warning("Upstox OAuth callback failed: %s", exc.__class__.__name__)
        return _frontend_redirect("failed")
    return _frontend_redirect("success")


@router.get("/status")
def upstox_auth_status() -> dict[str, str | bool | None]:
    """Return configuration and token state without returning the bearer token."""
    return get_auth_service().status()


@router.post("/logout")
def logout_upstox() -> dict[str, bool]:
    """Remove Q-FAE's local cached access token."""
    get_auth_service().logout()
    return {"authenticated": False}
