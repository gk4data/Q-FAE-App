"""Provider-neutral market-data models used throughout Q-FAE."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FrozenModel(BaseModel):
    """Immutable value object safe to share across worker threads."""

    model_config = ConfigDict(frozen=True)


class Candle(FrozenModel):
    """One normalized OHLCV candle."""

    instrument_key: str
    timestamp: datetime
    interval: str = "1minute"
    open: float
    high: float
    low: float
    close: float
    volume: int = Field(ge=0)
    open_interest: int = Field(default=0, ge=0)
    source: str = "upstox"

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("candle timestamps must include a timezone")
        return value


class LiveSnapshot(FrozenModel):
    """Latest normalized state for one equity or benchmark."""

    instrument_key: str
    symbol: str
    received_at: datetime
    last_trade_at: datetime | None = None
    ltp: float | None = None
    previous_close: float | None = None
    last_trade_quantity: int | None = Field(default=None, ge=0)
    total_traded_volume: int | None = Field(default=None, ge=0)
    average_traded_price: float | None = None
    best_bid_price: float | None = None
    best_bid_quantity: int | None = Field(default=None, ge=0)
    best_ask_price: float | None = None
    best_ask_quantity: int | None = Field(default=None, ge=0)
    total_buy_quantity: int | None = Field(default=None, ge=0)
    total_sell_quantity: int | None = Field(default=None, ge=0)
    current_candle: Candle | None = None
    completed_candle_relative_volume: float | None = Field(default=None, ge=0)
    completed_candle_timestamp: datetime | None = None


class RelativeVolumeMetric(FrozenModel):
    """RVOL for a specific completed one-minute candle."""

    instrument_key: str
    relative_volume: float = Field(ge=0)
    candle_timestamp: datetime
    calculated_at: datetime


class WatchlistItem(FrozenModel):
    """Frontend-ready state for one stock in the active pilot universe."""

    instrument_key: str
    symbol: str
    company_name: str
    sector: str | None = None
    ltp: float | None = None
    previous_close: float | None = None
    change_percent: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: int | None = Field(default=None, ge=0)
    relative_volume: float | None = Field(default=None, ge=0)
    spread_bps: float | None = Field(default=None, ge=0)
    updated_at: datetime | None = None
    data_state: str = "waiting"


class VWAPFeatures(FrozenModel):
    value: float | None = None
    position_percent: float | None = None
    slope_5m_percent_per_minute: float | None = None
    state: str = "unavailable"


class GapFeatures(FrozenModel):
    previous_close: float | None = None
    opening_price: float | None = None
    gap_percent: float | None = None
    gap_atr: float | None = None
    retention_percent: float | None = None
    state: str = "unavailable"


class OpeningRangeFeatures(FrozenModel):
    minutes: int
    ready: bool = False
    high: float | None = None
    low: float | None = None
    width_percent: float | None = None
    breakout_percent: float | None = None
    position: str = "pending"


class RelativeStrengthFeatures(FrozenModel):
    session_return_percent: float | None = None
    nifty_return_percent: float | None = None
    versus_nifty_percent: float | None = None
    sector_index: str | None = None
    sector_return_percent: float | None = None
    versus_sector_percent: float | None = None
    universe_percentile: float | None = None


class MomentumFeatures(FrozenModel):
    return_1m_percent: float | None = None
    return_5m_percent: float | None = None
    return_15m_percent: float | None = None
    return_30m_percent: float | None = None
    efficiency_ratio_15m: float | None = None
    bullish_candle_ratio_10m: float | None = None
    state: str = "unavailable"


class VolumeFeatures(FrozenModel):
    completed_minute_volume: int | None = Field(default=None, ge=0)
    acceleration_ratio: float | None = Field(default=None, ge=0)
    relative_volume: float | None = Field(default=None, ge=0)
    state: str = "unavailable"


class PullbackFeatures(FrozenModel):
    direction: str = "unavailable"
    distance_from_extreme_percent: float | None = Field(default=None, ge=0)
    recovery_fraction: float | None = Field(default=None, ge=0, le=1)
    countertrend_volume_ratio: float | None = Field(default=None, ge=0)
    quality: str = "unavailable"


class VolatilityFeatures(FrozenModel):
    atr: float | None = Field(default=None, ge=0)
    atr_percent: float | None = Field(default=None, ge=0)
    atr_sessions: int = Field(default=0, ge=0)
    session_range_percent: float | None = Field(default=None, ge=0)
    session_range_atr: float | None = Field(default=None, ge=0)
    state: str = "unavailable"


class LiquidityFeatures(FrozenModel):
    spread_bps: float | None = Field(default=None, ge=0)
    total_traded_value_inr: float | None = Field(default=None, ge=0)
    depth_imbalance: float | None = Field(default=None, ge=-1, le=1)
    passes_spread_filter: bool | None = None
    passes_traded_value_filter: bool | None = None
    state: str = "unavailable"


class StockFeatureSnapshot(FrozenModel):
    """Explainable feature state calculated for one completed market minute."""

    instrument_key: str
    symbol: str
    sector: str | None = None
    as_of: datetime
    candle_timestamp: datetime
    data_quality: str
    unavailable: list[str] = Field(default_factory=list)
    vwap: VWAPFeatures
    gap: GapFeatures
    opening_ranges: list[OpeningRangeFeatures]
    relative_strength: RelativeStrengthFeatures
    momentum: MomentumFeatures
    volume: VolumeFeatures
    pullback: PullbackFeatures
    volatility: VolatilityFeatures
    liquidity: LiquidityFeatures


class HorizonPerformance(FrozenModel):
    sessions: int
    stock_return_percent: float | None = None
    nifty_return_percent: float | None = None
    versus_nifty_percent: float | None = None
    sector_return_percent: float | None = None
    versus_sector_percent: float | None = None


class DailyTrendFeatures(FrozenModel):
    sma_20: float | None = None
    sma_50: float | None = None
    sma_100: float | None = None
    sma_200: float | None = None
    above_sma_20_percent: float | None = None
    above_sma_50_percent: float | None = None
    sma_20_slope_5d_percent: float | None = None
    sma_50_slope_10d_percent: float | None = None
    alignment: str = "unavailable"
    regime: str = "unavailable"


class DailyStructureFeatures(FrozenModel):
    distance_to_20d_high_percent: float | None = None
    distance_to_60d_high_percent: float | None = None
    drawdown_from_252d_high_percent: float | None = None
    close_location_20d: float | None = Field(default=None, ge=0, le=1)
    range_20d_percent: float | None = Field(default=None, ge=0)
    positive_close_ratio_20d: float | None = Field(default=None, ge=0, le=1)
    trend_efficiency_20d: float | None = Field(default=None, ge=0, le=1)
    state: str = "unavailable"


class DailyParticipationFeatures(FrozenModel):
    latest_volume: int | None = Field(default=None, ge=0)
    relative_volume: float | None = Field(default=None, ge=0)
    relative_volume_basis: str = "unavailable"
    up_down_volume_ratio_20: float | None = Field(default=None, ge=0)
    high_volume_direction: str = "unavailable"


class DailyVolatilityFeatures(FrozenModel):
    atr_14: float | None = Field(default=None, ge=0)
    atr_14_percent: float | None = Field(default=None, ge=0)
    atr_14_vs_50: float | None = Field(default=None, ge=0)
    latest_range_atr: float | None = Field(default=None, ge=0)
    state: str = "unavailable"


class DailyRegimeSnapshot(FrozenModel):
    """Independent multi-horizon evidence; no horizon is a hard gate."""

    instrument_key: str
    symbol: str
    sector: str | None = None
    as_of: datetime
    data_through: datetime
    sessions_available: int = Field(ge=1)
    data_quality: str
    horizon_performance: list[HorizonPerformance]
    trend: DailyTrendFeatures
    structure: DailyStructureFeatures
    participation: DailyParticipationFeatures
    volatility: DailyVolatilityFeatures
    evidence: list[str] = Field(default_factory=list)
    cautions: list[str] = Field(default_factory=list)


class BenchmarkState(FrozenModel):
    instrument_key: str
    ltp: float | None = None
    previous_close: float | None = None
    change_percent: float | None = None
    direction: str = "unavailable"
    updated_at: datetime | None = None
    fresh: bool = False


class SectorIndexState(BenchmarkState):
    sector: str


class SectorState(FrozenModel):
    sector: str
    instruments: int
    advancers: int
    decliners: int
    unchanged: int
    average_change_percent: float | None = None


class RelativeVolumeLeader(FrozenModel):
    instrument_key: str
    symbol: str
    relative_volume: float
    candle_timestamp: datetime


class MarketContext(FrozenModel):
    """Minute-level market context derived from the latest complete state."""

    as_of: datetime
    cadence_seconds: int = 60
    nifty_50: BenchmarkState
    nifty_bank: BenchmarkState
    india_vix: BenchmarkState
    sector_indices: list[SectorIndexState] = Field(default_factory=list)
    universe_size: int
    fresh_instruments: int
    stale_instruments: int
    advancers: int
    decliners: int
    unchanged: int
    advance_decline_ratio: float | None = None
    median_spread_bps: float | None = None
    liquid_instruments: int
    sectors: list[SectorState] = Field(default_factory=list)
    relative_volume_leaders: list[RelativeVolumeLeader] = Field(default_factory=list)
