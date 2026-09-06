from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.models.market import Candle, LiveSnapshot
from app.services.market_context import build_market_context, calculate_relative_volume
from app.services.market_state import InMemoryMarketStateStore
from app.services.upstox_market import (
    INDIA_VIX_KEY,
    NIFTY_50_KEY,
    NIFTY_BANK_KEY,
    UpstoxMarketDataError,
    keep_latest_sessions,
    normalize_feed_message,
    parse_candle_rows,
)

IST = timezone(timedelta(hours=5, minutes=30))


def candle(instrument_key: str, timestamp: datetime, volume: int) -> Candle:
    return Candle(
        instrument_key=instrument_key,
        timestamp=timestamp,
        open=100,
        high=102,
        low=99,
        close=101,
        volume=volume,
    )


def test_parse_candles_and_keep_latest_sessions() -> None:
    rows = [
        ["2026-09-01T09:15:00+05:30", 100, 102, 99, 101, 1200, 0],
        ["2026-09-02T09:15:00+05:30", 101, 103, 100, 102, 1400, 0],
    ]
    parsed = parse_candle_rows("NSE_EQ|TEST", rows)

    assert parsed[0].volume == 1200
    assert keep_latest_sessions(parsed, 1) == [parsed[1]]


def test_invalid_candle_contract_is_rejected() -> None:
    with pytest.raises(UpstoxMarketDataError):
        parse_candle_rows("NSE_EQ|TEST", [["2026-09-01", 100]])


def test_full_feed_message_is_normalized() -> None:
    message = {
        "currentTs": "1788493625000",
        "feeds": {
            "NSE_EQ|TEST": {
                "fullFeed": {
                    "marketFF": {
                        "ltpc": {"ltp": 101.5, "ltt": "1788493624000", "ltq": "25", "cp": 99.5},
                        "marketLevel": {
                            "bidAskQuote": [{"bidP": 101.45, "bidQ": "100", "askP": 101.55, "askQ": "80"}]
                        },
                        "marketOHLC": {
                            "ohlc": [
                                {
                                    "interval": "I1",
                                    "open": 101,
                                    "high": 102,
                                    "low": 100.8,
                                    "close": 101.5,
                                    "vol": "7250",
                                    "ts": "1788493560000",
                                }
                            ]
                        },
                        "atp": 100.75,
                        "vtt": "200000",
                        "tbq": "50000",
                        "tsq": "45000",
                    }
                }
            }
        },
    }

    snapshots = normalize_feed_message(message, {"NSE_EQ|TEST": "TEST"})

    assert len(snapshots) == 1
    assert snapshots[0].symbol == "TEST"
    assert snapshots[0].ltp == 101.5
    assert snapshots[0].best_ask_price == 101.55
    assert snapshots[0].current_candle is not None
    assert snapshots[0].current_candle.volume == 7250


def test_relative_volume_uses_same_minute_from_prior_sessions() -> None:
    key = "NSE_EQ|TEST"
    current = candle(key, datetime(2026, 9, 4, 9, 30, tzinfo=IST), 3000)
    history = [
        candle(key, datetime(2026, 9, 1, 9, 30, tzinfo=IST), 1000),
        candle(key, datetime(2026, 9, 2, 9, 30, tzinfo=IST), 2000),
        candle(key, datetime(2026, 9, 3, 9, 31, tzinfo=IST), 9000),
        current,
    ]

    assert calculate_relative_volume(current, history) == 2.0


def test_market_context_calculates_breadth_benchmarks_sectors_and_spread() -> None:
    now = datetime(2026, 9, 4, 4, 5, tzinfo=UTC)

    def snapshot(key: str, symbol: str, ltp: float, previous_close: float) -> LiveSnapshot:
        return LiveSnapshot(
            instrument_key=key,
            symbol=symbol,
            received_at=now,
            ltp=ltp,
            previous_close=previous_close,
            best_bid_price=ltp - 0.05,
            best_ask_price=ltp + 0.05,
        )

    snapshots = [
        snapshot("NSE_EQ|AAA", "AAA", 101, 100),
        snapshot("NSE_EQ|BBB", "BBB", 98, 100),
        snapshot(NIFTY_50_KEY, "NIFTY 50", 25100, 25000),
        snapshot(NIFTY_BANK_KEY, "NIFTY BANK", 51000, 51200),
        snapshot(INDIA_VIX_KEY, "INDIA VIX", 13, 12.5),
    ]

    context = build_market_context(
        snapshots,
        {"NSE_EQ|AAA": "Banks", "NSE_EQ|BBB": "Banks"},
        as_of=now,
    )

    assert context.advancers == 1
    assert context.decliners == 1
    assert context.advance_decline_ratio == 1
    assert context.nifty_50.direction == "up"
    assert context.nifty_bank.direction == "down"
    assert context.sectors[0].sector == "Banks"
    assert context.median_spread_bps is not None


def test_in_memory_store_replaces_an_updating_minute_candle() -> None:
    store = InMemoryMarketStateStore()
    timestamp = datetime(2026, 9, 4, 9, 30, tzinfo=IST)
    store.save_candles([candle("NSE_EQ|TEST", timestamp, 100)])
    store.save_candles([candle("NSE_EQ|TEST", timestamp, 250)])

    stored = store.get_candles("NSE_EQ|TEST")
    assert len(stored) == 1
    assert stored[0].volume == 250
