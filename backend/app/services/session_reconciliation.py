"""Compare captured minute data with the provider's official daily candle."""

from __future__ import annotations

from datetime import date, datetime

from app.models.market import Candle, DailyReconciliationRecord
from app.services.market_context import INDIA_TIMEZONE
from app.services.minute_profiles import minute_of_session

EXPECTED_REGULAR_MINUTES = 375
CLOSING_AUCTION_START_DATE = date(2026, 8, 3)


def reconcile_session(
    official: Candle,
    minute_candles: list[Candle],
    *,
    symbol: str,
    reconciled_at: datetime,
) -> DailyReconciliationRecord:
    """Produce an auditable comparison and never manufacture missing minutes."""
    session_date = official.timestamp.astimezone(INDIA_TIMEZONE).date()
    minutes = sorted(
        (
            candle
            for candle in minute_candles
            if candle.interval == "1minute"
            and candle.timestamp.astimezone(INDIA_TIMEZONE).date() == session_date
            and minute_of_session(candle.timestamp) is not None
        ),
        key=lambda candle: candle.timestamp,
    )
    notes: list[str] = []
    if len(minutes) < EXPECTED_REGULAR_MINUTES:
        notes.append("minute_grid_gaps_no_trade_or_missing")
    if not minutes:
        return DailyReconciliationRecord(
            session_date=session_date,
            instrument_key=official.instrument_key,
            symbol=symbol,
            status="official_only",
            minute_count=0,
            expected_minutes=EXPECTED_REGULAR_MINUTES,
            official_close=official.close,
            official_volume=official.volume,
            notes=notes,
            reconciled_at=reconciled_at,
        )

    aggregate_open = minutes[0].open
    aggregate_high = max(candle.high for candle in minutes)
    aggregate_low = min(candle.low for candle in minutes)
    aggregate_close = minutes[-1].close
    aggregate_volume = sum(candle.volume for candle in minutes)
    open_high_low_match = all(
        _price_matches(captured, expected)
        for captured, expected in (
            (aggregate_open, official.open),
            (aggregate_high, official.high),
            (aggregate_low, official.low),
        )
    )
    close_matches = _price_matches(aggregate_close, official.close)
    prices_match = open_high_low_match and close_matches
    volume_difference = (
        round((aggregate_volume / official.volume - 1) * 100, 4)
        if official.volume > 0
        else None
    )
    volume_matches = volume_difference is not None and abs(volume_difference) <= 1
    closing_auction_volume = (
        session_date >= CLOSING_AUCTION_START_DATE
        and aggregate_volume <= official.volume
    )
    volume_consistent = volume_matches or closing_auction_volume
    if not open_high_low_match:
        notes.append("open_high_low_difference")
    if not close_matches:
        notes.append("official_close_not_last_minute")
    if not volume_matches and closing_auction_volume:
        notes.append("closing_auction_volume_not_in_regular_minutes")
    elif not volume_matches:
        notes.append("volume_difference")
    status = (
        "matched"
        if len(minutes) == EXPECTED_REGULAR_MINUTES and open_high_low_match and volume_consistent
        else "reconciled_with_differences"
    )
    return DailyReconciliationRecord(
        session_date=session_date,
        instrument_key=official.instrument_key,
        symbol=symbol,
        status=status,
        minute_count=len(minutes),
        expected_minutes=EXPECTED_REGULAR_MINUTES,
        official_close=official.close,
        official_volume=official.volume,
        aggregated_close=aggregate_close,
        aggregated_volume=aggregate_volume,
        volume_difference_percent=volume_difference,
        ohlc_matches=prices_match,
        notes=notes,
        reconciled_at=reconciled_at,
    )


def _price_matches(captured: float, official: float) -> bool:
    return abs(captured - official) <= max(0.01, abs(official) * 0.000001)
