"""Reversible intraday attention funnel for the long-continuation model."""

from __future__ import annotations

from datetime import datetime, time, timedelta

from app.models.market import IntradayFocusState, OpportunityEvidenceSnapshot, StockFeatureSnapshot
from app.services.market_context import INDIA_TIMEZONE


MARKET_OPEN = time(9, 15)


def _volume_supportive(feature: StockFeatureSnapshot) -> bool:
    values = [
        value
        for value in (feature.volume.relative_volume, feature.volume.acceleration_ratio)
        if value is not None
    ]
    return bool(values) and max(values) >= 1.0


def _volume_weak(feature: StockFeatureSnapshot) -> bool:
    values = [
        value
        for value in (feature.volume.relative_volume, feature.volume.acceleration_ratio)
        if value is not None
    ]
    return bool(values) and all(value < 1.0 for value in values)


def _support_reasons(feature: StockFeatureSnapshot) -> list[str]:
    reasons: list[str] = []
    relative = feature.relative_strength
    if relative.session_return_percent is not None and relative.session_return_percent > 0:
        reasons.append("above_previous_close")
    if (
        feature.vwap.state == "above"
        and feature.vwap.slope_5m_percent_per_minute is not None
        and feature.vwap.slope_5m_percent_per_minute > 0
    ):
        reasons.append("above_rising_vwap")
    if relative.versus_nifty_percent is not None and relative.versus_nifty_percent > 0:
        reasons.append("outperforming_nifty")
    if relative.versus_sector_percent is not None and relative.versus_sector_percent > 0:
        reasons.append("outperforming_sector")
    if _volume_supportive(feature):
        reasons.append("volume_confirming")
    if any(item.ready and item.position == "above" for item in feature.opening_ranges):
        reasons.append("above_opening_range")
    return reasons


def _weakness_reasons(feature: StockFeatureSnapshot) -> list[str]:
    reasons: list[str] = []
    relative = feature.relative_strength
    if relative.session_return_percent is not None and relative.session_return_percent < 0:
        reasons.append("below_previous_close")
    if (
        feature.vwap.state == "below"
        and feature.vwap.slope_5m_percent_per_minute is not None
        and feature.vwap.slope_5m_percent_per_minute <= 0
    ):
        reasons.append("below_falling_vwap")
    if (
        relative.versus_nifty_percent is not None
        and relative.versus_nifty_percent <= 0
        and relative.versus_sector_percent is not None
        and relative.versus_sector_percent <= 0
    ):
        reasons.append("underperforming_nifty_and_sector")
    if _volume_weak(feature):
        reasons.append("weak_volume_participation")
    if (
        any(item.ready for item in feature.opening_ranges)
        and not any(item.ready and item.position == "above" for item in feature.opening_ranges)
    ):
        reasons.append("no_opening_range_breakout")
    return reasons


def _cooling_reasons(feature: StockFeatureSnapshot) -> list[str]:
    """Describe a green pause without treating it as a broken long setup."""
    reasons: list[str] = []
    if feature.momentum.return_5m_percent is not None and feature.momentum.return_5m_percent <= 0:
        reasons.append("short_term_momentum_paused")
    if (
        feature.vwap.slope_5m_percent_per_minute is not None
        and feature.vwap.slope_5m_percent_per_minute <= 0
    ):
        reasons.append("vwap_slope_paused")
    if _volume_weak(feature):
        reasons.append("pullback_volume_contracted")
    if feature.pullback.quality in {"holding_extreme", "orderly"}:
        reasons.append("constructive_green_pullback")
    return reasons


def evaluate_focus_state(
    feature: StockFeatureSnapshot,
    evidence: OpportunityEvidenceSnapshot,
    previous: IntradayFocusState | None,
    *,
    start_minutes_after_open: int = 15,
    promote_confirmation_minutes: int = 2,
    cooling_confirmation_minutes: int = 2,
    demote_confirmation_minutes: int = 3,
    minimum_score: float = 55,
) -> IntradayFocusState:
    """Classify one completed minute without making red performance a lone veto."""
    if previous is not None and previous.candle_timestamp >= feature.candle_timestamp:
        return previous

    local_timestamp = feature.candle_timestamp.astimezone(INDIA_TIMEZONE)
    session_open = datetime.combine(local_timestamp.date(), MARKET_OPEN, tzinfo=INDIA_TIMEZONE)
    evaluation_start = session_open + timedelta(minutes=start_minutes_after_open)
    score = evidence.opportunity_score

    if evidence.liquidity_tier == "dormant":
        target = "dormant"
        reasons = [evidence.liquidity_tier_reason or "rolling_liquidity_dormant"]
        promote_streak = cooling_streak = demote_streak = 0
    elif evidence.liquidity_tier == "watch_only":
        target = "watch_only"
        reasons = [evidence.liquidity_tier_reason or "rolling_liquidity_watch_only"]
        promote_streak = cooling_streak = demote_streak = 0
    elif local_timestamp < evaluation_start:
        target = "background"
        reasons = ["opening_discovery_window"]
        promote_streak = cooling_streak = demote_streak = 0
    else:
        support = _support_reasons(feature)
        weaknesses = _weakness_reasons(feature)
        cooling = _cooling_reasons(feature)
        regime = evidence.market_regime.state if evidence.market_regime else "insufficient"
        required_support = 4 if regime == "risk_off" else 3
        required_score = minimum_score + (5 if regime == "risk_off" else 0)
        promotable = bool(
            score
            and score.eligible
            and score.final_score >= required_score
            and len(support) >= required_support
        )
        materially_weak = bool(
            "below_previous_close" in weaknesses and len(weaknesses) >= 3
        )
        session_return = feature.relative_strength.session_return_percent
        cooling_candidate = bool(
            session_return is not None
            and session_return >= 0
            and not promotable
            and cooling
        )
        prior_state = previous.state if previous else "background"
        promote_streak = (previous.promote_streak if previous else 0) + 1 if promotable else 0
        cooling_streak = (
            (previous.cooling_streak if previous else 0) + 1
            if cooling_candidate
            else 0
        )
        demote_streak = (previous.demote_streak if previous else 0) + 1 if materially_weak else 0

        if prior_state in {"focus", "cooling"}:
            if score is not None and not score.eligible:
                target = "background"
                reasons = ["execution_or_risk_gate_failed", *score.invalidation_reasons]
                promote_streak = cooling_streak = demote_streak = 0
            elif demote_streak >= demote_confirmation_minutes:
                target = "background"
                reasons = weaknesses
                promote_streak = cooling_streak = demote_streak = 0
            elif prior_state == "cooling" and promotable:
                target = "focus"
                reasons = support
                promote_streak = cooling_streak = demote_streak = 0
            elif prior_state == "cooling":
                target = "cooling"
                reasons = cooling or support or ["constructive_setup_paused"]
            elif cooling_streak >= cooling_confirmation_minutes:
                target = "cooling"
                reasons = cooling
                cooling_streak = 0
            else:
                target = "focus"
                reasons = support or ["focus_held_pending_cooling_confirmation"]
        elif promote_streak >= promote_confirmation_minutes:
            target = "focus"
            reasons = support
            promote_streak = cooling_streak = demote_streak = 0
        else:
            target = "background"
            reasons = support if promotable else weaknesses or ["focus_conditions_not_confirmed"]

    state_since = (
        previous.state_since
        if previous is not None and previous.state == target
        else feature.candle_timestamp
    )
    return IntradayFocusState(
        instrument_key=feature.instrument_key,
        symbol=feature.symbol,
        sector=feature.sector,
        state=target,
        as_of=feature.as_of,
        candle_timestamp=feature.candle_timestamp,
        state_since=state_since,
        promote_streak=promote_streak,
        cooling_streak=cooling_streak,
        demote_streak=demote_streak,
        reasons=list(dict.fromkeys(reasons)),
    )
