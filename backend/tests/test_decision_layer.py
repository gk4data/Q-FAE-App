from datetime import UTC, datetime, timedelta, timezone

from app.models.market import (
    BenchmarkState,
    Candle,
    FlowLiquidityConfirmation,
    LiveSnapshot,
    MarketContext,
    MarketDepthLevel,
    OpportunityEvidenceSnapshot,
    SectorIndexState,
    SignalPersistenceSnapshot,
    StockFeatureSnapshot,
)
from app.services.evidence_outcomes import evaluate_observation
from app.services.market_regime import build_market_regime
from app.services.risk_gates import build_risk_assessment, estimate_slippage_bps
from app.services.signal_persistence import build_signal_persistence
from app.models.market import EvidenceOutcomeObservation

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 9, 8, 10, 0, tzinfo=IST)


def evidence(confluence: str, minute: int) -> OpportunityEvidenceSnapshot:
    return OpportunityEvidenceSnapshot.model_validate(
        {
            "instrument_key": "NSE_EQ|TEST", "symbol": "TEST", "as_of": NOW + timedelta(minutes=minute),
            "data_quality": "complete", "confluence": confluence, "pillars": [],
            "flow_liquidity": {
                "instrument_key": "NSE_EQ|TEST", "symbol": "TEST", "as_of": NOW,
                "data_quality": "complete", "volume_state": "active", "liquidity_state": "pass",
                "confirmation": "confirmed",
            },
        }
    )


def test_signal_requires_two_of_last_three_supportive_minutes() -> None:
    first = build_signal_persistence(evidence("supportive", 0), [])
    confirmed = build_signal_persistence(evidence("supportive", 1), [evidence("supportive", 0)], first)
    weakening = build_signal_persistence(evidence("mixed", 2), [evidence("supportive", 0), evidence("supportive", 1)], confirmed)

    assert first.state == "building"
    assert confirmed.state == "confirmed"
    assert weakening.state == "confirmed"  # two of the rolling three still support it


def test_market_regime_uses_persistent_breadth_and_sector_participation() -> None:
    benchmark = BenchmarkState(instrument_key="NSE_INDEX|Nifty 50", change_percent=0.5, direction="up", updated_at=NOW, fresh=True)
    vix = BenchmarkState(instrument_key="NSE_INDEX|India VIX", change_percent=-2, direction="down", updated_at=NOW, fresh=True)
    sectors = [SectorIndexState(sector=f"S{i}", instrument_key=f"IDX{i}", change_percent=1 if i < 8 else -1, direction="up", updated_at=NOW, fresh=True) for i in range(10)]
    context = MarketContext(
        as_of=NOW, nifty_50=benchmark, nifty_bank=benchmark, india_vix=vix, sector_indices=sectors,
        universe_size=20, fresh_instruments=20, stale_instruments=0, advancers=14, decliners=6,
        unchanged=0, liquid_instruments=20,
    )
    result = build_market_regime(context, [context.model_copy(update={"as_of": NOW - timedelta(minutes=1)})])

    assert result.state == "risk_on"
    assert result.breadth_persistence == 0.7
    assert result.sector_participation == 0.8
    assert "global_market_context" in result.unavailable_inputs


def test_d5_slippage_and_circuit_gate_are_calculated() -> None:
    snapshot = LiveSnapshot(
        instrument_key="NSE_EQ|TEST", symbol="TEST", received_at=NOW.astimezone(UTC), ltp=100,
        lower_circuit=80, upper_circuit=120,
        market_depth=[MarketDepthLevel(bid_price=99.9, bid_quantity=2000, ask_price=100.1, ask_quantity=2000)],
    )
    feature = StockFeatureSnapshot.model_validate(
        {
            "instrument_key": "NSE_EQ|TEST", "symbol": "TEST", "as_of": NOW.astimezone(UTC),
            "candle_timestamp": NOW - timedelta(minutes=1), "data_quality": "complete",
            "vwap": {}, "gap": {"gap_atr": 0.5}, "opening_ranges": [], "relative_strength": {},
            "momentum": {}, "volume": {}, "pullback": {}, "volatility": {},
            "liquidity": {"spread_bps": 20, "total_traded_value_inr": 20_000_000, "passes_spread_filter": True, "passes_traded_value_filter": True},
        }
    )
    result = build_risk_assessment(feature, snapshot, as_of=NOW.astimezone(UTC), reference_order_value_inr=100_000)

    assert estimate_slippage_bps(snapshot, 100_000, side="buy") == 10
    assert result.eligible is True
    assert result.distance_to_upper_circuit_percent == 20
    assert result.status == "partial"  # surveillance and portfolio budget are explicitly unavailable


def test_forward_outcomes_do_not_use_prices_before_each_horizon() -> None:
    observation = EvidenceOutcomeObservation(
        instrument_key="NSE_EQ|TEST", symbol="TEST", candle_timestamp=NOW,
        observed_at=NOW, reference_price=100, confluence="supportive", signal_state="confirmed",
        data_quality="complete", evidence_payload={},
    )
    candles = [
        Candle(instrument_key="NSE_EQ|TEST", timestamp=NOW + timedelta(minutes=minute), open=100, high=price + 1, low=price - 1, close=price, volume=100)
        for minute, price in ((3, 102), (5, 105), (15, 110), (60, 120))
    ]
    result = evaluate_observation(observation, candles, eod_close=115)

    assert result.forward_return_5m_percent == 5
    assert result.forward_return_15m_percent == 10
    assert result.forward_return_60m_percent == 20
    assert result.forward_return_eod_percent == 15
    assert result.mfe_60m_percent == 21
    assert result.mae_60m_percent == 1
    assert result.outcome_status == "complete"
