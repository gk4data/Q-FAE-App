from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app.core.config import Settings
from app.services.upstox_auth import OAuthStateError, OAuthStateStore, UpstoxAuthService, next_upstox_token_expiry


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        upstox_client_id="test-client",
        upstox_client_secret="test-secret",
        upstox_redirect_uri="http://localhost:8000/api/v1/auth/upstox/callback",
        upstox_token_cache_path=tmp_path / "token.json",
    )


def test_login_url_contains_a_one_time_state(tmp_path: Path) -> None:
    state_store = OAuthStateStore()
    service = UpstoxAuthService(_settings(tmp_path), state_store)

    state = parse_qs(urlparse(service.login_url()).query)["state"][0]
    state_store.consume(state)

    try:
        state_store.consume(state)
    except OAuthStateError:
        pass
    else:
        raise AssertionError("OAuth state must not be reusable")


def test_token_expiry_uses_the_next_ist_cutoff() -> None:
    before_cutoff = datetime(2026, 9, 6, 21, 0, tzinfo=UTC)  # 02:30 IST
    after_cutoff = datetime(2026, 9, 6, 23, 0, tzinfo=UTC)  # 04:30 IST

    assert next_upstox_token_expiry(before_cutoff) == datetime(2026, 9, 6, 22, 0, tzinfo=UTC)
    assert next_upstox_token_expiry(after_cutoff) == datetime(2026, 9, 7, 22, 0, tzinfo=UTC)


def test_callback_exchange_stores_token_without_exposing_it(tmp_path: Path, monkeypatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, str]:
            return {"access_token": "test-access-token"}

    monkeypatch.setattr("app.services.upstox_auth.httpx.post", lambda *args, **kwargs: FakeResponse())
    state_store = OAuthStateStore()
    service = UpstoxAuthService(_settings(tmp_path), state_store)
    state = parse_qs(urlparse(service.login_url()).query)["state"][0]

    service.complete_authorization("test-code", state)

    assert service.status()["authenticated"] is True
    assert "test-access-token" not in str(service.status())
