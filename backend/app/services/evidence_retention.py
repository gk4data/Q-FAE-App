"""Storage policy for full candidate evidence and compact universe checkpoints."""

from __future__ import annotations

from typing import Any

from app.models.market import (
    CompactEvidenceObservation,
    EvidenceOutcomeObservation,
    OpportunityEvidenceSnapshot,
)
from app.services.market_context import INDIA_TIMEZONE


def _payload_score(observation: EvidenceOutcomeObservation) -> tuple[bool, float, float]:
    raw = observation.evidence_payload.get("opportunity_score")
    score = raw if isinstance(raw, dict) else {}
    return (
        bool(score.get("eligible", False)),
        float(score.get("final_score") or 0),
        float(score.get("coverage_percent") or 0),
    )


def opportunity_priority(
    evidence: OpportunityEvidenceSnapshot,
) -> tuple[bool, float, float, str]:
    """Rank full-storage candidates without first serializing their large payloads."""
    score = evidence.opportunity_score
    return (
        bool(score and score.eligible),
        float(score.final_score if score else 0),
        float(score.coverage_percent if score else 0),
        evidence.symbol,
    )


def select_full_evidence_candidates(
    observations: list[EvidenceOutcomeObservation],
    maximum: int,
) -> list[EvidenceOutcomeObservation]:
    """Retain the strongest bounded point-in-time candidates for backtesting."""
    if maximum <= 0:
        return []
    return sorted(
        observations,
        key=lambda item: (*_payload_score(item), item.symbol),
        reverse=True,
    )[:maximum]


def compact_checkpoint_due(candle_timestamp: Any, interval_minutes: int) -> bool:
    """Use NSE-session anchored checkpoints (09:15, 09:30, ...)."""
    local = candle_timestamp.astimezone(INDIA_TIMEZONE)
    session_minute = local.hour * 60 + local.minute - (9 * 60 + 15)
    return session_minute >= 0 and session_minute % interval_minutes == 0


def compact_state_key(
    evidence: OpportunityEvidenceSnapshot,
    *,
    score_bucket: int,
) -> tuple[object, ...]:
    """Return a coarse decision state so normal score noise does not cause writes."""
    score = evidence.opportunity_score
    final_score = score.final_score if score is not None else 0
    risk = evidence.risk_assessment
    signal = evidence.signal_persistence
    return (
        int(final_score // score_bucket),
        bool(score and score.eligible),
        score.status if score else "unavailable",
        evidence.confluence,
        signal.state if signal else "unavailable",
        risk.status if risk else "unavailable",
        evidence.liquidity_tier,
    )


def build_compact_evidence_observation(
    evidence: OpportunityEvidenceSnapshot,
    *,
    candle_timestamp: Any,
    reference_price: float,
    capture_reason: str,
) -> CompactEvidenceObservation | None:
    """Flatten only stable numeric/state fields; never store the large evidence JSON."""
    score = evidence.opportunity_score
    signal = evidence.signal_persistence
    if score is None or signal is None:
        return None
    components = {component.key: component.score for component in score.components}
    return CompactEvidenceObservation(
        instrument_key=evidence.instrument_key,
        symbol=evidence.symbol,
        sector=evidence.sector,
        candle_timestamp=candle_timestamp,
        observed_at=evidence.as_of,
        reference_price=reference_price,
        opportunity_score=score.final_score,
        coverage_percent=score.coverage_percent,
        eligible=score.eligible,
        score_status=score.status,
        confluence=evidence.confluence,
        signal_state=signal.state,
        risk_status=evidence.risk_assessment.status if evidence.risk_assessment else None,
        liquidity_tier=evidence.liquidity_tier,
        market_regime_state=evidence.market_regime.state if evidence.market_regime else None,
        flow_confirmation=evidence.flow_liquidity.confirmation,
        price_trend_score=components.get("price_trend"),
        participation_score=components.get("participation"),
        market_sector_score=components.get("market_sector"),
        fundamental_score=components.get("fundamental"),
        capture_reason=capture_reason,
    )
