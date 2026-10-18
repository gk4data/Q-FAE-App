from pathlib import Path

from app.core.config import Settings
from app.services.upstox_auth import OAuthStateStore, UpstoxAuthService, analytics_access_token


def test_analytics_token_is_trimmed_and_reported_as_authenticated(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        upstox_analytics_token="  analytics-secret  ",
        upstox_token_cache_path=tmp_path / "token.json",
    )
    service = UpstoxAuthService(settings, OAuthStateStore())

    assert analytics_access_token(settings) == "analytics-secret"
    assert service.status() == {
        "configured": True,
        "authenticated": True,
        "expires_at": None,
        "auth_mode": "analytics",
    }


def test_blank_analytics_token_does_not_mask_oauth_configuration(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        upstox_analytics_token=" ",
        upstox_client_id="client",
        upstox_client_secret="secret",
        upstox_redirect_uri="http://localhost/callback",
        upstox_token_cache_path=tmp_path / "token.json",
    )
    service = UpstoxAuthService(settings, OAuthStateStore())

    assert analytics_access_token(settings) is None
    assert service.status()["configured"] is True
    assert service.status()["authenticated"] is False
