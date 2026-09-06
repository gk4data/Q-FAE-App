"""Environment-driven application configuration."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Runtime settings loaded from the repository-root .env file."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    qfae_environment: str = "development"
    qfae_cors_origins: str = "http://localhost:3000,http://localhost:5173"

    upstox_client_id: str | None = None
    upstox_client_secret: str | None = None
    upstox_redirect_uri: str | None = None
    upstox_token_cache_path: Path = PROJECT_ROOT / ".qfae" / "upstox_access_token.json"
    qfae_frontend_url: str = "http://localhost:3000"
    qfae_stock_list_path: Path = PROJECT_ROOT / "Stock List.xlsx"
    qfae_equity_universe_path: Path = PROJECT_ROOT / "data" / "instruments" / "upstox_nse_equity_universe.json"
    qfae_redis_url: str = "redis://localhost:6379/0"
    qfae_market_history_days: int = 5
    qfae_market_history_retention_days: int = 35
    qfae_market_request_rate_per_second: int = 8
    qfae_market_request_rate_per_minute: int = 450
    qfae_market_snapshot_interval_seconds: int = 60

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.qfae_cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
