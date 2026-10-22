from datetime import datetime, timezone, timedelta

from app.models.market import Candle, FinancialMetricSnapshot, OpportunityEvidenceSnapshot
from app.services.opportunity_scoring import build_opportunity_score, rank_opportunities

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 9, 14, 10, 0, tzinfo=IST)


def _evidence(symbol: str, *, supportive: bool = True, rejected: bool = False) -> OpportunityEvidenceSnapshot:
    state = "supportive" if supportive else "caution"
    positive = 4 if supportive else 0
    cautions = 0 if supportive else 4
    return OpportunityEvidenceSnapshot.model_validate(
        {
            "instrument_key": f"NSE_EQ|{symbol}",
            "symbol": symbol,
            "sector": "Auto Ancillary",
            "as_of": NOW,
            "data_quality": "complete",
            "confluence": "strong_support" if supportive else "caution",
            "pillars": [
                {
                    "key": "intraday", "label": "Intraday", "state": state,
                    "available_checks": 4, "supportive_checks": positive,
                    "caution_checks": cautions,
                    "evidence": ["intraday_support"] if supportive else [],
                    "cautions": [] if supportive else ["intraday_caution"],
                },
                {
                    "key": "daily", "label": "Daily", "state": state,
                    "available_checks": 4, "supportive_checks": positive,
                    "caution_checks": cautions,
                },
                {
                    "key": "relative_strength", "label": "Relative", "state": state,
                    "available_checks": 4, "supportive_checks": positive,
                    "caution_checks": cautions,
                },
            ],
            "flow_liquidity": {
                "instrument_key": f"NSE_EQ|{symbol}", "symbol": symbol, "as_of": NOW,
                "data_quality": "complete", "relative_volume": 2 if supportive else 0.5,
                "volume_acceleration": 1.5 if supportive else 0.5,
                "passes_spread_filter": not rejected,
                "passes_traded_value_filter": True,
                "volume_state": "strong" if supportive else "weak",
                "liquidity_state": "rejected" if rejected else "pass",
                "confirmation": "rejected" if rejected else "strong_confirmation",
            },
            "signal_persistence": {
                "instrument_key": f"NSE_EQ|{symbol}", "symbol": symbol, "as_of": NOW,
                "state": "confirmed" if supportive else "neutral",
                "supportive_minutes": 3 if supportive else 0,
                "caution_minutes": 0 if supportive else 3,
                "observed_minutes": 3,
                "reason": "support_repeated" if supportive else "support_absent",
            },
            "risk_assessment": {
                "instrument_key": f"NSE_EQ|{symbol}", "symbol": symbol, "as_of": NOW,
                "eligible": not rejected, "status": "rejected" if rejected else "pass",
                "reference_order_value_inr": 100000,
                "gates": [
                    {
                        "key": "spread", "status": "reject" if rejected else "pass",
                        "reason": "spread_result",
                    },
                    {"key": "freshness", "status": "pass", "reason": "fresh"},
                ],
            },
            "market_regime": {
                "as_of": NOW, "state": "risk_on", "observations": 3,
                "evidence": ["market_participation_supportive"],
            },
        }
    )


def _financials(symbol: str) -> FinancialMetricSnapshot:
    return FinancialMetricSnapshot.model_validate(
        {
            "source_snapshot_id": symbol.lower(),
            "isin": f"ISIN{symbol}",
            "instrument_key": f"NSE_EQ|{symbol}",
            "symbol": symbol,
            "growth": {
                "revenue_qoq_percent": 20, "revenue_yoy_percent": 30,
                "operating_profit_yoy_percent": 35, "net_profit_yoy_percent": 35,
            },
            "margins": {
                "operating_margin_yoy_change_pp": 5, "net_margin_yoy_change_pp": 5,
            },
            "capital": {
                "operating_cash_conversion_percent": 125, "total_debt_crore": 20,
                "debt_yoy_change_percent": -25, "debt_to_equity": 0,
                "roe_percent": 25, "roce_percent": 25,
            },
            "eps": {"latest_basic_eps": 10, "yoy_growth_percent": 30},
            "data_quality": "complete",
            "calculated_at": NOW,
        }
    )


def test_supportive_complete_evidence_produces_explainable_high_priority_score() -> None:
    result = build_opportunity_score(_evidence("GOOD"), _financials("GOOD"))

    assert result.eligible is True
    assert result.status == "high_priority"
    assert result.final_score >= 90
    assert result.coverage_percent == 100
    assert sum(result.weights.values()) == 100
    assert {item.key for item in result.components} == {
        "price_trend", "participation", "market_sector", "fundamental",
    }
    assert "intraday_support" in result.top_positive_factors
    assert "liquidity_execution" not in result.weights


def test_rejected_execution_gate_does_not_change_opportunity_eligibility() -> None:
    result = build_opportunity_score(_evidence("WIDE", rejected=True), _financials("WIDE"))

    assert result.eligible is True
    assert result.status == "high_priority"
    assert not any(item.startswith("risk_gate_rejected") for item in result.invalidation_reasons)


def test_low_turnover_watch_only_stock_keeps_strength_but_stays_outside_active_rank() -> None:
    evidence = _evidence("WATCH").model_copy(
        update={
            "liquidity_tier": "watch_only",
            "liquidity_tier_reason": "rolling_median_traded_value_below_active_threshold",
        }
    )

    result = build_opportunity_score(evidence, _financials("WATCH"))

    assert result.final_score >= 90
    assert result.eligible is False
    assert result.status == "ineligible"
    assert (
        "rolling_liquidity_filter:watch_only:rolling_median_traded_value_below_active_threshold"
        in result.invalidation_reasons
    )


def test_missing_inputs_reduce_coverage_instead_of_becoming_neutral_values() -> None:
    evidence = _evidence("SPARSE").model_copy(
        update={"risk_assessment": None}
    )
    result = build_opportunity_score(evidence, None)

    assert result.coverage_percent < 100
    assert result.eligible is True
    assert "risk_assessment_unavailable" not in result.invalidation_reasons
    fundamental = next(item for item in result.components if item.key == "fundamental")
    assert fundamental.score is None
    assert fundamental.unavailable_inputs == ["financial_metrics"]


def test_financial_snapshot_newer_than_the_evidence_is_not_used() -> None:
    future_metrics = _financials("GOOD").model_copy(
        update={"calculated_at": NOW + timedelta(minutes=1)}
    )

    result = build_opportunity_score(_evidence("GOOD"), future_metrics)

    fundamental = next(item for item in result.components if item.key == "fundamental")
    assert fundamental.score is None
    assert fundamental.unavailable_inputs == ["financial_metrics_newer_than_evidence"]


def test_ranking_ignores_execution_rejection_but_preserves_it_as_separate_context() -> None:
    good = _evidence("GOOD")
    weak = _evidence("WEAK", supportive=False)
    rejected = _evidence("REJECT", rejected=True)
    rows = rank_opportunities(
        [weak, rejected, good],
        {
            good.instrument_key: _financials("GOOD"),
            weak.instrument_key: _financials("WEAK"),
            rejected.instrument_key: _financials("REJECT"),
        },
        {good.instrument_key: 3.25, weak.instrument_key: -1.5},
        {good.instrument_key: 125.5, weak.instrument_key: 88.2},
        {
            good.instrument_key: Candle(
                instrument_key=good.instrument_key,
                timestamp=NOW,
                interval="day",
                open=120,
                high=127,
                low=119,
                close=125.5,
                volume=500_000,
            )
        },
        {good.instrument_key: [120, 121.5, 123, 125.5]},
    )

    assert [item.symbol for item in rows] == ["GOOD", "REJECT", "WEAK"]
    assert [item.rank for item in rows] == [1, 2, 3]
    assert rows[1].execution_risk is not None
    assert rows[1].execution_risk.eligible is False
    assert rows[0].session_return_percent == 3.25
    assert rows[0].current_market_price == 125.5
    assert (rows[0].day_open, rows[0].day_high, rows[0].day_low, rows[0].day_close) == (
        120,
        127,
        119,
        125.5,
    )
    assert rows[0].price_trace == [120, 121.5, 123, 125.5]
    assert rows[2].session_return_percent == -1.5
