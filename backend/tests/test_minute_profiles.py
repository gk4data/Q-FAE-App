from datetime import datetime, timedelta, timezone

from types import SimpleNamespace

from app.models.market import Candle, MinuteOfDayProfile
from app.services.market_runtime import MarketRuntime
from app.services.market_state import InMemoryMarketStateStore
from app.services.minute_profiles import build_minute_profiles, minute_of_session

IST = timezone(timedelta(hours=5, minutes=30))


def candle(day: int, hour: int, minute: int, volume: int, close: float = 101) -> Candle:
    return Candle(
        instrument_key="NSE_EQ|TEST",
        timestamp=datetime(2026, 9, day, hour, minute, tzinfo=IST),
        open=100,
        high=102,
        low=99,
        close=close,
        volume=volume,
    )


def test_minute_of_session_uses_regular_nse_boundaries() -> None:
    assert minute_of_session(datetime(2026, 9, 1, 9, 15, tzinfo=IST)) == 0
    assert minute_of_session(datetime(2026, 9, 1, 15, 29, tzinfo=IST)) == 374
    assert minute_of_session(datetime(2026, 9, 1, 15, 30, tzinfo=IST)) is None


def test_profile_aggregates_prior_sessions_and_excludes_live_day() -> None:
    candles = [
        candle(1, 9, 30, 100),
        candle(2, 9, 30, 200),
        candle(3, 9, 30, 300),
        candle(4, 9, 30, 10_000),
    ]

    profiles = build_minute_profiles(
        candles,
        exclude_session_date=datetime(2026, 9, 4, tzinfo=IST).date(),
        calculated_at=datetime(2026, 9, 4, 10, 0, tzinfo=IST),
    )

    assert len(profiles) == 1
    profile = profiles[0]
    assert profile.minute_of_session == 15
    assert profile.sample_count == 3
    assert profile.mean_volume == 200
    assert profile.median_volume == 200
    assert profile.volume_p25 == 150
    assert profile.volume_p75 == 250
    assert profile.data_through == candles[2].timestamp


def test_profile_ignores_daily_and_out_of_session_candles() -> None:
    daily = candle(1, 9, 30, 100).model_copy(update={"interval": "day"})
    outside = candle(1, 15, 30, 100)

    assert build_minute_profiles([daily, outside]) == []


def test_runtime_rvol_uses_profile_median_after_minimum_samples() -> None:
    completed = candle(4, 9, 30, 500)
    profile = MinuteOfDayProfile(
        instrument_key=completed.instrument_key,
        minute_of_session=15,
        sample_count=10,
        mean_volume=220,
        median_volume=250,
        volume_stddev=50,
        volume_p25=180,
        volume_p75=280,
        data_through=candle(3, 9, 30, 200).timestamp,
        updated_at=datetime(2026, 9, 4, 9, 31, tzinfo=IST),
    )

    class Repository:
        @staticmethod
        def get_minute_profile(*_args):
            return profile

    runtime = MarketRuntime(
        settings=SimpleNamespace(qfae_minute_profile_min_samples=5),
        state_store=InMemoryMarketStateStore(),
        universe_service=SimpleNamespace(),
        historical_repository=Repository(),
    )

    assert runtime._profile_relative_volume(completed) == 2.0
