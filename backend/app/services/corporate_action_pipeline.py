"""Corporate-action adjustment, outcome evaluation, and current evidence context."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta

from app.models.market import (
    AdjustedCandle,
    Candle,
    CorporateAction,
    CorporateActionAdjustment,
    CorporateActionAIAnalysis,
    CorporateActionAssessment,
    CorporateActionCalibrationBucket,
    CorporateActionCalibrationReport,
    CorporateActionContext,
    CorporateActionOutcome,
)
from app.services.corporate_action_assessment import classify_action_type, parse_action_ratio
from app.services.market_context import INDIA_TIMEZONE

ADJUSTMENT_VERSION = 1
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _detail_number(details: dict[str, str], labels: tuple[str, ...]) -> float | None:
    for key, value in details.items():
        normalized = key.casefold().replace("-", " ")
        if not any(label in normalized for label in labels):
            continue
        match = NUMBER.search(value)
        if match:
            return float(match.group().replace(",", ""))
    return None


def build_adjustment(
    action: CorporateAction,
    *,
    reference_close: float | None = None,
    calculated_at: datetime | None = None,
) -> CorporateActionAdjustment:
    """Create a safe backward factor, refusing ambiguous mechanical terms."""
    category = classify_action_type(action.action_type)
    effective_date = action.ex_date or action.record_date
    price_factor: float | None = None
    volume_factor: float | None = None
    status = "not_applicable"
    reason = "action_does_not_require_price_series_adjustment"

    if effective_date is None and category in {"dividend", "bonus", "split"}:
        status, reason = "unavailable", "effective_date_unavailable"
    elif category == "bonus":
        ratio = parse_action_ratio(action.ratio)
        if ratio:
            new, held = ratio
            price_factor = held / (held + new)
            volume_factor = 1 / price_factor
            status, reason = "applied", "bonus_ratio_interpreted_as_new_for_existing"
        else:
            status, reason = "unavailable", "bonus_ratio_unavailable"
    elif category == "split":
        old_face = _detail_number(action.details, ("old face value", "face value before", "from face value"))
        new_face = _detail_number(action.details, ("new face value", "face value after", "to face value"))
        if old_face and new_face and new_face < old_face:
            price_factor = new_face / old_face
            volume_factor = old_face / new_face
            status, reason = "applied", "face_value_change_verified"
        else:
            status, reason = "unavailable", "split_face_value_terms_ambiguous"
    elif category == "dividend":
        amount = action.amount or _detail_number(action.details, ("amount", "dividend per share"))
        if reference_close and amount and 0 < amount < reference_close:
            price_factor = (reference_close - amount) / reference_close
            volume_factor = 1.0
            status, reason = "applied", "total_return_dividend_factor"
        else:
            status, reason = "unavailable", "dividend_amount_or_reference_close_unavailable"

    return CorporateActionAdjustment(
        event_id=action.event_id,
        calculation_version=ADJUSTMENT_VERSION,
        instrument_key=action.instrument_key,
        category=category,
        effective_date=effective_date,
        price_factor=round(price_factor, 10) if price_factor else None,
        volume_factor=round(volume_factor, 10) if volume_factor else None,
        status=status,
        reason=reason,
        reference_close=reference_close,
        calculated_at=calculated_at or datetime.now(UTC),
    )


def adjust_candles(
    candles: list[Candle],
    adjustments: list[CorporateActionAdjustment],
) -> list[AdjustedCandle]:
    applicable = [item for item in adjustments if item.status == "applied" and item.effective_date and item.price_factor and item.volume_factor]
    unresolved = [item for item in adjustments if item.status == "unavailable" and item.effective_date and item.category in {"dividend", "bonus", "split"}]
    rows: list[AdjustedCandle] = []
    for candle in sorted(candles, key=lambda item: item.timestamp):
        candle_date = candle.timestamp.astimezone(INDIA_TIMEZONE).date()
        later = [item for item in applicable if item.effective_date > candle_date]
        price_factor = 1.0
        volume_factor = 1.0
        for item in later:
            price_factor *= item.price_factor or 1
            volume_factor *= item.volume_factor or 1
        partial = any(item.effective_date > candle_date for item in unresolved)
        rows.append(
            AdjustedCandle(
                instrument_key=candle.instrument_key,
                timestamp=candle.timestamp,
                interval=candle.interval,
                raw_open=candle.open,
                raw_high=candle.high,
                raw_low=candle.low,
                raw_close=candle.close,
                raw_volume=candle.volume,
                adjusted_open=round(candle.open * price_factor, 6),
                adjusted_high=round(candle.high * price_factor, 6),
                adjusted_low=round(candle.low * price_factor, 6),
                adjusted_close=round(candle.close * price_factor, 6),
                adjusted_volume=max(0, round(candle.volume * volume_factor)),
                cumulative_price_factor=round(price_factor, 10),
                cumulative_volume_factor=round(volume_factor, 10),
                adjustment_status="partial" if partial else "adjusted" if later else "raw_equivalent",
            )
        )
    return rows


def evaluate_action_outcome(
    action: CorporateAction,
    stock: list[Candle],
    benchmark: list[Candle],
    *,
    evaluated_at: datetime | None = None,
) -> CorporateActionOutcome | None:
    event_date = action.ex_date or action.announcement_date or action.record_date
    if event_date is None:
        return None
    stock = sorted(stock, key=lambda item: item.timestamp)
    benchmark = sorted(benchmark, key=lambda item: item.timestamp)
    prior = [item for item in stock if item.timestamp.astimezone(INDIA_TIMEZONE).date() < event_date]
    after = [item for item in stock if item.timestamp.astimezone(INDIA_TIMEZONE).date() >= event_date]
    if not prior:
        return CorporateActionOutcome(event_id=action.event_id, instrument_key=action.instrument_key, event_date=event_date, outcome_status="pending", evaluated_at=evaluated_at or datetime.now(UTC))
    reference = prior[-1].close
    benchmark_by_date = {item.timestamp.astimezone(INDIA_TIMEZONE).date(): item.close for item in benchmark}
    benchmark_prior = [item for item in benchmark if item.timestamp.astimezone(INDIA_TIMEZONE).date() < event_date]
    benchmark_reference = benchmark_prior[-1].close if benchmark_prior else None
    values: dict[str, float | None] = {}
    for sessions in (1, 5, 20):
        target = after[sessions - 1] if len(after) >= sessions else None
        stock_return = (target.close / reference - 1) * 100 if target else None
        benchmark_close = benchmark_by_date.get(target.timestamp.astimezone(INDIA_TIMEZONE).date()) if target else None
        benchmark_return = (benchmark_close / benchmark_reference - 1) * 100 if benchmark_close and benchmark_reference else None
        values[f"return_{sessions}d_percent"] = round(stock_return, 6) if stock_return is not None else None
        values[f"abnormal_return_{sessions}d_percent"] = round(stock_return - benchmark_return, 6) if stock_return is not None and benchmark_return is not None else None
    status = "complete" if values["return_20d_percent"] is not None else "partial" if after else "pending"
    return CorporateActionOutcome(event_id=action.event_id, instrument_key=action.instrument_key, event_date=event_date, reference_price=reference, outcome_status=status, evaluated_at=evaluated_at or datetime.now(UTC), **values)


def build_corporate_action_context(
    instrument_key: str,
    actions: list[CorporateAction],
    assessments: list[CorporateActionAssessment],
    ai_analyses: list[CorporateActionAIAnalysis],
    *,
    as_of: datetime,
) -> CorporateActionContext:
    today = as_of.astimezone(INDIA_TIMEZONE).date()
    assessment_by_id = {item.event_id: item for item in assessments}
    ai_by_id = {item.event_id: item for item in ai_analyses if item.status == "complete" and item.grounded}
    active = []
    for action in actions:
        start = action.announcement_date or action.ex_date or action.record_date
        end = action.ex_date or action.record_date or start
        if start and end and start - timedelta(days=5) <= today <= end + timedelta(days=5):
            active.append(action)
    active_assessments = [assessment_by_id[item.event_id] for item in active if item.event_id in assessment_by_id]
    active_ai = [ai_by_id[item.event_id] for item in active if item.event_id in ai_by_id]
    deterministic = max(active_assessments, key=lambda item: item.materiality_score).sentiment_score if active_assessments else None
    ai_score = max(active_ai, key=lambda item: item.confidence or 0).impact_score if active_ai else None
    effective = ai_score if ai_score is not None else deterministic
    state = "unavailable" if effective is None else "positive" if effective >= 10 else "negative" if effective <= -10 else "neutral"
    evidence = [f"active_{assessment.category}" for assessment in active_assessments]
    cautions = []
    if active and not active_ai:
        cautions.append("grounded_ai_analysis_unavailable")
    return CorporateActionContext(
        instrument_key=instrument_key,
        as_of=as_of,
        state=state,
        active_events=len(active),
        maximum_materiality=max((item.materiality_score for item in active_assessments), default=None),
        deterministic_sentiment=deterministic,
        ai_impact_score=ai_score,
        effective_score=effective,
        evidence=evidence,
        cautions=cautions,
    )


def build_calibration_report(
    assessments: list[CorporateActionAssessment],
    outcomes: list[CorporateActionOutcome],
    *,
    generated_at: datetime | None = None,
    minimum_observations: int = 30,
) -> CorporateActionCalibrationReport:
    """Summarize observed abnormal returns without changing production weights."""
    assessment_by_id = {item.event_id: item for item in assessments}
    grouped: dict[tuple[str, str, int], list[float]] = {}
    for outcome in outcomes:
        assessment = assessment_by_id.get(outcome.event_id)
        if assessment is None:
            continue
        for horizon in (1, 5, 20):
            value = getattr(outcome, f"abnormal_return_{horizon}d_percent")
            if value is not None:
                grouped.setdefault((assessment.category, assessment.direction, horizon), []).append(value)
    buckets = []
    for (category, direction, horizon), values in sorted(grouped.items()):
        observations = len(values)
        buckets.append(
            CorporateActionCalibrationBucket(
                category=category,
                direction=direction,
                horizon_sessions=horizon,
                observations=observations,
                mean_abnormal_return_percent=round(sum(values) / observations, 6),
                positive_rate=round(sum(value > 0 for value in values) / observations, 6),
                readiness="ready" if observations >= minimum_observations else "insufficient_sample",
            )
        )
    return CorporateActionCalibrationReport(
        generated_at=generated_at or datetime.now(UTC),
        minimum_observations=minimum_observations,
        buckets=buckets,
    )
