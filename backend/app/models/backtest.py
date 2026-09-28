"""Typed contracts for reproducible opportunity-model backtests."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class BacktestRunRequest(BaseModel):
    """Immutable strategy and execution assumptions for one research run."""

    from_date: date
    to_date: date
    min_score: float = Field(default=70.0, ge=0, le=100)
    required_signal_states: list[str] = Field(default_factory=lambda: ["confirmed"])
    require_eligible: bool = True
    max_candidates_per_minute: int = Field(default=3, ge=1, le=100)
    max_trades_per_day: int = Field(default=5, ge=1, le=100)
    max_concurrent_positions: int = Field(default=3, ge=1, le=100)
    one_trade_per_stock_per_day: bool = True
    exit_policy: Literal["fixed_minutes", "end_of_day", "bracket", "model"] = "model"
    holding_minutes: int = Field(default=30, ge=1, le=360)
    stop_loss_percent: float = Field(default=1.0, gt=0, le=20)
    take_profit_percent: float = Field(default=2.0, gt=0, le=50)
    model_exit_score: float = Field(default=55.0, ge=0, le=100)
    model_exit_confirmation_minutes: int = Field(default=2, ge=1, le=10)
    model_minimum_hold_minutes: int = Field(default=3, ge=0, le=120)
    slippage_bps_per_side: float = Field(default=5.0, ge=0, le=500)
    fees_bps_per_side: float = Field(default=10.0, ge=0, le=500)
    initial_capital_inr: float = Field(default=1_000_000.0, gt=0)
    position_size_inr: float = Field(default=100_000.0, gt=0)

    @model_validator(mode="after")
    def validate_period_and_capital(self) -> BacktestRunRequest:
        if self.from_date > self.to_date:
            raise ValueError("from_date cannot be after to_date")
        if (self.to_date - self.from_date).days > 730:
            raise ValueError("one backtest run cannot exceed two calendar years")
        if self.position_size_inr > self.initial_capital_inr:
            raise ValueError("position_size_inr cannot exceed initial_capital_inr")
        if not self.required_signal_states:
            raise ValueError("at least one signal state is required")
        return self


class BacktestTrade(BaseModel):
    trade_id: str
    instrument_key: str
    symbol: str
    sector: str | None = None
    signal_timestamp: datetime
    entry_timestamp: datetime
    exit_timestamp: datetime
    opportunity_score: float = Field(ge=0, le=100)
    score_status: str
    signal_state: str
    market_regime: str | None = None
    model_version: str | None = None
    entry_price: float = Field(gt=0)
    exit_price: float = Field(gt=0)
    gross_return_percent: float
    net_return_percent: float
    cost_percent: float = Field(ge=0)
    pnl_inr: float
    holding_minutes: int = Field(ge=0)
    exit_reason: str
    exit_opportunity_score: float | None = Field(default=None, ge=0, le=100)
    exit_signal_state: str | None = None
    mfe_percent: float | None = None
    mae_percent: float | None = None
    top_positive_factors: list[str] = Field(default_factory=list)
    top_cautions: list[str] = Field(default_factory=list)


class BacktestBreakdown(BaseModel):
    dimension: str
    bucket: str
    trades: int = Field(ge=0)
    win_rate_percent: float | None = None
    average_net_return_percent: float | None = None
    total_pnl_inr: float


class BacktestSummary(BaseModel):
    observations: int = Field(ge=0)
    recorded_sessions: int | None = Field(default=None, ge=0)
    traded_sessions: int | None = Field(default=None, ge=0)
    qualifying_signals: int = Field(ge=0)
    skipped_missing_candles: int = Field(ge=0)
    trades: int = Field(ge=0)
    wins: int = Field(ge=0)
    losses: int = Field(ge=0)
    win_rate_percent: float | None = None
    average_win_percent: float | None = None
    average_loss_percent: float | None = None
    average_net_return_percent: float | None = None
    expectancy_percent: float | None = None
    gross_return_percent: float
    net_return_percent: float
    net_profit_inr: float
    profit_factor: float | None = None
    maximum_drawdown_percent: float
    sharpe_like: float | None = None


class BacktestRun(BaseModel):
    run_id: str
    status: Literal["completed", "failed"]
    created_at: datetime
    completed_at: datetime
    config: BacktestRunRequest
    summary: BacktestSummary
    breakdowns: list[BacktestBreakdown] = Field(default_factory=list)
    model_versions: list[str] = Field(default_factory=list)
    trades: list[BacktestTrade] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class BacktestRunListItem(BaseModel):
    run_id: str
    status: str
    created_at: datetime
    completed_at: datetime
    config: BacktestRunRequest
    summary: BacktestSummary
    model_versions: list[str] = Field(default_factory=list)
