from datetime import UTC, datetime, timedelta, timezone

from app.models.market import Candle, LiveSnapshot, RelativeVolumeMetric
from app.services.market_features import build_stock_features, sector_index_for
from app.services.upstox_market import NIFTY_50_KEY

IST = timezone(timedelta(hours=5, minutes=30))


def make_candle(
    key: str,
    timestamp: datetime,
    open_price: float,
    close: float,
    volume: int,
) -> Candle:
    return Candle(
        instrument_key=key,
        timestamp=timestamp,
        open=open_price,
        high=max(open_price, close) + 0.05,
        low=min(open_price, close) - 0.05,
        close=close,
        volume=volume,
    )


def test_feature_engine_builds_all_approved_minute_feature_groups() -> None:
    key = "NSE_EQ|TEST"
    history = []
    for offset in range(14, 0, -1):
        session_date = datetime(2026, 9, 8, tzinfo=IST) - timedelta(days=offset)
        history.append(
            make_candle(
                key,
                session_date.replace(hour=15, minute=29),
                99,
                100,
                1000,
            )
        )

    session = []
    start = datetime(2026, 9, 8, 9, 15, tzinfo=IST)
    for index in range(31):
        open_price = 102 + index * 0.1
        session.append(
            make_candle(
                key,
                start + timedelta(minutes=index),
                open_price,
                open_price + 0.08,
                int(100 * (1.2**index)),
            )
        )
    history.extend(session)
    current = session[-1]
    as_of = datetime(2026, 9, 8, 9, 46, tzinfo=IST)
    snapshot = LiveSnapshot(
        instrument_key=key,
        symbol="TEST",
        received_at=as_of.astimezone(UTC),
        ltp=current.close,
        previous_close=100,
        total_traded_volume=200_000,
        best_bid_price=current.close - 0.05,
        best_ask_price=current.close + 0.05,
        total_buy_quantity=120_000,
        total_sell_quantity=80_000,
        current_candle=make_candle(key, as_of, current.close, current.close, 10),
    )
    snapshots = {
        key: snapshot,
        NIFTY_50_KEY: LiveSnapshot(
            instrument_key=NIFTY_50_KEY,
            symbol="NIFTY 50",
            received_at=as_of.astimezone(UTC),
            ltp=25_250,
            previous_close=25_000,
        ),
        "NSE_INDEX|Nifty Auto": LiveSnapshot(
            instrument_key="NSE_INDEX|Nifty Auto",
            symbol="NIFTY AUTO",
            received_at=as_of.astimezone(UTC),
            ltp=20_100,
            previous_close=20_000,
        ),
    }
    rvol = RelativeVolumeMetric(
        instrument_key=key,
        relative_volume=2.25,
        candle_timestamp=current.timestamp,
        calculated_at=as_of,
    )

    features = build_stock_features(
        snapshot,
        current,
        history,
        snapshots,
        "Auto Ancillary",
        rvol,
        as_of=as_of,
    )

    assert features.vwap.state == "above"
    assert features.vwap.slope_5m_percent_per_minute is not None
    assert features.gap.gap_percent == 2
    assert features.gap.retention_percent is not None
    assert [opening_range.ready for opening_range in features.opening_ranges] == [True, True, True]
    assert all(opening_range.position == "above" for opening_range in features.opening_ranges)
    assert features.relative_strength.versus_nifty_percent is not None
    assert features.relative_strength.sector_index == "Nifty Auto"
    assert features.momentum.state == "strong_up"
    assert features.volume.relative_volume == 2.25
    assert features.volume.acceleration_ratio is not None
    assert features.pullback.quality == "holding_extreme"
    assert features.volatility.atr_sessions == 14
    assert features.volatility.atr is not None
    assert features.liquidity.state == "pass"
    assert features.liquidity.depth_imbalance == 0.2


def test_sector_mapping_is_explicit_and_can_remain_unavailable() -> None:
    assert sector_index_for("Diamond, Gems and Jewellery") == (
        "NSE_INDEX|NIFTY CONSR DURBL",
        "Nifty Consumer Durables",
    )
    assert sector_index_for("Miscellaneous") is None
