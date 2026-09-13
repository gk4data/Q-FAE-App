"""Explainable provisional scoring and cross-sectional ranking for pilot opportunities."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.market import (
    CorporateActionContext,
    EvidencePillar,
    FinancialMetricSnapshot,
    FlowLiquidityConfirmation,
    MarketRegimeSnapshot,
    OpportunityEvidenceSnapshot,
    OpportunityScoreComponent,
    OpportunityScoreSnapshot,
    RankedOpportunity,
    RiskAssessment,
)

MODEL_VERSION = "long-continuation-pilot-v1"
STRATEGY = "long_continuation"
CALIBRATION_STATUS = "provisional_not_backtested"
DEFAULT_WEIGHTS = {
    "price_trend": 30.0,
    "participation": 20.0,
    "market_sector": 20.0,
    "liquidity_execution": 15.0,
    "fundamental": 10.0,
    "catalyst": 5.0,
}
FINANCIAL_SECTORS = {"bank", "banking", "nbfc", "finance", "financial services"}


@dataclass(frozen=True)
class _Measure:
    key: str
    score: float | None
    weight: float = 1.0
    positive: str | None = None
    caution: str | None = None


def _clamp(value: float, lower: float = 0, upper: float = 100) -> float:
    return max(lower, min(upper, value))


def _linear(value: float | None, low: float, high: float, *, inverse: bool = False) -> float | None:
    if value is None:
        return None
    if high <= low:
        raise ValueError("high must exceed low")
    score = _clamp((value - low) / (high - low) * 100)
    return 100 - score if inverse else score


def _component(
    key: str,
    label: str,
    outer_weight: float,
    measures: list[_Measure],
    *,
    extra_positive: list[str] | None = None,
    extra_cautions: list[str] | None = None,
) -> OpportunityScoreComponent:
    total_measure_weight = sum(max(0, item.weight) for item in measures)
    available = [item for item in measures if item.score is not None and item.weight > 0]
    available_weight = sum(item.weight for item in available)
    coverage = available_weight / total_measure_weight * 100 if total_measure_weight else 0
    score = (
        sum(float(item.score) * item.weight for item in available) / available_weight
        if available_weight
        else None
    )
    contribution = outer_weight * (coverage / 100) * ((score or 0) / 100)
    positives = list(extra_positive or [])
    cautions = list(extra_cautions or [])
    for item in available:
        if item.score is not None and item.score >= 60 and item.positive:
            positives.append(item.positive)
        elif item.score is not None and item.score <= 40 and item.caution:
            cautions.append(item.caution)
    return OpportunityScoreComponent(
        key=key,
        label=label,
        weight_percent=round(outer_weight, 4),
        score=round(score, 4) if score is not None else None,
        coverage_percent=round(coverage, 4),
        contribution_points=round(contribution, 4),
        positive_factors=list(dict.fromkeys(positives)),
        cautions=list(dict.fromkeys(cautions)),
        unavailable_inputs=[item.key for item in measures if item.score is None],
    )


def _pillar_measure(pillar: EvidencePillar | None, weight: float = 1.0) -> _Measure:
    if pillar is None or pillar.available_checks <= 0 or pillar.state == "unavailable":
        return _Measure(pillar.key if pillar else "pillar", None, weight)
    balance = (pillar.supportive_checks - pillar.caution_checks) / pillar.available_checks
    return _Measure(
        pillar.key,
        _clamp(50 + balance * 50),
        weight,
        f"{pillar.key}_evidence_supportive",
        f"{pillar.key}_evidence_caution",
    )


def _price_trend_component(
    pillars: dict[str, EvidencePillar], weight: float
) -> OpportunityScoreComponent:
    intraday = pillars.get("intraday")
    daily = pillars.get("daily")
    return _component(
        "price_trend",
        "Price and trend quality",
        weight,
        [_pillar_measure(intraday, 0.55), _pillar_measure(daily, 0.45)],
        extra_positive=[*(intraday.evidence if intraday else []), *(daily.evidence if daily else [])],
        extra_cautions=[*(intraday.cautions if intraday else []), *(daily.cautions if daily else [])],
    )


def _participation_component(
    flow: FlowLiquidityConfirmation, weight: float
) -> OpportunityScoreComponent:
    return _component(
        "participation",
        "Volume participation",
        weight,
        [
            _Measure(
                "relative_volume",
                _linear(flow.relative_volume, 0.5, 2.0),
                positive="relative_volume_supportive",
                caution="relative_volume_weak",
            ),
            _Measure(
                "volume_acceleration",
                _linear(flow.volume_acceleration, 0.5, 1.5),
                positive="volume_accelerating",
                caution="volume_decelerating",
            ),
        ],
        extra_positive=[item for item in flow.evidence if "volume" in item],
        extra_cautions=[item for item in flow.cautions if "volume" in item],
    )


def _market_sector_component(
    pillar: EvidencePillar | None,
    market_regime: MarketRegimeSnapshot | None,
    weight: float,
) -> OpportunityScoreComponent:
    regime_score = None
    if market_regime is not None:
        regime_score = {"risk_on": 100.0, "mixed": 50.0, "risk_off": 0.0}.get(
            market_regime.state
        )
    return _component(
        "market_sector",
        "NIFTY and sector alignment",
        weight,
        [
            _pillar_measure(pillar, 0.75),
            _Measure(
                "broad_market_regime",
                regime_score,
                0.25,
                positive="broad_market_risk_on",
                caution="broad_market_risk_off",
            ),
        ],
        extra_positive=[
            *(pillar.evidence if pillar else []),
            *(market_regime.evidence if market_regime else []),
        ],
        extra_cautions=[
            *(pillar.cautions if pillar else []),
            *(market_regime.cautions if market_regime else []),
        ],
    )


def _liquidity_component(
    flow: FlowLiquidityConfirmation,
    risk: RiskAssessment | None,
    weight: float,
) -> OpportunityScoreComponent:
    ignored = {"surveillance", "risk_budget"}
    status_scores = {"pass": 100.0, "caution": 50.0, "reject": 0.0}
    measures: list[_Measure] = []
    if risk is not None:
        measures = [
            _Measure(
                f"risk_{gate.key}",
                status_scores.get(gate.status),
                positive=f"{gate.key}_gate_passed",
                caution=f"{gate.key}_gate_{gate.status}",
            )
            for gate in risk.gates
            if gate.key not in ignored
        ]
    else:
        measures = [
            _Measure(
                "spread_filter",
                None if flow.passes_spread_filter is None else 100 if flow.passes_spread_filter else 0,
                positive="spread_filter_passed",
                caution="spread_filter_failed",
            ),
            _Measure(
                "traded_value_filter",
                None
                if flow.passes_traded_value_filter is None
                else 100
                if flow.passes_traded_value_filter
                else 0,
                positive="traded_value_filter_passed",
                caution="traded_value_filter_failed",
            ),
        ]
    return _component(
        "liquidity_execution",
        "Liquidity and execution",
        weight,
        measures,
        extra_positive=[item for item in flow.evidence if "volume" not in item],
        extra_cautions=[item for item in flow.cautions if "volume" not in item],
    )


def _fundamental_component(
    metrics: FinancialMetricSnapshot | None,
    sector: str | None,
    weight: float,
    *,
    unavailable_reason: str = "financial_metrics",
) -> OpportunityScoreComponent:
    if metrics is None:
        return _component(
            "fundamental",
            "Fundamental quality and growth",
            weight,
            [_Measure(unavailable_reason, None)],
        )
    growth = metrics.growth
    margins = metrics.margins
    capital = metrics.capital
    eps = metrics.eps
    measures = [
        _Measure("revenue_qoq", _linear(growth.revenue_qoq_percent, -15, 20), positive="revenue_qoq_growth", caution="revenue_qoq_contraction"),
        _Measure("revenue_yoy", _linear(growth.revenue_yoy_percent, -20, 30), positive="revenue_yoy_growth", caution="revenue_yoy_contraction"),
        _Measure("operating_profit_yoy", _linear(growth.operating_profit_yoy_percent, -25, 35), positive="operating_profit_yoy_growth", caution="operating_profit_yoy_weak"),
        _Measure("net_profit_yoy", _linear(growth.net_profit_yoy_percent, -25, 35), positive="net_profit_yoy_growth", caution="net_profit_yoy_weak"),
        _Measure("operating_margin_yoy_change", _linear(margins.operating_margin_yoy_change_pp, -5, 5), positive="operating_margin_expanding", caution="operating_margin_contracting"),
        _Measure("net_margin_yoy_change", _linear(margins.net_margin_yoy_change_pp, -5, 5), positive="net_margin_expanding", caution="net_margin_contracting"),
        _Measure("cash_conversion", _linear(capital.operating_cash_conversion_percent, 0, 125), positive="cash_conversion_strong", caution="cash_conversion_weak"),
        _Measure("roe", _linear(capital.roe_percent, 0, 25), positive="roe_strong", caution="roe_weak"),
        _Measure("roce", _linear(capital.roce_percent, 0, 25), positive="roce_strong", caution="roce_weak"),
        _Measure("eps_yoy", _linear(eps.yoy_growth_percent, -20, 30), positive="eps_yoy_growth", caution="eps_yoy_weak"),
    ]
    sector_key = (sector or "").casefold()
    financial_sector = any(name in sector_key for name in FINANCIAL_SECTORS)
    cautions = list(metrics.cautions)
    if financial_sector:
        cautions.append("generic_leverage_thresholds_not_used_for_financial_sector")
    else:
        measures.extend(
            [
                _Measure("debt_yoy", _linear(capital.debt_yoy_change_percent, -25, 25, inverse=True), positive="debt_reducing", caution="debt_increasing"),
                _Measure("debt_to_equity", _linear(capital.debt_to_equity, 0, 2, inverse=True), positive="leverage_controlled", caution="leverage_high"),
            ]
        )
    return _component(
        "fundamental",
        "Fundamental quality and growth",
        weight,
        measures,
        extra_cautions=cautions,
    )


def _catalyst_component(
    context: CorporateActionContext | None, weight: float
) -> OpportunityScoreComponent:
    if context is None:
        return _component(
            "catalyst",
            "Corporate catalyst",
            weight,
            [_Measure("corporate_action_context", None)],
        )
    if context.active_events == 0:
        return _component(
            "catalyst",
            "Corporate catalyst",
            weight,
            [_Measure("active_catalyst", 50, positive="no_active_corporate_action")],
        )
    score = None if context.effective_score is None else _clamp(50 + context.effective_score / 2)
    return _component(
        "catalyst",
        "Corporate catalyst",
        weight,
        [_Measure("active_catalyst", score, positive="positive_corporate_catalyst", caution="negative_corporate_catalyst")],
        extra_positive=context.evidence,
        extra_cautions=context.cautions,
    )


def _persistence_multiplier(evidence: OpportunityEvidenceSnapshot) -> tuple[float, str, bool]:
    signal = evidence.signal_persistence
    if signal is None:
        return 0.8, "signal_persistence_unavailable", False
    multipliers = {
        "confirmed": 1.0,
        "building": 0.9,
        "neutral": 0.8,
        "weakening": 0.6,
        "failed": 0.35,
    }
    return multipliers.get(signal.state, 0.8), signal.reason, signal.state in {"confirmed", "building"}


def build_opportunity_score(
    evidence: OpportunityEvidenceSnapshot,
    financial_metrics: FinancialMetricSnapshot | None = None,
    *,
    weights: dict[str, float] | None = None,
) -> OpportunityScoreSnapshot:
    """Score one point-in-time evidence snapshot without hiding missing inputs."""
    configured = dict(weights or DEFAULT_WEIGHTS)
    if set(configured) != set(DEFAULT_WEIGHTS):
        raise ValueError("scoring weights must contain every supported component")
    if any(value < 0 for value in configured.values()) or sum(configured.values()) <= 0:
        raise ValueError("scoring weights must be non-negative and have a positive total")
    total = sum(configured.values())
    normalized = {key: value / total * 100 for key, value in configured.items()}
    pillars = {pillar.key: pillar for pillar in evidence.pillars}
    point_in_time_metrics = financial_metrics
    financial_unavailable_reason = "financial_metrics"
    if financial_metrics is not None and financial_metrics.calculated_at > evidence.as_of:
        point_in_time_metrics = None
        financial_unavailable_reason = "financial_metrics_newer_than_evidence"
    components = [
        _price_trend_component(pillars, normalized["price_trend"]),
        _participation_component(evidence.flow_liquidity, normalized["participation"]),
        _market_sector_component(
            pillars.get("relative_strength"),
            evidence.market_regime,
            normalized["market_sector"],
        ),
        _liquidity_component(evidence.flow_liquidity, evidence.risk_assessment, normalized["liquidity_execution"]),
        _fundamental_component(
            point_in_time_metrics,
            evidence.sector,
            normalized["fundamental"],
            unavailable_reason=financial_unavailable_reason,
        ),
        _catalyst_component(evidence.corporate_action_context, normalized["catalyst"]),
    ]
    covered_weight = sum(item.weight_percent * item.coverage_percent / 100 for item in components)
    coverage = _clamp(covered_weight)
    contribution = sum(item.contribution_points for item in components)
    evidence_score = contribution / covered_weight * 100 if covered_weight else 0
    persistence, persistence_reason, persistence_supportive = _persistence_multiplier(evidence)
    coverage_adjusted = _clamp(contribution)
    final_score = _clamp(coverage_adjusted * persistence)

    invalidations: list[str] = []
    if evidence.risk_assessment is None:
        invalidations.append("risk_assessment_unavailable")
    elif not evidence.risk_assessment.eligible:
        invalidations.extend(
            f"risk_gate_rejected:{gate.key}"
            for gate in evidence.risk_assessment.gates
            if gate.status == "reject"
        )
    if "intraday_evidence_stale" in evidence.validation_notes:
        invalidations.append("intraday_evidence_stale")
    if coverage < 45:
        invalidations.append("score_coverage_below_45_percent")
    eligible = not invalidations
    if not eligible:
        status = "ineligible" if any(item.startswith("risk_gate_rejected") or item == "intraday_evidence_stale" for item in invalidations) else "insufficient_data"
    elif final_score >= 70:
        status = "high_priority"
    elif final_score >= 55:
        status = "promising"
    elif final_score >= 40:
        status = "watch"
    else:
        status = "low_conviction"

    positives = [factor for component in components for factor in component.positive_factors]
    if persistence_supportive:
        positives.append(persistence_reason)
    cautions = [
        *[factor for component in components for factor in component.cautions],
        *evidence.validation_notes,
    ]
    if not persistence_supportive:
        cautions.append(persistence_reason)
    return OpportunityScoreSnapshot(
        model_version=MODEL_VERSION,
        strategy=STRATEGY,
        calibration_status=CALIBRATION_STATUS,
        evidence_score=round(evidence_score, 4),
        coverage_percent=round(coverage, 4),
        coverage_adjusted_score=round(coverage_adjusted, 4),
        persistence_multiplier=persistence,
        final_score=round(final_score, 4),
        eligible=eligible,
        status=status,
        weights={key: round(value, 4) for key, value in normalized.items()},
        components=components,
        top_positive_factors=list(dict.fromkeys(positives))[:8],
        top_cautions=list(dict.fromkeys(cautions))[:8],
        invalidation_reasons=list(dict.fromkeys(invalidations)),
    )


def rank_opportunities(
    evidence_rows: list[OpportunityEvidenceSnapshot],
    financial_metrics: dict[str, FinancialMetricSnapshot] | None = None,
    session_returns: dict[str, float | None] | None = None,
    current_prices: dict[str, float | None] | None = None,
    *,
    weights: dict[str, float] | None = None,
) -> list[RankedOpportunity]:
    metrics = financial_metrics or {}
    returns = session_returns or {}
    prices = current_prices or {}
    scored = [
        RankedOpportunity(
            instrument_key=row.instrument_key,
            symbol=row.symbol,
            sector=row.sector,
            as_of=row.as_of,
            current_market_price=prices.get(row.instrument_key),
            session_return_percent=returns.get(row.instrument_key),
            score=build_opportunity_score(row, metrics.get(row.instrument_key), weights=weights),
        )
        for row in evidence_rows
    ]
    scored.sort(
        key=lambda item: (
            not item.score.eligible,
            -item.score.final_score,
            -item.score.coverage_percent,
            item.symbol,
        )
    )
    rank = 0
    result = []
    for item in scored:
        item_rank = None
        if item.score.eligible:
            rank += 1
            item_rank = rank
        result.append(item.model_copy(update={"rank": item_rank}))
    return result
