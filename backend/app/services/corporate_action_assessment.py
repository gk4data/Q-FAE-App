"""Deterministic corporate-action classification and materiality metrics."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime

from app.models.market import CorporateAction, CorporateActionAssessment

ASSESSMENT_VERSION = 1
NUMBER_PATTERN = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
RATIO_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*[:/]\s*(\d+(?:\.\d+)?)")


def classify_action_type(action_type: str) -> str:
    value = action_type.casefold().replace("-", " ")
    if "buyback" in value or "buy back" in value:
        return "buyback"
    if "dividend" in value:
        return "dividend"
    if "bonus" in value:
        return "bonus"
    if "split" in value or "sub division" in value or "subdivision" in value:
        return "split"
    if "right" in value:
        return "rights"
    if "demerger" in value:
        return "demerger"
    if "merger" in value or "amalgamation" in value:
        return "merger"
    if "delist" in value:
        return "delisting"
    return "other"


def _number_from_details(details: dict[str, str], keys: tuple[str, ...]) -> float | None:
    for label, raw_value in details.items():
        normalized = label.casefold().replace("-", " ")
        if not any(key in normalized for key in keys):
            continue
        match = NUMBER_PATTERN.search(raw_value)
        if match:
            try:
                return float(match.group().replace(",", ""))
            except ValueError:
                continue
    return None


def parse_action_ratio(value: str | None) -> tuple[float, float] | None:
    if not value:
        return None
    match = RATIO_PATTERN.search(value)
    if not match:
        return None
    first, second = float(match.group(1)), float(match.group(2))
    return (first, second) if first > 0 and second > 0 else None


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def assess_corporate_action(
    action: CorporateAction,
    *,
    reference_price: float | None = None,
    reference_price_date: date | None = None,
    assessed_at: datetime | None = None,
) -> CorporateActionAssessment:
    """Calculate transparent factual metrics without predicting price direction using AI."""
    category = classify_action_type(action.action_type)
    metrics: dict[str, float | str | None] = {}
    evidence: list[str] = [f"classified_as_{category}"]
    cautions: list[str] = []
    materiality = 10.0
    sentiment = 0.0
    direction = "contextual"
    horizon = "event_window"

    if category == "dividend":
        amount = action.amount or _number_from_details(action.details, ("amount", "dividend per share"))
        dividend_yield = amount / reference_price * 100 if amount and reference_price else None
        metrics.update(dividend_per_share=amount, dividend_yield_percent=dividend_yield)
        if dividend_yield is None:
            materiality = 15
            cautions.append("dividend_yield_unavailable")
        else:
            materiality = _clamp(dividend_yield * 20, 5, 100)
            sentiment = _clamp(dividend_yield * 8, 0, 40)
            direction = "positive" if dividend_yield >= 1 else "contextual"
            evidence.append("dividend_yield_calculated")
        cautions.extend(["dividend_expectation_unavailable", "cash_flow_support_unchecked"])
        horizon = "announcement_to_ex_date"

    elif category in {"buyback", "delisting"}:
        offer_price = _number_from_details(
            action.details,
            ("buyback price", "buy back price", "offer price", "exit price"),
        ) or action.amount
        premium = (offer_price / reference_price - 1) * 100 if offer_price and reference_price else None
        metrics.update(offer_price=offer_price, offer_premium_percent=premium)
        if premium is None:
            materiality = 30
            cautions.append("offer_premium_unavailable")
        else:
            materiality = _clamp(abs(premium) * 2.5, 10, 100)
            sentiment = _clamp(premium * 1.5, -60, 60)
            direction = "positive" if premium >= 5 else "negative" if premium < 0 else "contextual"
            evidence.append("offer_premium_calculated")
        cautions.extend(["acceptance_ratio_unavailable", "funding_and_completion_risk_unchecked"])
        horizon = "announcement_to_completion"

    elif category == "rights":
        ratio = parse_action_ratio(action.ratio)
        dilution = ratio[0] / ratio[1] * 100 if ratio else None
        issue_price = _number_from_details(action.details, ("issue price", "rights price", "offer price"))
        discount = (1 - issue_price / reference_price) * 100 if issue_price and reference_price else None
        metrics.update(
            issue_price=issue_price,
            issue_discount_percent=discount,
            new_shares_per_100_existing=dilution,
            ratio=action.ratio,
        )
        materiality = _clamp(max(dilution or 0, abs(discount or 0)), 15, 100)
        sentiment = -_clamp((dilution or 0) * 0.6, 0, 55)
        direction = "negative" if dilution is not None and dilution >= 20 else "contextual"
        if dilution is not None:
            evidence.append("rights_dilution_estimated")
        else:
            cautions.append("rights_ratio_unavailable")
        cautions.extend(["use_of_proceeds_unchecked", "shareholder_participation_unavailable"])
        horizon = "announcement_to_allotment"

    elif category == "bonus":
        ratio = parse_action_ratio(action.ratio)
        issuance = ratio[0] / ratio[1] if ratio else None
        metrics.update(bonus_shares_per_existing_share=issuance, ratio=action.ratio)
        materiality = _clamp((issuance or 0.25) * 60, 10, 100)
        direction = "neutral"
        evidence.append("bonus_is_economically_neutral")
        cautions.append("possible_liquidity_effect_not_value_creation")
        horizon = "ex_date_mechanical"

    elif category == "split":
        ratio = parse_action_ratio(action.ratio)
        magnitude = max(ratio) / min(ratio) if ratio else None
        metrics.update(stated_ratio=action.ratio, ratio_magnitude=magnitude)
        materiality = _clamp(((magnitude or 1) - 1) * 20, 10, 100)
        direction = "neutral"
        evidence.append("split_is_economically_neutral")
        cautions.append("ratio_semantics_require_adjustment_validation")
        horizon = "ex_date_mechanical"

    elif category in {"merger", "demerger"}:
        materiality = 60
        direction = "contextual"
        cautions.extend(["transaction_terms_require_document_review", "value_transfer_not_quantified"])
        horizon = "announcement_to_effective_date"

    else:
        materiality = 10
        direction = "contextual"
        cautions.append("unsupported_action_requires_review")

    known_category = category != "other"
    confidence = 0.35 + (0.2 if known_category else 0) + (0.2 if reference_price else 0) + (0.15 if action.announcement_date or action.ex_date else 0) + (0.1 if action.amount is not None or action.ratio else 0)
    return CorporateActionAssessment(
        event_id=action.event_id,
        assessment_version=ASSESSMENT_VERSION,
        isin=action.isin,
        instrument_key=action.instrument_key,
        symbol=action.symbol,
        category=category,
        direction=direction,
        materiality_score=round(materiality, 2),
        sentiment_score=round(sentiment, 2),
        confidence=round(_clamp(confidence, 0, 1), 2),
        impact_horizon=horizon,
        reference_price=reference_price,
        reference_price_date=reference_price_date,
        derived_metrics={key: round(value, 4) if isinstance(value, float) else value for key, value in metrics.items()},
        evidence=evidence,
        cautions=cautions,
        requires_ai_review=bool(cautions) or category in {"rights", "buyback", "delisting", "merger", "demerger", "other"},
        assessed_at=assessed_at or datetime.now(UTC),
    )
