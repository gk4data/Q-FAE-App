from datetime import datetime, timedelta, timezone

from app.models.market import OpportunityEvidenceSnapshot, StockFeatureSnapshot
from app.services.focus_universe import evaluate_focus_state


IST = timezone(timedelta(hours=5, minutes=30))


def _feature(
    timestamp: datetime,
    *,
    session_return: float,
    supportive: bool,
) -> StockFeatureSnapshot:
    return StockFeatureSnapshot.model_validate(
        {
            "instrument_key": "NSE_EQ|TEST",
            "symbol": "TEST",
            "sector": "Technology",
            "as_of": timestamp + timedelta(minutes=1),
            "candle_timestamp": timestamp,
            "data_quality": "complete",
            "vwap": {
                "state": "above" if supportive else "below",
                "slope_5m_percent_per_minute": 0.08 if supportive else -0.08,
            },
            "gap": {},
            "opening_ranges": [
                {
                    "minutes": 15,
                    "ready": True,
                    "position": "above" if supportive else "inside",
                }
            ],
            "relative_strength": {
                "session_return_percent": session_return,
                "versus_nifty_percent": 1.2 if supportive else -0.7,
                "versus_sector_percent": 0.8 if supportive else -0.5,
            },
            "momentum": {},
            "volume": {
                "relative_volume": 1.4 if supportive else 0.6,
                "acceleration_ratio": 1.2 if supportive else 0.7,
            },
            "pullback": {},
            "volatility": {},
            "liquidity": {},
        }
    )


def _evidence(
    timestamp: datetime,
    *,
    eligible: bool = True,
    score: float = 70,
) -> OpportunityEvidenceSnapshot:
    return OpportunityEvidenceSnapshot.model_validate(
        {
            "instrument_key": "NSE_EQ|TEST",
            "symbol": "TEST",
            "sector": "Technology",
            "as_of": timestamp + timedelta(minutes=1),
            "data_quality": "complete",
            "confluence": "supportive",
            "pillars": [],
            "flow_liquidity": {
                "instrument_key": "NSE_EQ|TEST",
                "symbol": "TEST",
                "as_of": timestamp + timedelta(minutes=1),
                "data_quality": "complete",
                "volume_state": "strong",
                "liquidity_state": "pass",
                "confirmation": "strong_confirmation",
            },
            "liquidity_tier": "active",
            "market_regime": {
                "as_of": timestamp,
                "state": "mixed",
                "observations": 3,
            },
            "opportunity_score": {
                "model_version": "model-v3",
                "strategy": "long_continuation",
                "calibration_status": "provisional",
                "evidence_score": score,
                "coverage_percent": 90,
                "coverage_adjusted_score": score,
                "persistence_multiplier": 1,
                "final_score": score,
                "eligible": eligible,
                "status": "promising" if eligible else "ineligible",
                "weights": {},
                "components": [],
                "invalidation_reasons": [] if eligible else ["risk_gate_rejected:spread"],
            },
        }
    )


def test_red_alone_is_not_a_veto_when_relative_and_intraday_strength_confirm() -> None:
    first_minute = datetime(2026, 10, 16, 9, 30, tzinfo=IST)
    first = evaluate_focus_state(
        _feature(first_minute, session_return=-0.1, supportive=True),
        _evidence(first_minute),
        None,
    )
    second_minute = first_minute + timedelta(minutes=1)
    second = evaluate_focus_state(
        _feature(second_minute, session_return=-0.05, supportive=True),
        _evidence(second_minute),
        first,
    )

    assert first.state == "background"
    assert second.state == "focus"
    assert "outperforming_nifty" in second.reasons


def test_focus_demotes_only_after_three_confirmed_weak_minutes() -> None:
    timestamp = datetime(2026, 10, 16, 10, 0, tzinfo=IST)
    state = evaluate_focus_state(
        _feature(timestamp, session_return=1, supportive=True),
        _evidence(timestamp),
        None,
        promote_confirmation_minutes=1,
    )
    assert state.state == "focus"

    for offset in range(1, 3):
        minute = timestamp + timedelta(minutes=offset)
        state = evaluate_focus_state(
            _feature(minute, session_return=-1, supportive=False),
            _evidence(minute),
            state,
        )
        assert state.state == "focus"

    minute = timestamp + timedelta(minutes=3)
    state = evaluate_focus_state(
        _feature(minute, session_return=-1, supportive=False),
        _evidence(minute),
        state,
    )
    assert state.state == "background"
    assert "below_previous_close" in state.reasons


def test_duplicate_api_evaluation_does_not_advance_confirmation_streak() -> None:
    timestamp = datetime(2026, 10, 16, 9, 30, tzinfo=IST)
    feature = _feature(timestamp, session_return=1, supportive=True)
    evidence = _evidence(timestamp)
    state = evaluate_focus_state(feature, evidence, None)

    repeated = evaluate_focus_state(feature, evidence, state)

    assert state.promote_streak == 1
    assert repeated == state


def test_constructive_green_pause_stays_visible_as_cooling_and_resumes_immediately() -> None:
    timestamp = datetime(2026, 10, 16, 10, 0, tzinfo=IST)
    state = evaluate_focus_state(
        _feature(timestamp, session_return=1.5, supportive=True),
        _evidence(timestamp),
        None,
        promote_confirmation_minutes=1,
    )
    assert state.state == "focus"

    for offset in range(1, 3):
        minute = timestamp + timedelta(minutes=offset)
        paused_base = _feature(minute, session_return=1.1, supportive=False)
        paused = paused_base.model_copy(
            update={
                "pullback": paused_base.pullback.model_copy(
                    update={"direction": "up", "quality": "orderly"}
                ),
            }
        )
        state = evaluate_focus_state(paused, _evidence(minute, score=50), state)

    assert state.state == "cooling"
    assert "constructive_green_pullback" in state.reasons

    resumed_at = timestamp + timedelta(minutes=3)
    state = evaluate_focus_state(
        _feature(resumed_at, session_return=1.8, supportive=True),
        _evidence(resumed_at),
        state,
    )
    assert state.state == "focus"
