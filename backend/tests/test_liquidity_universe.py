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


def sessions(count: int = 20) -> list[date]:
    return [date(2026, 9, day) for day in range(1, count + 1)]


def test_eighteen_sessions_with_sufficient_median_value_and_spread_are_active() -> None:
    candles = [daily(day, 60_000_000) for day in range(1, 20)] + [daily(20, 5_000_000)]

    result = classify_liquidity_tier(
        candles,
        as_of_date=date(2026, 9, 21),
        reference_session_dates=sessions(),
        daily_median_spreads_bps=[10.0] * 20,
    )

    assert result.tier == "active"
    assert result.sessions_available == 20
    assert result.median_spread_bps == 10.0


def test_fewer_than_eighteen_of_twenty_sessions_becomes_dormant() -> None:
    candles = [daily(day, 60_000_000) for day in range(1, 18)]

    result = classify_liquidity_tier(
        candles,
        as_of_date=date(2026, 9, 21),
        reference_session_dates=sessions(),
        daily_median_spreads_bps=[10.0] * 20,
    )

    assert result.tier == "dormant"
    assert result.sessions_available == 17
    assert result.reason == "traded_fewer_than_18_of_last_20_sessions"


def test_median_value_below_five_crore_is_watch_only() -> None:
    candles = [daily(day, 20_000_000) for day in range(1, 21)]

    result = classify_liquidity_tier(
        candles,
        as_of_date=date(2026, 9, 21),
        reference_session_dates=sessions(),
        daily_median_spreads_bps=[10.0] * 20,
    )

    assert result.tier == "watch_only"
    assert result.reason == "rolling_median_traded_value_below_five_crore"


def test_missing_or_wide_spread_history_is_watch_only() -> None:
    candles = [daily(day, 60_000_000) for day in range(1, 21)]

    missing = classify_liquidity_tier(
        candles,
        as_of_date=date(2026, 9, 21),
        reference_session_dates=sessions(),
    )
    wide = classify_liquidity_tier(
        candles,
        as_of_date=date(2026, 9, 21),
        reference_session_dates=sessions(),
        daily_median_spreads_bps=[30.0] * 20,
    )

    assert missing.tier == "watch_only"
    assert missing.reason == "rolling_spread_history_unavailable"
    assert wide.tier == "watch_only"
    assert wide.reason == "rolling_median_spread_above_25_bps"
