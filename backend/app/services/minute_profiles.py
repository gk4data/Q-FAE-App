"""Build compact, rolling minute-of-session baselines from normalized candles."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from statistics import fmean, median, pstdev

from app.models.market import Candle, MinuteOfDayProfile
from app.services.market_context import INDIA_TIMEZONE

NSE_OPEN_MINUTE = 9 * 60 + 15
NSE_REGULAR_SESSION_MINUTES = 375
PROFILE_CALCULATION_VERSION = 1


def minute_of_session(timestamp: datetime) -> int | None:
    local = timestamp.astimezone(INDIA_TIMEZONE)
    minute = local.hour * 60 + local.minute - NSE_OPEN_MINUTE
    return minute if 0 <= minute < NSE_REGULAR_SESSION_MINUTES else None


def build_minute_profiles(
    candles: list[Candle],
    *,
    exclude_session_date: date | None = None,
    calculated_at: datetime | None = None,
) -> list[MinuteOfDayProfile]:
    """Aggregate prior completed sessions without including today's live observations."""
    grouped: dict[int, list[Candle]] = defaultdict(list)
    for candle in candles:
        if candle.interval != "1minute":
            continue
        local = candle.timestamp.astimezone(INDIA_TIMEZONE)
        if exclude_session_date is not None and local.date() == exclude_session_date:
            continue
        minute = minute_of_session(candle.timestamp)
        if minute is not None:
            grouped[minute].append(candle)

    updated_at = calculated_at or datetime.now(INDIA_TIMEZONE)
    profiles = []
    for minute, samples in sorted(grouped.items()):
        volumes = sorted(float(candle.volume) for candle in samples)
        ranges = [
            (candle.high - candle.low) / candle.close * 10_000
            for candle in samples
            if candle.close > 0 and candle.high >= candle.low
        ]
        returns = [
            abs(candle.close / candle.open - 1) * 10_000
            for candle in samples
            if candle.open > 0
        ]
        traded_values = [candle.close * candle.volume for candle in samples if candle.close > 0]
        profiles.append(
            MinuteOfDayProfile(
                instrument_key=samples[0].instrument_key,
                minute_of_session=minute,
                sample_count=len(samples),
                mean_volume=round(fmean(volumes), 4),
                median_volume=round(median(volumes), 4),
                volume_stddev=round(pstdev(volumes), 4),
                volume_p25=round(_percentile(volumes, 0.25), 4),
                volume_p75=round(_percentile(volumes, 0.75), 4),
                mean_range_bps=round(fmean(ranges), 4) if ranges else None,
                mean_abs_return_bps=round(fmean(returns), 4) if returns else None,
                mean_traded_value_inr=round(fmean(traded_values), 2) if traded_values else None,
                calculation_version=PROFILE_CALCULATION_VERSION,
                data_through=max(candle.timestamp for candle in samples),
                updated_at=updated_at,
            )
        )
    return profiles


def _percentile(sorted_values: list[float], fraction: float) -> float:
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = position - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight

