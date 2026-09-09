"""Multi-horizon daily evidence that complements, but never vetoes, intraday strength."""

from __future__ import annotations

from datetime import datetime, time
from statistics import fmean

from app.models.market import (
    Candle,
    DailyParticipationFeatures,
    DailyRegimeSnapshot,
    DailyStructureFeatures,
    DailyTrendFeatures,
    DailyVolatilityFeatures,
    HorizonPerformance,
)
from app.services.market_features import sector_index_for
from app.services.upstox_market import INDIA_TIMEZONE, NIFTY_50_KEY

HORIZONS = (5, 20, 60, 120, 250)


def _percent_change(current: float | None, base: float | None) -> float | None:
    if current is None or base is None or base == 0:
        return None
    return round((current / base - 1) * 100, 4)


def _return(candles: list[Candle], sessions: int) -> float | None:
    if len(candles) <= sessions:
        return None
    return _percent_change(candles[-1].close, candles[-sessions - 1].close)


def _sma(candles: list[Candle], sessions: int, offset: int = 0) -> float | None:
    end = len(candles) - offset
    start = end - sessions
    if start < 0 or end <= 0:
        return None
    return round(fmean(candle.close for candle in candles[start:end]), 4)


def _sma_slope(candles: list[Candle], sessions: int, offset: int) -> float | None:
    current = _sma(candles, sessions)
    previous = _sma(candles, sessions, offset)
    return _percent_change(current, previous)


def _true_ranges(candles: list[Candle]) -> list[float]:
    values: list[float] = []
    for index, candle in enumerate(candles):
        value = candle.high - candle.low
        if index:
            previous_close = candles[index - 1].close
            value = max(value, abs(candle.high - previous_close), abs(candle.low - previous_close))
        values.append(value)
    return values


def aggregate_session_candle(
    instrument_key: str,
    minute_candles: list[Candle],
    completed_candle: Candle | None,
) -> Candle | None:
    """Aggregate completed one-minute candles into a provisional daily candle."""
    if completed_candle is None:
        return None
    session_date = completed_candle.timestamp.astimezone(INDIA_TIMEZONE).date()
    session = sorted(
        (
            candle
            for candle in minute_candles
            if candle.timestamp.astimezone(INDIA_TIMEZONE).date() == session_date
            and candle.timestamp <= completed_candle.timestamp
        ),
        key=lambda candle: candle.timestamp,
    )
    if not session:
        return None
    return Candle(
        instrument_key=instrument_key,
        timestamp=datetime.combine(session_date, time.min, tzinfo=INDIA_TIMEZONE),
        interval="day",
        open=session[0].open,
        high=max(candle.high for candle in session),
        low=min(candle.low for candle in session),
        close=session[-1].close,
        volume=sum(candle.volume for candle in session),
        source="qfae-live-aggregate",
    )


def merge_daily_history(history: list[Candle], provisional: Candle | None) -> list[Candle]:
    """Replace the same session date with live evidence instead of double counting it."""
    if provisional is None:
        return sorted(history, key=lambda candle: candle.timestamp)
    session_date = provisional.timestamp.astimezone(INDIA_TIMEZONE).date()
    merged = [
        candle
        for candle in history
        if candle.timestamp.astimezone(INDIA_TIMEZONE).date() != session_date
    ]
    merged.append(provisional)
    return sorted(merged, key=lambda candle: candle.timestamp)


def _horizon_performance(
    stock: list[Candle],
    nifty: list[Candle],
    sector: list[Candle] | None,
) -> list[HorizonPerformance]:
    rows = []
    for sessions in HORIZONS:
        stock_return = _return(stock, sessions)
        nifty_return = _return(nifty, sessions)
        sector_return = _return(sector or [], sessions)
        rows.append(
            HorizonPerformance(
                sessions=sessions,
                stock_return_percent=stock_return,
                nifty_return_percent=nifty_return,
                versus_nifty_percent=(
                    round(stock_return - nifty_return, 4)
                    if stock_return is not None and nifty_return is not None
                    else None
                ),
                sector_return_percent=sector_return,
                versus_sector_percent=(
                    round(stock_return - sector_return, 4)
                    if stock_return is not None and sector_return is not None
                    else None
                ),
            )
        )
    return rows


def _trend(candles: list[Candle]) -> DailyTrendFeatures:
    close = candles[-1].close
    sma20 = _sma(candles, 20)
    sma50 = _sma(candles, 50)
    sma100 = _sma(candles, 100)
    sma200 = _sma(candles, 200)
    slope20 = _sma_slope(candles, 20, 5)
    slope50 = _sma_slope(candles, 50, 10)

    available = [value for value in (sma20, sma50, sma100, sma200) if value is not None]
    if len(available) >= 3 and all(left > right for left, right in zip(available, available[1:])):
        alignment = "bullish"
    elif len(available) >= 3 and all(left < right for left, right in zip(available, available[1:])):
        alignment = "bearish"
    elif available:
        alignment = "mixed"
    else:
        alignment = "unavailable"

    if sma20 is None:
        regime = "forming"
    elif sma50 is not None and close > sma20 > sma50 and (slope20 or 0) > 0:
        regime = "established_uptrend"
    elif close > sma20 and (slope20 or 0) > 0:
        regime = "emerging_uptrend"
    elif sma50 is not None and close < sma20 and sma20 > sma50:
        regime = "pullback_in_uptrend"
    elif sma50 is not None and close < sma20 < sma50:
        regime = "downtrend"
    else:
        regime = "mixed"

    return DailyTrendFeatures(
        sma_20=sma20,
        sma_50=sma50,
        sma_100=sma100,
        sma_200=sma200,
        above_sma_20_percent=_percent_change(close, sma20),
        above_sma_50_percent=_percent_change(close, sma50),
        sma_20_slope_5d_percent=slope20,
        sma_50_slope_10d_percent=slope50,
        alignment=alignment,
        regime=regime,
    )


def _structure(candles: list[Candle]) -> DailyStructureFeatures:
    close = candles[-1].close

    def prior_high(sessions: int) -> float | None:
        sample = candles[-sessions - 1 : -1]
        return max((candle.high for candle in sample), default=None)

    high20 = prior_high(20)
    high60 = prior_high(60)
    high252 = prior_high(252)
    window = candles[-20:]
    window_high = max((candle.high for candle in window), default=None)
    window_low = min((candle.low for candle in window), default=None)
    range_percent = (
        round((window_high - window_low) / close * 100, 4)
        if window_high is not None and window_low is not None and close
        else None
    )
    close_location = (
        round((close - window_low) / (window_high - window_low), 4)
        if window_high is not None and window_low is not None and window_high > window_low
        else None
    )
    comparisons = [
        candles[index].close > candles[index - 1].close
        for index in range(max(1, len(candles) - 19), len(candles))
    ]
    positive_ratio = round(sum(comparisons) / len(comparisons), 4) if comparisons else None
    efficiency = None
    if len(candles) >= 21:
        closes = [candle.close for candle in candles[-21:]]
        path = sum(abs(current - previous) for previous, current in zip(closes, closes[1:]))
        efficiency = round(abs(closes[-1] - closes[0]) / path, 4) if path else 0.0
    distance20 = _percent_change(close, high20)
    distance60 = _percent_change(close, high60)
    drawdown252 = _percent_change(close, high252)
    if distance20 is not None and distance20 > 0:
        state = "breakout_20d"
    elif distance20 is not None and distance20 >= -3:
        state = "near_20d_high"
    elif range_percent is not None and range_percent <= 10:
        state = "tight_base"
    elif distance60 is not None and distance60 <= -15:
        state = "deep_pullback"
    else:
        state = "developing"
    return DailyStructureFeatures(
        distance_to_20d_high_percent=distance20,
        distance_to_60d_high_percent=distance60,
        drawdown_from_252d_high_percent=drawdown252,
        close_location_20d=close_location,
        range_20d_percent=range_percent,
        positive_close_ratio_20d=positive_ratio,
        trend_efficiency_20d=efficiency,
        state=state,
    )


def cumulative_relative_volume(
    minute_candles: list[Candle],
    completed_candle: Candle | None,
) -> float | None:
    """Compare current cumulative volume with prior sessions at the same minute."""
    if completed_candle is None:
        return None
    local_completed = completed_candle.timestamp.astimezone(INDIA_TIMEZONE)
    current_date = local_completed.date()
    target_time = local_completed.time()
    totals: dict[object, int] = {}
    for candle in minute_candles:
        local_timestamp = candle.timestamp.astimezone(INDIA_TIMEZONE)
        if local_timestamp.time() > target_time:
            continue
        totals[local_timestamp.date()] = totals.get(local_timestamp.date(), 0) + candle.volume
    current_volume = totals.pop(current_date, 0)
    prior_totals = [volume for volume in totals.values() if volume > 0]
    if current_volume <= 0 or not prior_totals:
        return None
    return round(current_volume / fmean(prior_totals), 4)


def _participation(
    candles: list[Candle],
    live_relative_volume: float | None,
) -> DailyParticipationFeatures:
    latest = candles[-1]
    prior20 = candles[-21:-1]
    average_volume = fmean(candle.volume for candle in prior20) if prior20 else None
    if latest.source == "qfae-live-aggregate":
        rvol = live_relative_volume
        rvol_basis = "cumulative_same_time"
    else:
        rvol = round(latest.volume / average_volume, 4) if average_volume and average_volume > 0 else None
        rvol_basis = "full_session_20d"
    up_volumes: list[int] = []
    down_volumes: list[int] = []
    start = max(1, len(candles) - 20)
    for index in range(start, len(candles)):
        if candles[index].close >= candles[index - 1].close:
            up_volumes.append(candles[index].volume)
        else:
            down_volumes.append(candles[index].volume)
    down_average = fmean(down_volumes) if down_volumes else None
    up_down_ratio = (
        round(fmean(up_volumes) / down_average, 4)
        if up_volumes and down_average and down_average > 0
        else None
    )
    if rvol is None or len(candles) < 2:
        direction = "unavailable"
    elif rvol < 1.5:
        direction = "normal_volume"
    elif latest.close > candles[-2].close:
        direction = "high_volume_up"
    elif latest.close < candles[-2].close:
        direction = "high_volume_down"
    else:
        direction = "high_volume_flat"
    return DailyParticipationFeatures(
        latest_volume=latest.volume,
        relative_volume=rvol,
        relative_volume_basis=rvol_basis,
        up_down_volume_ratio_20=up_down_ratio,
        high_volume_direction=direction,
    )


def _volatility(candles: list[Candle]) -> DailyVolatilityFeatures:
    ranges = _true_ranges(candles)
    atr14 = round(fmean(ranges[-14:]), 4) if len(ranges) >= 14 else None
    atr50 = round(fmean(ranges[-50:]), 4) if len(ranges) >= 50 else None
    prior_atr14 = fmean(ranges[-15:-1]) if len(ranges) >= 15 else None
    latest_range_atr = round(ranges[-1] / prior_atr14, 4) if prior_atr14 and prior_atr14 > 0 else None
    atr_ratio = round(atr14 / atr50, 4) if atr14 is not None and atr50 else None
    if latest_range_atr is not None and latest_range_atr >= 1.5:
        state = "range_expansion"
    elif atr_ratio is not None and atr_ratio <= 0.75:
        state = "compressed"
    elif atr_ratio is not None and atr_ratio >= 1.25:
        state = "elevated"
    elif atr14 is not None:
        state = "normal"
    else:
        state = "forming"
    return DailyVolatilityFeatures(
        atr_14=atr14,
        atr_14_percent=round(atr14 / candles[-1].close * 100, 4) if atr14 and candles[-1].close else None,
        atr_14_vs_50=atr_ratio,
        latest_range_atr=latest_range_atr,
        state=state,
    )


def build_daily_regime(
    instrument_key: str,
    symbol: str,
    sector_name: str | None,
    stock_history: list[Candle],
    benchmark_histories: dict[str, list[Candle]],
    *,
    as_of: datetime,
    live_relative_volume: float | None = None,
) -> DailyRegimeSnapshot | None:
    """Build independent horizon evidence without a composite score or hard gate."""
    stock = sorted(stock_history, key=lambda candle: candle.timestamp)
    if not stock:
        return None
    nifty = sorted(benchmark_histories.get(NIFTY_50_KEY, []), key=lambda candle: candle.timestamp)
    mapped_sector = sector_index_for(sector_name)
    sector = (
        sorted(benchmark_histories.get(mapped_sector[0], []), key=lambda candle: candle.timestamp)
        if mapped_sector
        else None
    )
    horizons = _horizon_performance(stock, nifty, sector)
    trend = _trend(stock)
    structure = _structure(stock)
    participation = _participation(stock, live_relative_volume)
    volatility = _volatility(stock)
    horizon_by_sessions = {row.sessions: row for row in horizons}
    evidence: list[str] = []
    cautions: list[str] = []
    return5 = horizon_by_sessions[5].stock_return_percent
    return20 = horizon_by_sessions[20].stock_return_percent
    return120 = horizon_by_sessions[120].stock_return_percent
    return250 = horizon_by_sessions[250].stock_return_percent
    versus_nifty20 = horizon_by_sessions[20].versus_nifty_percent

    if return5 is not None and return5 > 0:
        evidence.append("positive_5d_momentum")
    if return20 is not None and return20 > 0:
        evidence.append("positive_20d_momentum")
    if versus_nifty20 is not None and versus_nifty20 > 0:
        evidence.append("outperforming_nifty_20d")
    if trend.regime in {"emerging_uptrend", "established_uptrend"}:
        evidence.append(trend.regime)
    if participation.high_volume_direction == "high_volume_up":
        evidence.append("volume_confirmed_advance")
    if structure.state in {"breakout_20d", "near_20d_high", "tight_base"}:
        evidence.append(structure.state)
    if return20 is not None and return20 > 0 and any(
        value is not None and value < 0 for value in (return120, return250)
    ):
        evidence.append("short_term_strength_despite_weak_long_history")

    if return250 is not None and return250 < 0:
        cautions.append("weak_250d_history_not_a_veto")
    if trend.above_sma_20_percent is not None and trend.above_sma_20_percent >= 10:
        cautions.append("extended_above_sma20")
    if participation.relative_volume is not None and participation.relative_volume < 0.7:
        cautions.append("low_volume_participation")
    if volatility.latest_range_atr is not None and volatility.latest_range_atr >= 1.8:
        cautions.append("large_daily_range")

    sessions = len(stock)
    data_quality = "complete" if sessions >= 251 and len(nifty) >= 251 else "partial" if sessions >= 60 else "limited"
    return DailyRegimeSnapshot(
        instrument_key=instrument_key,
        symbol=symbol,
        sector=sector_name,
        as_of=as_of,
        data_through=stock[-1].timestamp,
        sessions_available=sessions,
        data_quality=data_quality,
        horizon_performance=horizons,
        trend=trend,
        structure=structure,
        participation=participation,
        volatility=volatility,
        evidence=evidence,
        cautions=cautions,
    )
