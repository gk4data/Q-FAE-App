"""Require repeated minute evidence before calling a signal confirmed."""

from __future__ import annotations

from datetime import UTC, datetime

from app.models.market import OpportunityEvidenceSnapshot, SignalPersistenceSnapshot


SUPPORTIVE = {"strong_support", "supportive"}


def build_signal_persistence(
    current: OpportunityEvidenceSnapshot,
    prior: list[OpportunityEvidenceSnapshot],
    previous: SignalPersistenceSnapshot | None = None,
    *,
    as_of: datetime | None = None,
) -> SignalPersistenceSnapshot:
    """Classify building/confirmed/weakening/failed using up to three completed minutes."""
    window = [*prior[-2:], current]
    supportive = sum(item.confluence in SUPPORTIVE for item in window)
    cautions = sum(item.confluence == "caution" for item in window)
    current_supportive = current.confluence in SUPPORTIVE
    prior_confirmed = previous is not None and previous.state == "confirmed"

    if cautions >= 2 or (prior_confirmed and current.confluence == "caution"):
        state = "failed"
        reason = "support_failed_with_repeated_or_current_caution"
    elif supportive >= 2:
        state = "confirmed"
        reason = "support_present_in_at_least_two_of_last_three_minutes"
    elif prior_confirmed:
        state = "weakening"
        reason = "previous_confirmation_is_no_longer_repeated"
    elif current_supportive:
        state = "building"
        reason = "support_is_present_but_not_yet_repeated"
    else:
        state = "neutral"
        reason = "no_persistent_directional_confluence"

    transition = None
    if previous is not None and previous.state != state:
        transition = f"{previous.state}_to_{state}"
    return SignalPersistenceSnapshot(
        instrument_key=current.instrument_key,
        symbol=current.symbol,
        as_of=as_of or datetime.now(UTC),
        state=state,
        supportive_minutes=supportive,
        caution_minutes=cautions,
        observed_minutes=len(window),
        transition=transition,
        reason=reason,
    )
