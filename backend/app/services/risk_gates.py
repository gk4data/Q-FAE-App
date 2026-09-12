"""Execution-quality and tradability gates for a reference cash order."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models.market import LiveSnapshot, RiskAssessment, RiskGateResult, StockFeatureSnapshot


def estimate_slippage_bps(
    snapshot: LiveSnapshot,
    order_value_inr: float,
    *,
    side: str,
) -> float | None:
    """Walk visible D5 depth and return VWAP slippage from LTP for a cash value."""
    if snapshot.ltp is None or snapshot.ltp <= 0 or order_value_inr <= 0:
        return None
    remaining_quantity = order_value_inr / snapshot.ltp
    cost = 0.0
    filled = 0.0
    for level in snapshot.market_depth[:5]:
        price = level.ask_price if side == "buy" else level.bid_price
        quantity = level.ask_quantity if side == "buy" else level.bid_quantity
        if price is None or price <= 0 or quantity is None or quantity <= 0:
            continue
        take = min(remaining_quantity, float(quantity))
        cost += take * price
        filled += take
        remaining_quantity -= take
        if remaining_quantity <= 1e-9:
            break
    if remaining_quantity > 1e-9 or filled <= 0:
        return None
    execution_price = cost / filled
    movement = execution_price - snapshot.ltp if side == "buy" else snapshot.ltp - execution_price
    return round(max(0.0, movement / snapshot.ltp * 10_000), 4)


def build_risk_assessment(
    feature: StockFeatureSnapshot,
    snapshot: LiveSnapshot | None,
    *,
    as_of: datetime | None = None,
    freshness_seconds: int = 120,
    reference_order_value_inr: float = 100_000,
    max_slippage_bps: float = 20,
    min_circuit_distance_percent: float = 1,
    max_gap_atr: float = 2,
    risk_capital_inr: float | None = None,
    recent_spreads_bps: list[float] | None = None,
    recent_depth_imbalances: list[float] | None = None,
    max_spread_range_bps: float = 10,
) -> RiskAssessment:
    now = as_of or datetime.now(UTC)
    gates: list[RiskGateResult] = []
    fresh = bool(snapshot and snapshot.received_at >= now - timedelta(seconds=freshness_seconds))
    gates.append(RiskGateResult(key="freshness", status="pass" if fresh else "reject", value=fresh, reason="quote_is_current" if fresh else "quote_is_stale_or_missing"))

    spread_pass = feature.liquidity.passes_spread_filter
    gates.append(RiskGateResult(key="spread", status="unavailable" if spread_pass is None else "pass" if spread_pass else "reject", value=feature.liquidity.spread_bps, reason="spread_within_limit" if spread_pass else "spread_exceeds_limit_or_is_unavailable"))
    value_pass = feature.liquidity.passes_traded_value_filter
    gates.append(RiskGateResult(key="traded_value", status="unavailable" if value_pass is None else "pass" if value_pass else "reject", value=feature.liquidity.total_traded_value_inr, reason="traded_value_sufficient" if value_pass else "traded_value_below_limit_or_unavailable"))

    buy_slippage = estimate_slippage_bps(snapshot, reference_order_value_inr, side="buy") if snapshot else None
    sell_slippage = estimate_slippage_bps(snapshot, reference_order_value_inr, side="sell") if snapshot else None
    worst_slippage = max(value for value in (buy_slippage, sell_slippage) if value is not None) if buy_slippage is not None or sell_slippage is not None else None
    gates.append(RiskGateResult(key="d5_slippage", status="unavailable" if worst_slippage is None else "pass" if worst_slippage <= max_slippage_bps else "reject", value=worst_slippage, threshold=max_slippage_bps, reason="visible_depth_supports_reference_order" if worst_slippage is not None and worst_slippage <= max_slippage_bps else "depth_insufficient_or_slippage_too_high"))

    spreads = [value for value in (recent_spreads_bps or []) if value >= 0][-3:]
    spread_range = max(spreads) - min(spreads) if len(spreads) >= 3 else None
    gates.append(RiskGateResult(key="spread_stability", status="unavailable" if spread_range is None else "pass" if spread_range <= max_spread_range_bps else "reject", value=round(spread_range, 4) if spread_range is not None else None, threshold=max_spread_range_bps, reason="spread_stable_across_three_minutes" if spread_range is not None and spread_range <= max_spread_range_bps else "spread_history_insufficient_or_unstable"))
    imbalances = [value for value in (recent_depth_imbalances or []) if -1 <= value <= 1][-3:]
    imbalance_range = max(imbalances) - min(imbalances) if len(imbalances) >= 3 else None
    gates.append(RiskGateResult(key="depth_imbalance_stability", status="unavailable" if imbalance_range is None else "pass" if imbalance_range <= 0.5 else "caution", value=round(imbalance_range, 4) if imbalance_range is not None else None, threshold=0.5, reason="depth_imbalance_stable" if imbalance_range is not None and imbalance_range <= 0.5 else "depth_history_insufficient_or_unstable"))

    ltp = snapshot.ltp if snapshot else None
    upper_distance = ((snapshot.upper_circuit - ltp) / ltp * 100) if snapshot and snapshot.upper_circuit and ltp else None
    lower_distance = ((ltp - snapshot.lower_circuit) / ltp * 100) if snapshot and snapshot.lower_circuit and ltp else None
    circuit_distance = min(value for value in (upper_distance, lower_distance) if value is not None) if upper_distance is not None or lower_distance is not None else None
    gates.append(RiskGateResult(key="circuit_distance", status="unavailable" if circuit_distance is None else "pass" if circuit_distance >= min_circuit_distance_percent else "reject", value=round(circuit_distance, 4) if circuit_distance is not None else None, threshold=min_circuit_distance_percent, reason="price_clear_of_circuit_limits" if circuit_distance is not None and circuit_distance >= min_circuit_distance_percent else "circuit_limits_unavailable_or_too_close"))

    gap_atr = abs(feature.gap.gap_atr) if feature.gap.gap_atr is not None else None
    gates.append(RiskGateResult(key="gap_atr", status="unavailable" if gap_atr is None else "pass" if gap_atr <= max_gap_atr else "reject", value=gap_atr, threshold=max_gap_atr, reason="opening_gap_within_volatility_limit" if gap_atr is not None and gap_atr <= max_gap_atr else "gap_atr_unavailable_or_excessive"))
    gates.append(RiskGateResult(key="surveillance", status="unavailable", reason="asm_gsm_trade_to_trade_source_not_configured"))
    gates.append(RiskGateResult(key="risk_budget", status="unavailable" if risk_capital_inr is None else "pass", value=risk_capital_inr, reason="capital_and_portfolio_exposure_not_configured" if risk_capital_inr is None else "capital_budget_configured"))

    rejected = [gate for gate in gates if gate.status == "reject"]
    unavailable = [gate for gate in gates if gate.status == "unavailable"]
    status = "rejected" if rejected else "partial" if unavailable else "pass"
    return RiskAssessment(
        instrument_key=feature.instrument_key,
        symbol=feature.symbol,
        as_of=now,
        eligible=not rejected,
        status=status,
        reference_order_value_inr=reference_order_value_inr,
        estimated_buy_slippage_bps=buy_slippage,
        estimated_sell_slippage_bps=sell_slippage,
        spread_range_bps=round(spread_range, 4) if spread_range is not None else None,
        depth_imbalance_range=round(imbalance_range, 4) if imbalance_range is not None else None,
        distance_to_upper_circuit_percent=round(upper_distance, 4) if upper_distance is not None else None,
        distance_to_lower_circuit_percent=round(lower_distance, 4) if lower_distance is not None else None,
        gates=gates,
    )
