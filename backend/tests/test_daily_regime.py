from datetime import datetime, timedelta, timezone

from app.models.market import Candle
from app.services.daily_regime import (
    aggregate_session_candle,
    build_daily_regime,
    cumulative_relative_volume,
)
from app.services.upstox_market import NIFTY_50_KEY

IST = timezone(timedelta(hours=5, minutes=30))


def daily_candle(key: str, index: int, close: float, volume: int = 1_000) -> Candle:
    timestamp = datetime(2025, 1, 1, tzinfo=IST) + timedelta(days=index)
    return Candle(
        instrument_key=key,
        timestamp=timestamp,
        interval="day",
        open=close - 0.2,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=volume,
    )


def test_new_strength_is_not_vetoed_by_weak_250_session_history() -> None:
    key = "NSE_EQ|TEST"
    stock = []
    nifty = []
    sector = []
    for index in range(251):
        stock_close = 120 - index * 0.2 if index < 200 else 80 + (index - 200) * 0.6
        stock.append(daily_candle(key, index, stock_close, 2_500 if index == 250 else 1_000))
        nifty.append(daily_candle(NIFTY_50_KEY, index, 100 + index * 0.02))
        sector.append(daily_candle("NSE_INDEX|Nifty Auto", index, 100 + index * 0.03))

    regime = build_daily_regime(
        key,
        "TEST",
        "Auto Ancillary",
        stock,
        {NIFTY_50_KEY: nifty, "NSE_INDEX|Nifty Auto": sector},
        as_of=datetime(2026, 9, 8, 15, 30, tzinfo=IST),
    )

    assert regime is not None
    horizons = {row.sessions: row for row in regime.horizon_performance}
    assert horizons[20].stock_return_percent > 0
    assert horizons[250].stock_return_percent < 0
    assert regime.trend.regime == "established_uptrend"
    assert regime.participation.relative_volume == 2.5
    assert regime.participation.relative_volume_basis == "full_session_20d"
    assert "short_term_strength_despite_weak_long_history" in regime.evidence
    assert "weak_250d_history_not_a_veto" in regime.cautions


def test_completed_minutes_form_a_provisional_daily_candle() -> None:
    key = "NSE_EQ|TEST"
    first = Candle(
        instrument_key=key,
        timestamp=datetime(2026, 9, 8, 9, 15, tzinfo=IST),
        open=100,
        high=102,
        low=99,
        close=101,
        volume=1_000,
    )
    second = first.model_copy(
        update={
            "timestamp": datetime(2026, 9, 8, 9, 16, tzinfo=IST),
            "open": 101,
            "high": 104,
            "low": 100,
            "close": 103,
            "volume": 2_000,
        }
    )

    aggregate = aggregate_session_candle(key, [first, second], second)

    assert aggregate is not None
    assert aggregate.interval == "day"
    assert (aggregate.open, aggregate.high, aggregate.low, aggregate.close) == (100, 104, 99, 103)
    assert aggregate.volume == 3_000

    prior_first = first.model_copy(update={"timestamp": first.timestamp - timedelta(days=1), "volume": 500})
    prior_second = second.model_copy(update={"timestamp": second.timestamp - timedelta(days=1), "volume": 1_000})
    assert cumulative_relative_volume([prior_first, prior_second, first, second], second) == 2.0
