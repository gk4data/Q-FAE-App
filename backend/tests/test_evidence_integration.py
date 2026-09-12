from datetime import UTC, datetime, timedelta, timezone

from app.models.market import DailyRegimeSnapshot, StockFeatureSnapshot
from app.services.evidence_integration import build_opportunity_evidence

IST = timezone(timedelta(hours=5, minutes=30))


def test_supportive_intraday_daily_and_relative_inputs_form_confluence() -> None:
    as_of = datetime(2026, 9, 9, 10, 0, tzinfo=IST)
    feature = StockFeatureSnapshot.model_validate(
        {
            "instrument_key": "NSE_EQ|TEST",
            "symbol": "TEST",
            "sector": "Auto Ancillary",
            "as_of": as_of,
            "candle_timestamp": as_of - timedelta(minutes=1),
            "data_quality": "complete",
            "vwap": {"position_percent": 1.2, "slope_5m_percent_per_minute": 0.1, "state": "above"},
            "gap": {"gap_percent": 1, "retention_percent": 90, "state": "retained"},
            "opening_ranges": [{"minutes": 15, "ready": True, "position": "above"}],
            "relative_strength": {"session_return_percent": 2, "versus_nifty_percent": 2.5, "sector_index": "Nifty Auto", "versus_sector_percent": 1.5},
            "momentum": {"return_5m_percent": 0.8, "efficiency_ratio_15m": 0.7, "state": "strong_up"},
            "volume": {"relative_volume": 2, "acceleration_ratio": 1.4, "state": "high_relative"},
            "pullback": {"direction": "up", "quality": "holding_extreme"},
            "volatility": {"atr_sessions": 14, "state": "normal"},
            "liquidity": {"passes_spread_filter": True, "passes_traded_value_filter": True, "state": "pass"},
        }
    )
    regime = DailyRegimeSnapshot.model_validate(
        {
            "instrument_key": "NSE_EQ|TEST",
            "symbol": "TEST",
            "sector": "Auto Ancillary",
            "as_of": as_of,
            "data_through": as_of - timedelta(days=1),
            "sessions_available": 260,
            "data_quality": "complete",
            "horizon_performance": [
                {"sessions": 20, "versus_nifty_percent": 8, "versus_sector_percent": 5},
                {"sessions": 60, "versus_nifty_percent": 12, "versus_sector_percent": 7},
            ],
            "trend": {"alignment": "bullish", "regime": "established_uptrend", "sma_20_slope_5d_percent": 1},
            "structure": {"state": "near_20d_high"},
            "participation": {},
            "volatility": {},
        }
    )

    result = build_opportunity_evidence(
        feature,
        regime,
        None,
        as_of=as_of.astimezone(UTC),
    )

    states = {pillar.key: pillar.state for pillar in result.pillars}
    assert states == {
        "intraday": "supportive",
        "daily": "supportive",
        "relative_strength": "supportive",
        "confirmation": "supportive",
    }
    assert result.confluence == "strong_support"
    assert result.data_quality == "partial"
    assert "market_context_unavailable" in result.validation_notes


def test_stale_intraday_inputs_are_not_classified_as_current_evidence() -> None:
    feature = StockFeatureSnapshot.model_validate(
        {
            "instrument_key": "NSE_EQ|TEST",
            "symbol": "TEST",
            "as_of": datetime(2026, 9, 8, 10, 0, tzinfo=IST),
            "candle_timestamp": datetime(2026, 9, 8, 9, 59, tzinfo=IST),
            "data_quality": "complete",
            "vwap": {}, "gap": {}, "opening_ranges": [], "relative_strength": {},
            "momentum": {}, "volume": {}, "pullback": {}, "volatility": {}, "liquidity": {},
        }
    )

    result = build_opportunity_evidence(
        feature,
        None,
        None,
        as_of=datetime(2026, 9, 9, 10, 0, tzinfo=IST),
    )

    assert result.confluence == "insufficient"
    assert result.pillars[0].state == "unavailable"
    assert "intraday_evidence_stale" in result.validation_notes

