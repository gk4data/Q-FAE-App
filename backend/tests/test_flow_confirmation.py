from datetime import datetime, timedelta, timezone

from app.models.market import StockFeatureSnapshot
from app.services.flow_confirmation import build_flow_liquidity_confirmation

IST = timezone(timedelta(hours=5, minutes=30))


def feature(
    *,
    rvol: float | None,
    acceleration: float | None,
    spread_pass: bool | None,
    traded_value_pass: bool | None,
) -> StockFeatureSnapshot:
    as_of = datetime(2026, 9, 9, 10, 0, tzinfo=IST)
    return StockFeatureSnapshot.model_validate(
        {
            "instrument_key": "NSE_EQ|TEST",
            "symbol": "TEST",
            "as_of": as_of,
            "candle_timestamp": as_of - timedelta(minutes=1),
            "data_quality": "complete",
            "vwap": {}, "gap": {}, "opening_ranges": [], "relative_strength": {},
            "momentum": {},
            "volume": {"relative_volume": rvol, "acceleration_ratio": acceleration},
            "pullback": {}, "volatility": {},
            "liquidity": {
                "spread_bps": 8,
                "total_traded_value_inr": 20_000_000,
                "depth_imbalance": 0.2,
                "passes_spread_filter": spread_pass,
                "passes_traded_value_filter": traded_value_pass,
            },
        }
    )


def test_strong_volume_with_passing_liquidity_is_strong_confirmation() -> None:
    result = build_flow_liquidity_confirmation(
        feature(rvol=2, acceleration=1.5, spread_pass=True, traded_value_pass=True)
    )

    assert result.confirmation == "strong_confirmation"
    assert result.volume_state == "strong"
    assert result.liquidity_state == "pass"
    assert "buy_depth_imbalance" in result.evidence


def test_high_volume_cannot_override_a_failed_spread_filter() -> None:
    result = build_flow_liquidity_confirmation(
        feature(rvol=3, acceleration=2, spread_pass=False, traded_value_pass=True)
    )

    assert result.confirmation == "rejected"
    assert "spread_too_wide" in result.cautions


def test_passing_liquidity_without_volume_is_not_confirmation() -> None:
    result = build_flow_liquidity_confirmation(
        feature(rvol=0.5, acceleration=0.6, spread_pass=True, traded_value_pass=True)
    )

    assert result.confirmation == "liquid_but_unconfirmed"
    assert result.volume_state == "weak"


def test_missing_inputs_remain_insufficient() -> None:
    result = build_flow_liquidity_confirmation(
        feature(rvol=None, acceleration=None, spread_pass=None, traded_value_pass=None)
    )

    assert result.confirmation == "insufficient"
    assert result.data_quality == "limited"


def test_acceleration_can_mark_volume_active_before_rvol_rises() -> None:
    result = build_flow_liquidity_confirmation(
        feature(rvol=0.8, acceleration=1.1, spread_pass=True, traded_value_pass=True)
    )

    assert result.volume_state == "active"
    assert result.confirmation == "confirmed"
