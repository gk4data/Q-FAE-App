from datetime import UTC, datetime, timedelta, timezone

from app.models.market import Candle
from app.services.session_reconciliation import reconcile_session

IST = timezone(timedelta(hours=5, minutes=30))


def minute_candles() -> list[Candle]:
    start = datetime(2026, 9, 9, 9, 15, tzinfo=IST)
    rows = []
    for index in range(375):
        open_price = 100 + index * 0.01
        rows.append(
            Candle(
                instrument_key="NSE_EQ|TEST",
                timestamp=start + timedelta(minutes=index),
                open=open_price,
                high=open_price + 0.2,
                low=open_price - 0.1,
                close=open_price + 0.05,
                volume=100,
            )
        )
    return rows


def test_complete_capture_matches_official_daily_candle() -> None:
    minutes = minute_candles()
    official = Candle(
        instrument_key="NSE_EQ|TEST",
        timestamp=datetime(2026, 9, 9, tzinfo=IST),
        interval="day",
        open=minutes[0].open,
        high=max(row.high for row in minutes),
        low=min(row.low for row in minutes),
        close=minutes[-1].close,
        volume=sum(row.volume for row in minutes),
    )

    result = reconcile_session(
        official,
        minutes,
        symbol="TEST",
        reconciled_at=datetime(2026, 9, 9, 10, 30, tzinfo=UTC),
    )

    assert result.status == "matched"
    assert result.minute_count == 375
    assert result.ohlc_matches is True
    assert result.volume_difference_percent == 0
    assert result.notes == []


def test_missing_capture_preserves_official_candle_and_reports_gap() -> None:
    official = Candle(
        instrument_key="NSE_INDEX|Nifty 50",
        timestamp=datetime(2026, 9, 9, tzinfo=IST),
        interval="day",
        open=25_000,
        high=25_200,
        low=24_900,
        close=25_100,
        volume=0,
    )

    result = reconcile_session(
        official,
        [],
        symbol="NIFTY 50",
        reconciled_at=datetime(2026, 9, 9, 10, 30, tzinfo=UTC),
    )

    assert result.status == "official_only"
    assert result.aggregated_close is None
    assert "minute_grid_gaps_no_trade_or_missing" in result.notes


def test_post_cas_official_close_and_extra_volume_are_not_false_capture_errors() -> None:
    minutes = minute_candles()
    official = Candle(
        instrument_key="NSE_EQ|TEST",
        timestamp=datetime(2026, 9, 9, tzinfo=IST),
        interval="day",
        open=minutes[0].open,
        high=max(row.high for row in minutes),
        low=min(row.low for row in minutes),
        close=minutes[-1].close + 1,
        volume=sum(row.volume for row in minutes) + 500,
    )

    result = reconcile_session(
        official,
        minutes,
        symbol="TEST",
        reconciled_at=datetime(2026, 9, 9, 10, 30, tzinfo=UTC),
    )

    assert result.status == "matched"
    assert result.ohlc_matches is False
    assert "official_close_not_last_minute" in result.notes
    assert "closing_auction_volume_not_in_regular_minutes" in result.notes
