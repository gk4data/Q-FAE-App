from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.models.market import Candle, LiveSnapshot, RelativeVolumeMetric
from app.services.market_context import build_market_context, calculate_relative_volume
from app.services.market_runtime import MarketRuntime, nse_market_close_at
from app.services.market_state import InMemoryMarketStateStore
from app.services.upstox_market import (
    INDIA_VIX_KEY,
    NIFTY_50_KEY,
    NIFTY_BANK_KEY,
    UpstoxMarketDataError,
    keep_latest_sessions,
    normalize_feed_message,
    normalize_corporate_actions,
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

    daily = parse_candle_rows("NSE_EQ|TEST", rows, interval="day")
    assert daily[0].interval == "day"


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
                            "bidAskQuote": [
                                {"bidP": 101.45, "bidQ": "100", "askP": 101.55, "askQ": "80"},
                                {"bidP": 101.40, "bidQ": "200", "askP": 101.60, "askQ": "180"},
                            ]
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
                        "eFeedDetails": {
                            "atp": 100.75,
                            "vtt": "200000",
                            "tbq": "50000",
                            "tsq": "45000",
                            "lc": 80,
                            "uc": 120,
                        },
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
    assert len(snapshots[0].market_depth) == 2
    assert snapshots[0].market_depth[1].ask_quantity == 180
    assert snapshots[0].lower_circuit == 80
    assert snapshots[0].upper_circuit == 120
    assert snapshots[0].current_candle is not None
    assert snapshots[0].current_candle.volume == 7250


def test_corporate_actions_preserve_facts_and_normalize_dates() -> None:
    actions = normalize_corporate_actions(
        "INE000000001",
        "NSE_EQ|INE000000001",
        "TEST",
        [
            {
                "name": "Dividend",
                "expiry_date": "14 Aug 2025",
                "amount": 5.5,
                "ratio": None,
                "event_details": [
                    {"name": "Announcement date", "value": "25 Apr 2025"},
                    {"name": "Ex dividend date", "value": "14 Aug 2025"},
                    {"name": "Record date", "value": "14 Aug 2025"},
                    {"name": "Details", "value": "Final dividend"},
                ],
            }
        ],
        ingested_at=datetime(2026, 9, 12, tzinfo=UTC),
    )

    assert len(actions) == 1
    assert actions[0].action_type == "Dividend"
    assert actions[0].announcement_date.isoformat() == "2025-04-25"
    assert actions[0].ex_date.isoformat() == "2025-08-14"
    assert actions[0].amount == 5.5
    assert actions[0].details["Details"] == "Final dividend"
    assert len(actions[0].event_id) == 32


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
        snapshot("NSE_INDEX|Nifty IT", "NIFTY IT", 41000, 40000),
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
    assert len(context.sector_indices) == 13
    assert context.sector_indices[0].sector == "Nifty IT"
    assert context.sector_indices[0].change_percent == 2.5
    assert context.sector_indices[0].fresh is True
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


def test_watchlist_defaults_to_ten_pilot_stocks_and_marks_stale_snapshot_cached() -> None:
    instruments = [
        {
            "requested_name": f"Company {index}",
            "status": "resolved",
            "candidate": {
                "instrument_key": f"NSE_EQ|{index}",
                "trading_symbol": f"STOCK{index}",
                "isin": f"ISIN{index}",
            },
        }
        for index in range(12)
    ]

    class UniverseService:
        @staticmethod
        def load() -> dict[str, list[dict[str, object]]]:
            return {"instruments": instruments}

    store = InMemoryMarketStateStore()
    completed = candle("NSE_EQ|0", datetime(2026, 9, 8, 9, 30, tzinfo=IST), 250)
    current = candle("NSE_EQ|0", datetime(2026, 9, 8, 9, 31, tzinfo=IST), 100)
    store.save_candles([completed, current])
    store.save_relative_volume(
        RelativeVolumeMetric(
            instrument_key="NSE_EQ|0",
            relative_volume=2.5,
            candle_timestamp=completed.timestamp,
            calculated_at=datetime(2026, 9, 8, 9, 31, tzinfo=IST),
        )
    )
    store.save_snapshot(
        LiveSnapshot(
            instrument_key="NSE_EQ|0",
            symbol="STOCK0",
            received_at=datetime.now(UTC),
            ltp=101,
            previous_close=100,
            current_candle=current,
        )
    )
    runtime = MarketRuntime(
        settings=SimpleNamespace(
            qfae_market_pilot_size=10,
            qfae_market_history_days=14,
        ),
        state_store=store,
        universe_service=UniverseService(),
    )

    rows = runtime.get_watchlist()

    assert len(rows) == 10
    assert rows[0].symbol == "STOCK0"
    assert rows[0].change_percent == 1
    assert rows[0].relative_volume == 2.5
    assert rows[0].data_state == "cached"


def test_previous_session_candle_is_not_used_as_current_session_rvol() -> None:
    previous_close = candle("NSE_EQ|TEST", datetime(2026, 9, 7, 15, 29, tzinfo=IST), 500)
    opening_candle = candle("NSE_EQ|TEST", datetime(2026, 9, 8, 9, 15, tzinfo=IST), 100)
    snapshot = LiveSnapshot(
        instrument_key="NSE_EQ|TEST",
        symbol="TEST",
        received_at=datetime(2026, 9, 8, 9, 15, tzinfo=IST),
        current_candle=opening_candle,
    )

    completed = MarketRuntime._latest_completed_candle(
        snapshot,
        [previous_close, opening_candle],
    )

    assert completed is None


def test_nse_market_close_is_scheduled_for_330_pm_ist() -> None:
    now = datetime(2026, 9, 8, 10, 0, tzinfo=UTC)

    market_close = nse_market_close_at(now)

    assert market_close == datetime(2026, 9, 8, 15, 30, tzinfo=IST)


def test_live_persistence_collects_all_completed_minutes_after_watermark() -> None:
    first = candle("NSE_EQ|TEST", datetime(2026, 9, 8, 9, 15, tzinfo=IST), 100)
    second = candle("NSE_EQ|TEST", datetime(2026, 9, 8, 9, 16, tzinfo=IST), 200)
    forming = candle("NSE_EQ|TEST", datetime(2026, 9, 8, 9, 17, tzinfo=IST), 50)

    class Repository:
        @staticmethod
        def latest_candle_timestamp(*_args):
            return datetime(2026, 9, 7, 15, 29, tzinfo=IST)

    runtime = MarketRuntime(
        settings=SimpleNamespace(),
        state_store=InMemoryMarketStateStore(),
        universe_service=SimpleNamespace(),
        historical_repository=Repository(),
    )
    snapshot = LiveSnapshot(
        instrument_key="NSE_EQ|TEST",
        symbol="TEST",
        received_at=forming.timestamp,
        current_candle=forming,
    )
    pending: dict[tuple[str, datetime], Candle] = {}

    runtime._collect_unpersisted_minutes(snapshot, [first, second, forming], second, pending)

    assert list(pending.values()) == [first, second]
