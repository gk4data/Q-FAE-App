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
    qfae_database_url: str | None = None
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "qfae"
    postgres_user: str = "qfae"
    postgres_password: str | None = None
    qfae_market_history_days: int = 14
    qfae_market_history_retention_days: int = 35
    qfae_minute_history_retention_days: int = 35
    qfae_minute_profile_min_samples: int = 5
    qfae_daily_history_sessions: int = 300
    qfae_market_request_rate_per_second: int = 8
    qfae_market_request_rate_per_minute: int = 450
    qfae_market_snapshot_interval_seconds: int = 60
    qfae_market_pilot_size: int = 20
    qfae_feature_max_spread_bps: float = 25.0
    qfae_feature_min_traded_value_inr: float = 10_000_000.0
    qfae_confirmation_active_rvol: float = 1.0
    qfae_confirmation_strong_rvol: float = 1.5
    qfae_confirmation_active_acceleration: float = 1.0
    qfae_confirmation_strong_acceleration: float = 1.25
    qfae_risk_reference_order_value_inr: float = 100_000.0
    qfae_risk_max_slippage_bps: float = 20.0
    qfae_risk_min_circuit_distance_percent: float = 1.0
    qfae_risk_max_gap_atr: float = 2.0
    qfae_risk_max_spread_range_bps: float = 10.0
    qfae_risk_capital_inr: float | None = None
    qfae_corporate_documents_enabled: bool = True
    qfae_corporate_action_lookback_days: int = 365
    qfae_corporate_action_ai_enabled: bool = False
    openai_api_key: str | None = None
    qfae_ai_model: str | None = None

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.qfae_cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
