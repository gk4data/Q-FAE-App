from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
import threading

import pytest

from app.models.market import Candle, LiveSnapshot, RelativeVolumeMetric
from app.services.market_context import build_market_context, calculate_relative_volume
from app.services.market_runtime import (
    MarketRuntime,
    completed_regular_session_candles,
    nse_market_close_at,
    opportunity_display_values,
    readable_company_name,
)
from app.services.market_state import InMemoryMarketStateStore
from app.services.upstox_market import (
    INDIA_VIX_KEY,
    NIFTY_50_KEY,
    NIFTY_BANK_KEY,
    UpstoxMarketDataClient,
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

    daily = parse_candle_rows("NSE_EQ|TEST", rows, interval="day")
    assert daily[0].interval == "day"


def test_invalid_candle_contract_is_rejected() -> None:
    with pytest.raises(UpstoxMarketDataError):
        parse_candle_rows("NSE_EQ|TEST", [["2026-09-01", 100]])


def test_readable_company_names_prefer_familiar_names_over_cryptic_symbols() -> None:
    assert readable_company_name("HEXT", "HEXAWARE TECHNOLOGIES LTD") == "Hexaware"
    assert readable_company_name("NETWEB", "NETWEB TECH INDIA LTD", "Netweb Tech India") == "Netweb"
    assert readable_company_name("KAYNES", "KAYNES TECHNOLOGY IND LTD", "Kaynes Technology") == "Kaynes"
    assert readable_company_name("INFY", "INFOSYS LIMITED", "Infosys") == "Infosys"


def test_opportunity_display_uses_latest_ltp_for_cmp_return_and_trace() -> None:
    feature = SimpleNamespace(
        candle_timestamp=datetime(2026, 10, 9, 15, 22, tzinfo=IST),
        session_price_trace=[18.99, 19.29, 19.98],
        relative_strength=SimpleNamespace(session_return_percent=6.7878),
    )
    snapshot = LiveSnapshot(
        instrument_key="NSE_EQ|TEST",
        symbol="TEST",
        received_at=datetime(2026, 10, 9, 15, 29, tzinfo=IST),
        ltp=19.02,
        previous_close=18.71,
        session_candle=Candle(
            instrument_key="NSE_EQ|TEST",
            timestamp=datetime(2026, 10, 9, 0, 0, tzinfo=IST),
            interval="day",
            open=19.0,
            high=20.5,
            low=18.52,
            close=19.98,
            volume=25_675,
        ),
    )

    price, session_return, session_candle, trace = opportunity_display_values(feature, snapshot)

    assert price == 19.02
    assert session_return == 1.6569
    assert session_candle is not None
    assert session_candle.close == 19.02
    assert (session_candle.open, session_candle.high, session_candle.low) == (19.0, 20.5, 18.52)
    assert trace == [18.99, 19.29, 19.98, 19.02]


def test_current_session_daily_candle_uses_intraday_v3_endpoint() -> None:
    requested: list[str] = []
    client = object.__new__(UpstoxMarketDataClient)
    client._get = lambda path: (
        requested.append(path)
        or {
            "data": {
                "candles": [
                    ["2026-09-15T00:00:00+05:30", 100, 105, 98, 104, 250_000, 0]
                ]
            }
        }
    )

    result = client.fetch_intraday_daily_candle("NSE_EQ|TEST KEY")

    assert requested == [
        "/v3/historical-candle/intraday/NSE_EQ%7CTEST%20KEY/days/1"
    ]
    assert result is not None
    assert result.interval == "day"
    assert result.close == 104
    assert result.volume == 250_000


def test_current_session_minute_candles_use_intraday_v3_endpoint() -> None:
    requested: list[str] = []
    client = object.__new__(UpstoxMarketDataClient)
    client._get = lambda path: (
        requested.append(path)
        or {
            "data": {
                "candles": [
                    ["2026-09-15T09:16:00+05:30", 101, 103, 100, 102, 2_000, 0],
                    ["2026-09-15T09:15:00+05:30", 100, 102, 99, 101, 1_000, 0],
                ]
            }
        }
    )

    result = client.fetch_intraday_minute_history("NSE_EQ|TEST KEY")

    assert requested == [
        "/v3/historical-candle/intraday/NSE_EQ%7CTEST%20KEY/minutes/1"
    ]
    assert [item.timestamp.minute for item in result] == [15, 16]
    assert all(item.interval == "1minute" for item in result)


def test_nse_market_session_uses_provider_timings_and_detects_closed_day() -> None:
    requested: list[str] = []
    client = object.__new__(UpstoxMarketDataClient)
    client._get = lambda path: (
        requested.append(path)
        or {
            "data": [
                {
                    "exchange": "NSE",
                    "start_time": 1_789_353_900_000,
                    "end_time": 1_789_376_400_000,
                }
            ]
        }
    )

    session = client.fetch_nse_market_session(datetime(2026, 9, 15).date())

    assert requested == ["/v2/market/timings/2026-09-15"]
    assert session is not None
    assert session[0].tzinfo is not None
    assert session[1] > session[0]

    client._get = lambda _path: {"data": []}
    assert client.fetch_nse_market_session(datetime(2026, 9, 13).date()) is None


def test_pre_open_preparation_arms_live_start_for_market_open(monkeypatch) -> None:
    scheduled: list[object] = []

    class Timer:
        def __init__(self, delay, callback, args=()):
            self.delay = delay
            self.callback = callback
            self.args = args
            self.name = ""
            self.daemon = False
            self.started = False
            self.cancelled = False
            scheduled.append(self)

        def start(self):
            self.started = True

        def cancel(self):
            self.cancelled = True

    runtime = MarketRuntime(
        settings=SimpleNamespace(),
        state_store=InMemoryMarketStateStore(),
        universe_service=SimpleNamespace(),
    )
    monkeypatch.setattr("app.services.market_runtime.threading.Timer", Timer)
    monkeypatch.setattr(runtime, "_require_access_token", lambda: "token")
    started: list[tuple[object, object]] = []
    monkeypatch.setattr(
        runtime,
        "start_live",
        lambda **kwargs: started.append(
            (kwargs["prepared_instruments"], kwargs["session_window"])
        ) or {"state": "connecting"},
    )
    instruments = [{"instrument_key": "NSE_EQ|TEST", "symbol": "TEST"}]
    now = datetime(2026, 9, 15, 8, 0, tzinfo=IST)
    market_open = datetime(2026, 9, 15, 9, 15, tzinfo=IST)
    market_close = datetime(2026, 9, 15, 15, 30, tzinfo=IST)

    result = runtime.arm_or_start_live(
        prepared_instruments=instruments,
        now=now,
        session_window=(market_open, market_close),
    )

    assert result["state"] == "scheduled"
    assert result["scheduled_start_at"] == market_open.isoformat()
    assert len(scheduled) == 1
    assert scheduled[0].delay == 75 * 60
    assert scheduled[0].started is True
    assert started == []

    scheduled[0].callback(*scheduled[0].args)
    assert started == [(instruments, (market_open, market_close))]


def test_prepared_live_starts_immediately_during_market_hours(monkeypatch) -> None:
    runtime = MarketRuntime(
        settings=SimpleNamespace(),
        state_store=InMemoryMarketStateStore(),
        universe_service=SimpleNamespace(),
    )
    monkeypatch.setattr(runtime, "_require_access_token", lambda: "token")
    started: list[dict[str, object]] = []
    monkeypatch.setattr(
        runtime,
        "start_live",
        lambda **kwargs: started.append(kwargs) or {"state": "connecting"},
    )
    instruments = [{"instrument_key": "NSE_EQ|TEST", "symbol": "TEST"}]
    now = datetime(2026, 9, 15, 11, 0, tzinfo=IST)
    session = (
        datetime(2026, 9, 15, 9, 15, tzinfo=IST),
        datetime(2026, 9, 15, 15, 30, tzinfo=IST),
    )

    result = runtime.arm_or_start_live(
        prepared_instruments=instruments,
        now=now,
        session_window=session,
    )

    assert result == {"state": "connecting"}
    assert started[0]["prepared_instruments"] == instruments
    assert started[0]["now"] == now
    assert started[0]["session_window"] == session


def test_session_backfill_keeps_regular_hours_and_completed_minutes_only() -> None:
    key = "NSE_EQ|TEST"
    session_date = datetime(2026, 9, 15, tzinfo=IST).date()
    candles = [
        candle(key, datetime(2026, 9, 14, 15, 29, tzinfo=IST), 100),
        candle(key, datetime(2026, 9, 15, 9, 14, tzinfo=IST), 100),
        candle(key, datetime(2026, 9, 15, 9, 15, tzinfo=IST), 100),
        candle(key, datetime(2026, 9, 15, 10, 59, tzinfo=IST), 100),
        candle(key, datetime(2026, 9, 15, 11, 0, tzinfo=IST), 100),
    ]

    result = completed_regular_session_candles(
        candles,
        session_date,
        datetime(2026, 9, 15, 11, 0, 42, tzinfo=IST),
    )

    assert [item.timestamp.strftime("%H:%M") for item in result] == ["09:15", "10:59"]


def test_session_backfill_merges_into_cache_and_database(monkeypatch) -> None:
    key = "NSE_EQ|TEST"
    session_date = datetime(2026, 9, 15, tzinfo=IST).date()
    downloaded = [
        candle(key, datetime(2026, 9, 15, 9, 15, tzinfo=IST), 100),
        candle(key, datetime(2026, 9, 15, 9, 16, tzinfo=IST), 200),
    ]

    class Client:
        def __init__(self, *_args):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        @staticmethod
        def fetch_intraday_minute_history(instrument_key: str) -> list[Candle]:
            assert instrument_key == key
            return downloaded

    class Repository:
        def __init__(self):
            self.saved: list[Candle] = []

        def upsert_candles(self, candles):
            self.saved.extend(candles)
            return len(self.saved)

    repository = Repository()
    store = InMemoryMarketStateStore()
    runtime = MarketRuntime(
        settings=SimpleNamespace(
            qfae_market_request_rate_per_second=8,
            qfae_market_request_rate_per_minute=450,
        ),
        state_store=store,
        universe_service=SimpleNamespace(),
        historical_repository=repository,
    )
    cancel_event = threading.Event()
    runtime._session_backfill_cancel = cancel_event
    runtime._symbols = {key: "TEST"}
    runtime._live.update(
        {
            "backfill_state": "running",
            "backfill_total": 1,
            "backfill_processed": 0,
            "backfill_instruments_loaded": 0,
            "backfill_candles_loaded": 0,
            "backfill_errors": 0,
            "backfill_recent_errors": [],
        }
    )
    monkeypatch.setattr("app.services.market_runtime.UpstoxMarketDataClient", Client)
    monkeypatch.setattr(runtime, "_require_access_token", lambda: "token")

    runtime._run_session_backfill([key], session_date, cancel_event)

    assert store.get_candles(key) == downloaded
    assert repository.saved == downloaded
    assert runtime._live["backfill_state"] == "completed"
    assert runtime._live["backfill_processed"] == 1
    assert runtime._live["backfill_candles_loaded"] == 2


def test_admission_cache_hydrates_daily_history_in_bounded_batches() -> None:
    instruments = [
        {"instrument_key": f"NSE_EQ|{index}", "symbol": f"STOCK{index}"}
        for index in range(5)
    ]

    class Repository:
        def __init__(self) -> None:
            self.batches: list[list[str]] = []

        @staticmethod
        def get_profile_instrument_keys(_keys):
            return {"NSE_EQ|0", "NSE_EQ|1"}

        def get_candles_many(self, keys, interval, limit):
            assert interval == "day"
            assert limit == 25
            self.batches.append(list(keys))
            return {
                key: [
                    candle(
                        key,
                        datetime(2026, 9, 14, tzinfo=IST),
                        1_000,
                    ).model_copy(update={"interval": "day"})
                ]
                for key in keys
            }

    repository = Repository()
    store = InMemoryMarketStateStore()
    runtime = MarketRuntime(
        settings=SimpleNamespace(
            qfae_bootstrap_batch_size=2,
            qfae_bootstrap_admission_history_sessions=25,
        ),
        state_store=store,
        universe_service=SimpleNamespace(),
        historical_repository=repository,
    )

    runtime._hydrate_daily_admission_cache(instruments)

    assert repository.batches == [
        ["NSE_EQ|0", "NSE_EQ|1"],
        ["NSE_EQ|2", "NSE_EQ|3"],
        ["NSE_EQ|4"],
    ]
    assert runtime._bootstrap["daily_history_loaded"] == 5
    assert runtime._bootstrap["minute_profiles_built"] == 2


def test_financial_refresh_batch_prioritises_never_checked_then_oldest() -> None:
    instruments = [
        {"instrument_key": "NSE_EQ|NEW", "symbol": "NEW"},
        {"instrument_key": "NSE_EQ|RECENT", "symbol": "RECENT"},
        {"instrument_key": "NSE_EQ|OLD", "symbol": "OLD"},
    ]

    class Repository:
        @staticmethod
        def get_financial_result_recency(_keys):
            return {
                "NSE_EQ|RECENT": datetime(2026, 9, 14, tzinfo=UTC),
                "NSE_EQ|OLD": datetime(2026, 8, 1, tzinfo=UTC),
            }

    runtime = MarketRuntime(
        settings=SimpleNamespace(),
        state_store=InMemoryMarketStateStore(),
        universe_service=SimpleNamespace(),
        historical_repository=Repository(),
    )

    selected = runtime._financial_refresh_batch(instruments, 2)

    assert [item["symbol"] for item in selected] == ["NEW", "OLD"]


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
                                },
                                {
                                    "interval": "1d",
                                    "open": 99.5,
                                    "high": 103,
                                    "low": 98.75,
                                    "close": 101.5,
                                    "vol": "200000",
                                    "ts": "1788451200000",
                                },
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
    assert snapshots[0].session_candle is not None
    assert snapshots[0].session_candle.interval == "day"
    assert snapshots[0].session_candle.open == 99.5
    assert snapshots[0].session_candle.high == 103
    assert snapshots[0].session_candle.low == 98.75
    assert snapshots[0].session_candle.close == 101.5


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


def test_market_context_rvol_leaders_are_enriched_with_readable_company_names() -> None:
    now = datetime(2026, 9, 4, 4, 5, tzinfo=UTC)
    key = "NSE_EQ|INE093A01041"
    snapshot = LiveSnapshot(
        instrument_key=key,
        symbol="HEXT",
        received_at=now,
        ltp=500,
        previous_close=490,
        completed_candle_relative_volume=3.5,
        completed_candle_timestamp=now,
    )
    store = InMemoryMarketStateStore()
    store.save_context(build_market_context([snapshot], {}, as_of=now))
    universe = {
        "instruments": [
            {
                "status": "excluded_share_price",
                "requested_name": "HEXAWARE TECHNOLOGIES LTD",
                "candidate": {
                    "instrument_key": key,
                    "trading_symbol": "HEXT",
                    "name": "HEXAWARE TECHNOLOGIES LTD",
                    "short_name": None,
                },
            }
        ]
    }
    runtime = MarketRuntime(
        settings=SimpleNamespace(),
        state_store=store,
        universe_service=SimpleNamespace(load=lambda: universe),
    )

    context = runtime.get_market_context()

    assert context is not None
    assert context.relative_volume_leaders[0].company_name == "HEXAWARE TECHNOLOGIES LTD"
    assert context.relative_volume_leaders[0].display_name == "Hexaware"


def test_in_memory_store_replaces_an_updating_minute_candle() -> None:
    store = InMemoryMarketStateStore()
    timestamp = datetime(2026, 9, 4, 9, 30, tzinfo=IST)
    store.save_candles([candle("NSE_EQ|TEST", timestamp, 100)])
    store.save_candles([candle("NSE_EQ|TEST", timestamp, 250)])

    stored = store.get_candles("NSE_EQ|TEST")
    assert len(stored) == 1
    assert stored[0].volume == 250


def test_watchlist_defaults_to_full_approved_universe_and_marks_stale_snapshot_cached() -> None:
    instruments = [
        {
            "requested_name": f"Company {index}",
            "status": "resolved",
            "candidate": {
                "instrument_key": f"NSE_EQ|{index}",
                "trading_symbol": f"STOCK{index}",
                "isin": f"ISIN{index}",
                "instrument_type": "EQ",
            },
        }
        for index in range(12)
    ]

    class UniverseService:
        @staticmethod
        def load() -> dict[str, list[dict[str, object]]]:
            return {"instruments": instruments}

    class TrackingStore(InMemoryMarketStateStore):
        def __init__(self) -> None:
            super().__init__()
            self.requested_candle_limits: list[int] = []

        def get_candles(self, instrument_key: str, limit: int = 500) -> list[Candle]:
            self.requested_candle_limits.append(limit)
            return super().get_candles(instrument_key, limit)

        def get_candles_many(self, instrument_keys, limit: int = 500):
            self.requested_candle_limits.append(limit)
            return super().get_candles_many(instrument_keys, limit)

    store = TrackingStore()
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
            best_bid_price=104,
            best_ask_price=98,
            current_candle=current,
        )
    )
    runtime = MarketRuntime(
        settings=SimpleNamespace(qfae_market_history_days=14),
        state_store=store,
        universe_service=UniverseService(),
    )

    rows = runtime.get_watchlist()

    assert len(rows) == 12
    assert rows[0].symbol == "STOCK0"
    assert rows[0].change_percent == 1
    assert rows[0].relative_volume == 2.5
    assert rows[0].spread_bps is None
    assert rows[0].data_state == "cached"
    assert store.requested_candle_limits
    assert max(store.requested_candle_limits) == 1


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


def test_after_market_reconciliation_is_scheduled_ten_minutes_after_close(monkeypatch) -> None:
    scheduled: list[object] = []

    class FakeTimer:
        def __init__(self, delay, callback, args=()):
            self.delay = delay
            self.callback = callback
            self.args = args
            self.name = ""
            self.daemon = False
            self.started = False
            self.cancelled = False
            scheduled.append(self)

        def start(self):
            self.started = True

        def cancel(self):
            self.cancelled = True

    monkeypatch.setattr("app.services.market_runtime.threading.Timer", FakeTimer)
    runtime = MarketRuntime(
        settings=SimpleNamespace(qfae_reconciliation_delay_minutes=10),
        state_store=InMemoryMarketStateStore(),
        universe_service=SimpleNamespace(),
    )
    now = datetime(2026, 9, 8, 15, 0, tzinfo=IST)
    market_close = nse_market_close_at(now)

    runtime._schedule_after_market_reconciliation(market_close, now)

    assert len(scheduled) == 1
    assert scheduled[0].delay == 40 * 60
    assert scheduled[0].started is True
    assert runtime._reconciliation["state"] == "scheduled"
    assert runtime._reconciliation["next_attempt_at"] == "2026-09-08T15:40:00+05:30"


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


def test_full_provider_universe_is_preserved_and_instrument_keys_are_unique() -> None:
    def row(
        symbol: str,
        key: str,
        *,
        instrument_type: str = "EQ",
    ) -> dict[str, object]:
        return {
            "requested_name": symbol,
            "status": "resolved",
            "candidate": {
                "instrument_key": key,
                "trading_symbol": symbol,
                "isin": f"ISIN-{symbol}",
                "instrument_type": instrument_type,
            },
        }

    universe = {
        "instruments": [
            row("ORDINARY_A", "NSE_EQ|A"),
            row("SECOND", "NSE_EQ|P"),
            row("SME", "NSE_EQ|SME", instrument_type="SM"),
            row("PRIORITY_DUPLICATE", "NSE_EQ|P"),
            row("ORDINARY_B", "NSE_EQ|B"),
        ]
    }
    runtime = MarketRuntime(
        settings=SimpleNamespace(),
        state_store=InMemoryMarketStateStore(),
        universe_service=SimpleNamespace(load=lambda: universe),
    )

    selected = runtime._resolved_instruments(None)

    assert [item["symbol"] for item in selected] == ["ORDINARY_A", "SECOND", "ORDINARY_B"]
