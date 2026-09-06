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


class BenchmarkState(FrozenModel):
    instrument_key: str
    ltp: float | None = None
    previous_close: float | None = None
    change_percent: float | None = None
    direction: str = "unavailable"


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

