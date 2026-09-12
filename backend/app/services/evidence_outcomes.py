"""Forward-return and excursion calculations for point-in-time evidence."""

from __future__ import annotations

from datetime import timedelta

from app.models.market import Candle, EvidenceOutcomeObservation


HORIZONS = {
    "forward_return_5m_percent": 5,
    "forward_return_15m_percent": 15,
    "forward_return_30m_percent": 30,
    "forward_return_60m_percent": 60,
}


def _return_percent(reference: float, value: float) -> float:
    return round((value / reference - 1) * 100, 6)


def evaluate_observation(
    observation: EvidenceOutcomeObservation,
    candles: list[Candle],
    *,
    eod_close: float | None = None,
) -> EvidenceOutcomeObservation:
    """Fill only horizons observable without looking ahead beyond available candles."""
    future = sorted(
        (
            candle
            for candle in candles
            if candle.instrument_key == observation.instrument_key
            and candle.timestamp > observation.candle_timestamp
        ),
        key=lambda candle: candle.timestamp,
    )
    updates: dict[str, object] = {}
    for field, minutes in HORIZONS.items():
        if getattr(observation, field) is not None:
            continue
        target = observation.candle_timestamp + timedelta(minutes=minutes)
        match = next((candle for candle in future if candle.timestamp >= target), None)
        if match is not None:
            updates[field] = _return_percent(observation.reference_price, match.close)

    excursion_end = observation.candle_timestamp + timedelta(minutes=60)
    excursion = [candle for candle in future if candle.timestamp <= excursion_end]
    if excursion:
        updates["mfe_60m_percent"] = _return_percent(
            observation.reference_price,
            max(candle.high for candle in excursion),
        )
        updates["mae_60m_percent"] = _return_percent(
            observation.reference_price,
            min(candle.low for candle in excursion),
        )
        updates["evaluated_through"] = excursion[-1].timestamp
    if eod_close is not None and eod_close > 0:
        updates["forward_return_eod_percent"] = _return_percent(
            observation.reference_price,
            eod_close,
        )
    candidate = observation.model_copy(update=updates)
    intraday_complete = all(getattr(candidate, field) is not None for field in HORIZONS)
    status = "complete" if intraday_complete and candidate.forward_return_eod_percent is not None else "partial" if updates or any(getattr(candidate, field) is not None for field in HORIZONS) else "pending"
    return candidate.model_copy(update={"outcome_status": status})
