"""Combine volume participation with executable-liquidity evidence."""

from __future__ import annotations

from app.models.market import FlowLiquidityConfirmation, StockFeatureSnapshot


def build_flow_liquidity_confirmation(
    feature: StockFeatureSnapshot,
    *,
    active_rvol: float = 1.0,
    strong_rvol: float = 1.5,
    active_acceleration: float = 1.0,
    strong_acceleration: float = 1.25,
) -> FlowLiquidityConfirmation:
    """Confirm participation only when the stock also passes execution-quality checks."""
    rvol = feature.volume.relative_volume
    acceleration = feature.volume.acceleration_ratio
    spread_pass = feature.liquidity.passes_spread_filter
    traded_value_pass = feature.liquidity.passes_traded_value_filter
    evidence: list[str] = []
    cautions: list[str] = []

    if rvol is None and acceleration is None:
        volume_state = "unavailable"
    elif (
        rvol is not None
        and acceleration is not None
        and rvol >= strong_rvol
        and acceleration >= strong_acceleration
    ):
        volume_state = "strong"
        evidence.extend(["high_relative_volume", "volume_accelerating_strongly"])
    elif (
        (rvol is not None and rvol >= active_rvol)
        or (acceleration is not None and acceleration >= active_acceleration)
    ):
        volume_state = "active"
        if rvol is not None and rvol >= active_rvol:
            evidence.append("relative_volume_active")
        if acceleration is not None and acceleration >= active_acceleration:
            evidence.append("volume_accelerating")
    elif rvol is not None and acceleration is not None and rvol < 0.7 and acceleration < 0.8:
        volume_state = "weak"
        cautions.append("quiet_and_decelerating_volume")
    else:
        volume_state = "mixed"
        cautions.append("volume_confirmation_mixed")

    if spread_pass is False or traded_value_pass is False:
        liquidity_state = "rejected"
        if spread_pass is False:
            cautions.append("spread_too_wide")
        if traded_value_pass is False:
            cautions.append("traded_value_too_low")
    elif spread_pass is True and traded_value_pass is True:
        liquidity_state = "pass"
        evidence.extend(["spread_acceptable", "traded_value_acceptable"])
    elif spread_pass is True or traded_value_pass is True:
        liquidity_state = "partial"
        cautions.append("liquidity_confirmation_partial")
    else:
        liquidity_state = "unavailable"

    imbalance = feature.liquidity.depth_imbalance
    if imbalance is not None and imbalance >= 0.15:
        evidence.append("buy_depth_imbalance")
    elif imbalance is not None and imbalance <= -0.15:
        cautions.append("sell_depth_imbalance")

    if liquidity_state == "rejected":
        confirmation = "rejected"
    elif liquidity_state == "pass" and volume_state == "strong":
        confirmation = "strong_confirmation"
    elif liquidity_state == "pass" and volume_state == "active":
        confirmation = "confirmed"
    elif liquidity_state == "pass" and volume_state in {"mixed", "weak"}:
        confirmation = "liquid_but_unconfirmed"
    elif volume_state in {"strong", "active"}:
        confirmation = "volume_without_full_liquidity"
    else:
        confirmation = "insufficient"

    available = sum(
        value is not None
        for value in (rvol, acceleration, spread_pass, traded_value_pass)
    )
    data_quality = "complete" if available == 4 else "partial" if available >= 2 else "limited"
    return FlowLiquidityConfirmation(
        instrument_key=feature.instrument_key,
        symbol=feature.symbol,
        as_of=feature.as_of,
        data_quality=data_quality,
        relative_volume=rvol,
        volume_acceleration=acceleration,
        spread_bps=feature.liquidity.spread_bps,
        traded_value_inr=feature.liquidity.total_traded_value_inr,
        depth_imbalance=imbalance,
        passes_spread_filter=spread_pass,
        passes_traded_value_filter=traded_value_pass,
        volume_state=volume_state,
        liquidity_state=liquidity_state,
        confirmation=confirmation,
        evidence=evidence,
        cautions=cautions,
    )
