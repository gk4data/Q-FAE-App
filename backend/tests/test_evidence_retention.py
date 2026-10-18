from datetime import datetime, timedelta, timezone

from app.models.market import EvidenceOutcomeObservation, OpportunityEvidenceSnapshot
from app.services.evidence_retention import (
    build_compact_evidence_observation,
    compact_checkpoint_due,
    compact_state_key,
    opportunity_priority,
    select_full_evidence_candidates,
)


IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 10, 16, 10, 0, tzinfo=IST)


def _observation(symbol: str, score: float, *, eligible: bool) -> EvidenceOutcomeObservation:
    return EvidenceOutcomeObservation(
        instrument_key=f"NSE_EQ|{symbol}",
        symbol=symbol,
        sector="Technology",
        candle_timestamp=NOW,
        observed_at=NOW,
        reference_price=100,
        confluence="supportive",
        signal_state="confirmed",
        data_quality="complete",
        evidence_payload={
            "opportunity_score": {
                "final_score": score,
                "coverage_percent": 90,
                "eligible": eligible,
            }
        },
    )


def _evidence(symbol: str = "TEST", score: float = 76) -> OpportunityEvidenceSnapshot:
    return OpportunityEvidenceSnapshot.model_validate(
        {
            "instrument_key": f"NSE_EQ|{symbol}",
            "symbol": symbol,
            "sector": "Technology",
            "as_of": NOW,
            "data_quality": "complete",
            "confluence": "strong_support",
            "pillars": [],
            "flow_liquidity": {
                "instrument_key": f"NSE_EQ|{symbol}",
                "symbol": symbol,
                "as_of": NOW,
                "data_quality": "complete",
                "volume_state": "strong",
                "liquidity_state": "pass",
                "confirmation": "strong_confirmation",
            },
            "signal_persistence": {
                "instrument_key": f"NSE_EQ|{symbol}",
                "symbol": symbol,
                "as_of": NOW,
                "state": "confirmed",
                "supportive_minutes": 3,
                "caution_minutes": 0,
                "observed_minutes": 3,
                "reason": "support_repeated",
            },
            "liquidity_tier": "active",
            "market_regime": {
                "as_of": NOW,
                "state": "risk_on",
                "observations": 3,
            },
            "opportunity_score": {
                "model_version": "pilot-v1",
                "strategy": "long_continuation",
                "calibration_status": "provisional",
                "evidence_score": score,
                "coverage_percent": 90,
                "coverage_adjusted_score": score,
                "persistence_multiplier": 1,
                "final_score": score,
                "eligible": True,
                "status": "high_priority",
                "weights": {"price_trend": 30},
                "components": [
                    {
                        "key": "price_trend",
                        "label": "Price trend",
                        "weight_percent": 30,
                        "score": 82,
                        "coverage_percent": 100,
                        "contribution_points": 24.6,
                    }
                ],
            },
        }
    )


def test_full_evidence_is_bounded_and_prioritizes_eligible_candidates() -> None:
    observations = [
        _observation("INELIGIBLE", 99, eligible=False),
        _observation("SECOND", 80, eligible=True),
        _observation("FIRST", 90, eligible=True),
    ]

    selected = select_full_evidence_candidates(observations, maximum=2)

    assert [item.symbol for item in selected] == ["FIRST", "SECOND"]


def test_compact_checkpoints_are_anchored_to_the_nse_open() -> None:
    assert compact_checkpoint_due(NOW.replace(hour=9, minute=15), 15)
    assert compact_checkpoint_due(NOW.replace(hour=9, minute=30), 15)
    assert not compact_checkpoint_due(NOW.replace(hour=9, minute=31), 15)


def test_compact_observation_keeps_decision_fields_without_json_payloads() -> None:
    evidence = _evidence()

    compact = build_compact_evidence_observation(
        evidence,
        candle_timestamp=NOW,
        reference_price=101.5,
        capture_reason="interval",
    )

    assert compact is not None
    assert compact.opportunity_score == 76
    assert compact.price_trend_score == 82
    assert compact.market_regime_state == "risk_on"
    assert compact.capture_reason == "interval"
    assert opportunity_priority(evidence)[:3] == (True, 76, 90)
    assert compact_state_key(evidence, score_bucket=5)[0] == 15
