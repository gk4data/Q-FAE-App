"""Server-side OAuth and local token storage for the Upstox provider."""

from __future__ import annotations

import json
import os
import secrets
import threading
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from urllib.parse import urlencode

import httpx

from app.core.config import Settings

UPSTOX_AUTHORIZE_URL = "https://api.upstox.com/v2/login/authorization/dialog"
UPSTOX_TOKEN_URL = "https://api.upstox.com/v2/login/authorization/token"
UPSTOX_TIMEZONE_OFFSET = timedelta(hours=5, minutes=30)


class AuthConfigurationError(ValueError):
    """Raised when OAuth credentials have not been configured."""


class OAuthStateError(ValueError):
    """Raised when an OAuth callback state is absent, stale, or already used."""


class OAuthStateStore:
    """Short-lived, one-time OAuth state tokens held only in the API process."""

    def __init__(self, ttl: timedelta = timedelta(minutes=10)) -> None:
        self._ttl = ttl
        self._values: dict[str, datetime] = {}
        self._lock = threading.Lock()

    def issue(self) -> str:
        now = datetime.now(UTC)
        state = secrets.token_urlsafe(32)
        with self._lock:
            self._values = {key: expiry for key, expiry in self._values.items() if expiry > now}
            self._values[state] = now + self._ttl
        return state

    def consume(self, state: str) -> None:
        now = datetime.now(UTC)
        with self._lock:
            expiry = self._values.pop(state, None)
        if expiry is None or expiry <= now:
            raise OAuthStateError("The sign-in request expired or was already used")


class TokenCache:
    """Persist an Upstox bearer token locally without exposing it through the API."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def save(self, access_token: str, expires_at: datetime) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "access_token": access_token,
            "obtained_at": datetime.now(UTC).isoformat(),
            "expires_at": expires_at.isoformat(),
        }
        temporary_path = self.path.with_suffix(".tmp")
        descriptor = os.open(temporary_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            json.dump(payload, file)
        temporary_path.replace(self.path)

    def load(self) -> dict[str, str] | None:
        if not self.path.is_file():
            return None
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            expires_at = datetime.fromisoformat(payload["expires_at"])
            if expires_at <= datetime.now(expires_at.tzinfo or UTC):
                self.clear()
                return None
            if not payload.get("access_token"):
                return None
            return {"access_token": payload["access_token"], "expires_at": payload["expires_at"]}
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            self.clear()
            return None

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()


def next_upstox_token_expiry(now: datetime | None = None) -> datetime:
    """Return the next 03:30 Asia/Kolkata token cutoff as an offset-aware time."""
    now = now or datetime.now(UTC)
    india_time = now.astimezone(UTC).replace(tzinfo=None) + UPSTOX_TIMEZONE_OFFSET
    cutoff = datetime.combine(india_time.date(), time(hour=3, minute=30))
    if india_time >= cutoff:
        cutoff += timedelta(days=1)
    return (cutoff - UPSTOX_TIMEZONE_OFFSET).replace(tzinfo=UTC)


class UpstoxAuthService:
    """Own the Q-FAE Upstox OAuth flow and local access-token lifecycle."""

    def __init__(self, settings: Settings, state_store: OAuthStateStore) -> None:
        self.settings = settings
        self.state_store = state_store
        self.token_cache = TokenCache(settings.upstox_token_cache_path)

    def login_url(self) -> str:
        self._require_configuration()
        state = self.state_store.issue()
        parameters = {
            "response_type": "code",
            "client_id": self.settings.upstox_client_id,
            "redirect_uri": self.settings.upstox_redirect_uri,
            "state": state,
        }
        return f"{UPSTOX_AUTHORIZE_URL}?{urlencode(parameters)}"

    def complete_authorization(self, code: str, state: str) -> None:
        self._require_configuration()
        self.state_store.consume(state)
        response = httpx.post(
            UPSTOX_TOKEN_URL,
            headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
            data={
                "code": code,
                "client_id": self.settings.upstox_client_id,
                "client_secret": self.settings.upstox_client_secret,
                "redirect_uri": self.settings.upstox_redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=30.0,
        )
        response.raise_for_status()
        access_token = response.json().get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise ValueError("Upstox did not return an access token")
        self.token_cache.save(access_token, next_upstox_token_expiry())

    def status(self) -> dict[str, str | bool | None]:
        configured = all(
            [
                self.settings.upstox_client_id,
                self.settings.upstox_client_secret,
                self.settings.upstox_redirect_uri,
            ]
        )
        token = self.token_cache.load() if configured else None
        return {
            "configured": configured,
            "authenticated": token is not None,
            "expires_at": token["expires_at"] if token else None,
        }

    def logout(self) -> None:
        self.token_cache.clear()

    def _require_configuration(self) -> None:
        if not all(
            [
                self.settings.upstox_client_id,
                self.settings.upstox_client_secret,
                self.settings.upstox_redirect_uri,
            ]
        ):
            raise AuthConfigurationError("Upstox OAuth is not fully configured")
