"""Rolling traded-value tiers for controlling live-universe resource usage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from statistics import median

from app.models.market import Candle
from app.services.market_context import INDIA_TIMEZONE


@dataclass(frozen=True)
class LiquidityUniverseDecision:
    tier: str
    sessions_expected: int
    sessions_available: int
    median_daily_traded_value_inr: float | None
    latest_daily_traded_value_inr: float | None
    spread_sessions_available: int
    median_spread_bps: float | None
    reason: str


def approximate_daily_traded_value(candle: Candle) -> float:
    """Approximate turnover from daily OHLCV when provider turnover is unavailable."""
    typical_price = (candle.high + candle.low + candle.close) / 3
    return max(0.0, typical_price * candle.volume)


def classify_liquidity_tier(
    daily_candles: list[Candle],
    *,
    as_of_date: date,
    lookback_sessions: int = 20,
    minimum_traded_sessions: int = 18,
    active_median_traded_value_inr: float = 50_000_000,
    reference_session_dates: list[date] | None = None,
    daily_median_spreads_bps: list[float] | None = None,
    max_median_spread_bps: float = 25.0,
) -> LiquidityUniverseDecision:
    """Apply rolling trading-continuity, turnover and spread admission rules."""
    if not 1 <= minimum_traded_sessions <= lookback_sessions:
        raise ValueError("minimum traded sessions must fit inside the lookback")
    if active_median_traded_value_inr <= 0 or max_median_spread_bps <= 0:
        raise ValueError("liquidity thresholds must be positive")

    completed_by_date = {
        candle.timestamp.astimezone(INDIA_TIMEZONE).date(): candle
        for candle in daily_candles
        if candle.timestamp.astimezone(INDIA_TIMEZONE).date() < as_of_date
    }
    session_calendar = (
        list(completed_by_date)
        if reference_session_dates is None
        else reference_session_dates
    )
    expected_dates = sorted(
        session_date
        for session_date in session_calendar
        if session_date < as_of_date
    )[-lookback_sessions:]
    completed = [
        completed_by_date[session_date]
        for session_date in expected_dates
        if session_date in completed_by_date
        and completed_by_date[session_date].volume > 0
        and completed_by_date[session_date].close > 0
    ]
    values = [approximate_daily_traded_value(candle) for candle in completed]
    spreads = [
        float(value)
        for value in (daily_median_spreads_bps or [])[-lookback_sessions:]
        if value >= 0
    ]
    median_spread = float(median(spreads)) if spreads else None
    sessions_expected = len(expected_dates)
    if sessions_expected < lookback_sessions or len(values) < minimum_traded_sessions:
        return LiquidityUniverseDecision(
            tier="dormant",
            sessions_expected=sessions_expected,
            sessions_available=len(values),
            median_daily_traded_value_inr=round(float(median(values)), 2) if values else None,
            latest_daily_traded_value_inr=round(values[-1], 2) if values else None,
            spread_sessions_available=len(spreads),
            median_spread_bps=round(median_spread, 4) if median_spread is not None else None,
            reason="traded_fewer_than_18_of_last_20_sessions",
        )

    median_value = float(median(values))
    latest_value = values[-1]
    if median_value < active_median_traded_value_inr:
        tier = "watch_only"
        reason = "rolling_median_traded_value_below_five_crore"
    elif median_spread is None:
        tier = "watch_only"
        reason = "rolling_spread_history_unavailable"
    elif median_spread > max_median_spread_bps:
        tier = "watch_only"
        reason = "rolling_median_spread_above_25_bps"
    else:
        tier = "active"
        reason = "continuity_turnover_and_spread_active"

    return LiquidityUniverseDecision(
        tier=tier,
        sessions_expected=sessions_expected,
        sessions_available=len(values),
        median_daily_traded_value_inr=round(median_value, 2),
        latest_daily_traded_value_inr=round(latest_value, 2),
        spread_sessions_available=len(spreads),
        median_spread_bps=round(median_spread, 4) if median_spread is not None else None,
        reason=reason,
    )
