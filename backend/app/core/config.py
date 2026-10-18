"""Environment-driven application configuration."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
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
    upstox_analytics_token: str | None = None
    upstox_redirect_uri: str | None = None
    upstox_token_cache_path: Path = PROJECT_ROOT / ".qfae" / "upstox_access_token.json"
    qfae_frontend_url: str = "http://localhost:3000"
    qfae_equity_universe_path: Path = PROJECT_ROOT / "data" / "instruments" / "upstox_nse_equity_universe.json"
    qfae_min_market_cap_crore: float = Field(default=500.0, ge=0)
    qfae_min_share_price_inr: float = Field(default=20.0, ge=0)
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
    qfae_prune_persisted_minute_history: bool = False
    qfae_minute_profile_min_samples: int = 5
    qfae_daily_history_sessions: int = 300
    qfae_market_request_rate_per_second: int = 8
    qfae_market_request_rate_per_minute: int = 450
    qfae_market_snapshot_interval_seconds: int = 60
    qfae_full_evidence_max_per_minute: int = Field(default=50, ge=1, le=250)
    qfae_compact_evidence_interval_minutes: int = Field(default=15, ge=5, le=60)
    qfae_compact_evidence_score_bucket: int = Field(default=5, ge=1, le=25)
    qfae_focus_start_minutes_after_open: int = Field(default=15, ge=0, le=60)
    qfae_focus_promote_confirmation_minutes: int = Field(default=2, ge=1, le=10)
    qfae_focus_cooling_confirmation_minutes: int = Field(default=2, ge=1, le=10)
    qfae_focus_demote_confirmation_minutes: int = Field(default=3, ge=1, le=10)
    qfae_focus_min_score: float = Field(default=55.0, ge=0, le=100)
    qfae_bootstrap_batch_size: int = Field(default=25, ge=5, le=100)
    qfae_bootstrap_admission_history_sessions: int = Field(default=25, ge=20, le=60)
    qfae_enrichment_financial_limit_per_run: int = Field(default=25, ge=0, le=250)
    qfae_memory_min_available_mb: int = Field(default=1024, ge=256, le=8192)
    qfae_reconciliation_delay_minutes: int = Field(default=10, ge=0, le=60)
    qfae_reconciliation_retry_minutes: int = Field(default=5, ge=1, le=30)
    qfae_reconciliation_max_attempts: int = Field(default=8, ge=1, le=24)
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
    qfae_financial_results_cache_days: int = 30
    qfae_liquidity_lookback_sessions: int = Field(default=20, ge=10, le=60)
    qfae_liquidity_min_traded_sessions: int = Field(default=18, ge=1, le=60)
    qfae_liquidity_active_median_traded_value_inr: float = Field(
        default=50_000_000.0, gt=0
    )
    qfae_liquidity_max_median_spread_bps: float = Field(default=25.0, gt=0)
    qfae_score_weight_price_trend: float = Field(default=30.0, ge=0)
    qfae_score_weight_participation: float = Field(default=20.0, ge=0)
    qfae_score_weight_market_sector: float = Field(default=20.0, ge=0)
    qfae_score_weight_liquidity_execution: float = Field(default=0.0, ge=0)
    qfae_score_weight_fundamental: float = Field(default=15.0, ge=0)

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.qfae_cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
