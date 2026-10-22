from datetime import date, datetime, timedelta, timezone

from app.models.market import Candle
from app.services.liquidity_universe import classify_liquidity_tier

IST = timezone(timedelta(hours=5, minutes=30))
KEY = "NSE_EQ|TEST"


def daily(day: int, traded_value_inr: float) -> Candle:
    price = 100.0
    return Candle(
        instrument_key=KEY,
        timestamp=datetime(2026, 9, day, tzinfo=IST),
        interval="day",
        open=price,
        high=price,
        low=price,
        close=price,
        volume=int(traded_value_inr / price),
    )


def sessions(count: int = 10) -> list[date]:
    return [date(2026, 9, day) for day in range(1, count + 1)]


def test_eight_sessions_with_sufficient_median_value_are_active() -> None:
    candles = [daily(day, 60_000_000) for day in range(1, 10)] + [daily(10, 5_000_000)]

    result = classify_liquidity_tier(
        candles,
        as_of_date=date(2026, 9, 11),
        reference_session_dates=sessions(),
        daily_median_spreads_bps=[10.0] * 10,
    )

    assert result.tier == "active"
    assert result.sessions_available == 10
    assert result.median_spread_bps == 10.0


def test_fewer_than_eight_of_ten_sessions_becomes_dormant() -> None:
    candles = [daily(day, 60_000_000) for day in range(1, 8)]

    result = classify_liquidity_tier(
        candles,
        as_of_date=date(2026, 9, 11),
        reference_session_dates=sessions(),
        daily_median_spreads_bps=[10.0] * 10,
    )

    assert result.tier == "dormant"
    assert result.sessions_available == 7
    assert result.reason == "traded_fewer_than_8_of_last_10_sessions"


def test_median_value_below_two_crore_is_watch_only() -> None:
    candles = [daily(day, 10_000_000) for day in range(1, 11)]

    result = classify_liquidity_tier(
        candles,
        as_of_date=date(2026, 9, 11),
        reference_session_dates=sessions(),
        daily_median_spreads_bps=[10.0] * 10,
    )

    assert result.tier == "watch_only"
    assert result.reason == "rolling_median_traded_value_below_active_threshold"


def test_missing_or_wide_spread_history_remains_active_but_is_reported() -> None:
    candles = [daily(day, 60_000_000) for day in range(1, 11)]

    missing = classify_liquidity_tier(
        candles,
        as_of_date=date(2026, 9, 11),
        reference_session_dates=sessions(),
    )
    wide = classify_liquidity_tier(
        candles,
        as_of_date=date(2026, 9, 11),
        reference_session_dates=sessions(),
        daily_median_spreads_bps=[30.0] * 10,
    )

    assert missing.tier == "active"
    assert missing.reason == "continuity_and_turnover_active"
    assert missing.median_spread_bps is None
    assert wide.tier == "active"
    assert wide.reason == "continuity_and_turnover_active"
    assert wide.median_spread_bps == 30.0
