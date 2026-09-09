"""Explainable minute-level technical and execution feature calculations."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from statistics import fmean

from app.models.market import (
    Candle,
    GapFeatures,
    LiquidityFeatures,
    LiveSnapshot,
    MomentumFeatures,
    OpeningRangeFeatures,
    PullbackFeatures,
    RelativeStrengthFeatures,
    RelativeVolumeMetric,
    StockFeatureSnapshot,
    VWAPFeatures,
    VolatilityFeatures,
    VolumeFeatures,
)
from app.services.upstox_market import INDIA_TIMEZONE, NIFTY_50_KEY

SECTOR_INDEX_RULES: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (("psu bank",), "NSE_INDEX|Nifty PSU Bank", "Nifty PSU Bank"),
    (("nbfc", "finance", "financial"), "NSE_INDEX|Nifty Fin Service", "Nifty Financial Services"),
    (("bank",), "NSE_INDEX|Nifty Bank", "Nifty Bank"),
    (("auto", "automobile"), "NSE_INDEX|Nifty Auto", "Nifty Auto"),
    (("jewellery", "diamond", "consumer durable"), "NSE_INDEX|NIFTY CONSR DURBL", "Nifty Consumer Durables"),
    (("pharma", "bio", "health"), "NSE_INDEX|Nifty Pharma", "Nifty Pharma"),
    (("it -", "software", "technology", "hardware"), "NSE_INDEX|Nifty IT", "Nifty IT"),
    (("steel", "iron", "metal"), "NSE_INDEX|Nifty Metal", "Nifty Metal"),
    (("food", "fmcg"), "NSE_INDEX|Nifty FMCG", "Nifty FMCG"),
    (("media",), "NSE_INDEX|Nifty Media", "Nifty Media"),
    (("construction", "realty", "real estate"), "NSE_INDEX|Nifty Realty", "Nifty Realty"),
    (("oil", "gas", "refiner"), "NSE_INDEX|NIFTY OIL AND GAS", "Nifty Oil & Gas"),
)


def _percent_change(current: float | None, base: float | None) -> float | None:
    if current is None or base is None or base == 0:
        return None
    return round((current / base - 1) * 100, 4)


def _snapshot_change(snapshot: LiveSnapshot | None) -> float | None:
    if snapshot is None:
        return None
    return _percent_change(snapshot.ltp, snapshot.previous_close)


def sector_index_for(sector: str | None) -> tuple[str, str] | None:
    """Map provider industry labels to a transparent broad NIFTY benchmark."""
    if not sector:
        return None
    normalized = sector.casefold()
    for terms, instrument_key, label in SECTOR_INDEX_RULES:
        if any(term in normalized for term in terms):
            return instrument_key, label
    return None


def _daily_atr(history: list[Candle], session_date: date) -> tuple[float | None, int]:
    grouped: dict[date, list[Candle]] = defaultdict(list)
    for candle in history:
        candle_date = candle.timestamp.astimezone(INDIA_TIMEZONE).date()
        if candle_date < session_date:
            grouped[candle_date].append(candle)
    daily = []
    for candle_date in sorted(grouped):
        candles = sorted(grouped[candle_date], key=lambda item: item.timestamp)
        daily.append((max(item.high for item in candles), min(item.low for item in candles), candles[-1].close))
    if not daily:
        return None, 0
    true_ranges = []
    previous_close = None
    for high, low, close in daily:
        true_range = high - low
        if previous_close is not None:
            true_range = max(true_range, abs(high - previous_close), abs(low - previous_close))
        true_ranges.append(true_range)
        previous_close = close
    sample = true_ranges[-14:]
    return (round(fmean(sample), 4), len(sample)) if sample else (None, 0)


def _vwap(session: list[Candle], close: float) -> VWAPFeatures:
    cumulative_value = 0.0
    cumulative_volume = 0
    series: list[float] = []
    for candle in session:
        if candle.volume > 0:
            typical_price = (candle.high + candle.low + candle.close) / 3
            cumulative_value += typical_price * candle.volume
            cumulative_volume += candle.volume
        if cumulative_volume > 0:
            series.append(cumulative_value / cumulative_volume)
    if not series:
        return VWAPFeatures()
    value = series[-1]
    position = _percent_change(close, value)
    slope = None
    if len(series) >= 6:
        total_change = _percent_change(value, series[-6])
        slope = round(total_change / 5, 4) if total_change is not None else None
    state = "above" if close > value else "below" if close < value else "at"
    return VWAPFeatures(
        value=round(value, 4),
        position_percent=position,
        slope_5m_percent_per_minute=slope,
        state=state,
    )


def _gap(
    session: list[Candle],
    close: float,
    previous_close: float | None,
    atr: float | None,
) -> GapFeatures:
    if not session or previous_close is None or previous_close == 0:
        return GapFeatures(previous_close=previous_close)
    opening_price = session[0].open
    gap_percent = _percent_change(opening_price, previous_close)
    gap_size = opening_price - previous_close
    retention = round((close - previous_close) / gap_size * 100, 2) if gap_size else None
    gap_atr = round(gap_size / atr, 4) if atr else None
    if gap_size == 0:
        state = "flat_open"
    elif retention is not None and retention >= 100:
        state = "extending"
    elif retention is not None and retention >= 50:
        state = "holding"
    elif retention is not None and retention > 0:
        state = "fading"
    else:
        state = "filled_or_reversed"
    return GapFeatures(
        previous_close=previous_close,
        opening_price=opening_price,
        gap_percent=gap_percent,
        gap_atr=gap_atr,
        retention_percent=retention,
        state=state,
    )


def _opening_range(
    session: list[Candle],
    current: Candle,
    as_of: datetime,
    minutes: int,
) -> OpeningRangeFeatures:
    session_date = current.timestamp.astimezone(INDIA_TIMEZONE).date()
    range_start = datetime.combine(session_date, time(9, 15), tzinfo=INDIA_TIMEZONE)
    range_end = range_start + timedelta(minutes=minutes)
    range_candles = [
        candle
        for candle in session
        if range_start <= candle.timestamp.astimezone(INDIA_TIMEZONE) < range_end
    ]
    ready = as_of.astimezone(INDIA_TIMEZONE) >= range_end
    if not ready or not range_candles:
        return OpeningRangeFeatures(minutes=minutes, ready=ready)
    high = max(candle.high for candle in range_candles)
    low = min(candle.low for candle in range_candles)
    midpoint = (high + low) / 2
    width = round((high - low) / midpoint * 100, 4) if midpoint else None
    if current.close > high:
        position = "above"
        breakout = _percent_change(current.close, high)
    elif current.close < low:
        position = "below"
        breakout = _percent_change(current.close, low)
    else:
        position = "inside"
        breakout = 0.0
    return OpeningRangeFeatures(
        minutes=minutes,
        ready=True,
        high=high,
        low=low,
        width_percent=width,
        breakout_percent=breakout,
        position=position,
    )


def _relative_strength(
    close: float,
    previous_close: float | None,
    sector: str | None,
    snapshots: dict[str, LiveSnapshot],
) -> RelativeStrengthFeatures:
    session_return = _percent_change(close, previous_close)
    nifty_return = _snapshot_change(snapshots.get(NIFTY_50_KEY))
    versus_nifty = (
        round(session_return - nifty_return, 4)
        if session_return is not None and nifty_return is not None
        else None
    )
    mapped_sector = sector_index_for(sector)
    sector_return = None
    sector_label = None
    if mapped_sector:
        sector_key, sector_label = mapped_sector
        sector_return = _snapshot_change(snapshots.get(sector_key))
    versus_sector = (
        round(session_return - sector_return, 4)
        if session_return is not None and sector_return is not None
        else None
    )
    return RelativeStrengthFeatures(
        session_return_percent=session_return,
        nifty_return_percent=nifty_return,
        versus_nifty_percent=versus_nifty,
        sector_index=sector_label,
        sector_return_percent=sector_return,
        versus_sector_percent=versus_sector,
    )


def _period_return(closes: list[float], periods: int) -> float | None:
    if len(closes) <= periods:
        return None
    return _percent_change(closes[-1], closes[-periods - 1])


def _momentum(session: list[Candle]) -> MomentumFeatures:
    closes = [candle.close for candle in session]
    returns = {period: _period_return(closes, period) for period in (1, 5, 15, 30)}
    efficiency = None
    if len(closes) >= 16:
        window = closes[-16:]
        path = sum(abs(current - previous) for previous, current in zip(window, window[1:]))
        efficiency = round(abs(window[-1] - window[0]) / path, 4) if path else 0.0
    recent = session[-10:]
    bullish_ratio = round(sum(candle.close > candle.open for candle in recent) / len(recent), 4) if recent else None
    return_5m = returns[5]
    return_15m = returns[15]
    if return_5m is None:
        state = "forming"
    elif return_5m > 0 and (return_15m is None or return_15m > 0):
        state = "strong_up" if efficiency is not None and efficiency >= 0.5 else "up"
    elif return_5m < 0 and (return_15m is None or return_15m < 0):
        state = "strong_down" if efficiency is not None and efficiency >= 0.5 else "down"
    else:
        state = "mixed"
    return MomentumFeatures(
        return_1m_percent=returns[1],
        return_5m_percent=return_5m,
        return_15m_percent=return_15m,
        return_30m_percent=returns[30],
        efficiency_ratio_15m=efficiency,
        bullish_candle_ratio_10m=bullish_ratio,
        state=state,
    )


def _volume(session: list[Candle], relative_volume: float | None) -> VolumeFeatures:
    acceleration = None
    if len(session) >= 8:
        recent = fmean(candle.volume for candle in session[-3:])
        prior = fmean(candle.volume for candle in session[-8:-3])
        acceleration = round(recent / prior, 4) if prior > 0 else None
    if relative_volume is not None and relative_volume >= 2:
        state = "high_relative"
    elif acceleration is not None and acceleration >= 1.5:
        state = "accelerating"
    elif relative_volume is not None and relative_volume >= 1:
        state = "active"
    elif relative_volume is not None or acceleration is not None:
        state = "quiet"
    else:
        state = "unavailable"
    return VolumeFeatures(
        completed_minute_volume=session[-1].volume if session else None,
        acceleration_ratio=acceleration,
        relative_volume=relative_volume,
        state=state,
    )


def _pullback(session: list[Candle], atr: float | None) -> PullbackFeatures:
    if not session:
        return PullbackFeatures()
    open_price = session[0].open
    close = session[-1].close
    session_high = max(candle.high for candle in session)
    session_low = min(candle.low for candle in session)
    session_range = session_high - session_low
    if close > open_price:
        direction = "up"
        distance = session_high - close
        recovery = (close - session_low) / session_range if session_range else 1.0
        countertrend = [candle.volume for candle in session[-10:] if candle.close < candle.open]
        directional = [candle.volume for candle in session[-10:] if candle.close > candle.open]
    elif close < open_price:
        direction = "down"
        distance = close - session_low
        recovery = (session_high - close) / session_range if session_range else 1.0
        countertrend = [candle.volume for candle in session[-10:] if candle.close > candle.open]
        directional = [candle.volume for candle in session[-10:] if candle.close < candle.open]
    else:
        return PullbackFeatures(direction="flat", quality="no_direction")
    distance_percent = round(distance / close * 100, 4) if close else None
    volume_ratio = None
    if countertrend and directional:
        directional_mean = fmean(directional)
        volume_ratio = round(fmean(countertrend) / directional_mean, 4) if directional_mean > 0 else None
    if atr and distance <= atr * 0.25:
        quality = "holding_extreme"
    elif recovery >= 0.65 and (volume_ratio is None or volume_ratio <= 1):
        quality = "orderly"
    else:
        quality = "deep_or_heavy"
    return PullbackFeatures(
        direction=direction,
        distance_from_extreme_percent=distance_percent,
        recovery_fraction=round(max(0.0, min(1.0, recovery)), 4),
        countertrend_volume_ratio=volume_ratio,
        quality=quality,
    )


def _volatility(session: list[Candle], close: float, atr: float | None, atr_sessions: int) -> VolatilityFeatures:
    session_high = max(candle.high for candle in session)
    session_low = min(candle.low for candle in session)
    session_range = session_high - session_low
    range_percent = round(session_range / close * 100, 4) if close else None
    atr_percent = round(atr / close * 100, 4) if atr and close else None
    range_atr = round(session_range / atr, 4) if atr else None
    if range_atr is None:
        state = "unavailable"
    elif range_atr >= 1:
        state = "expanded"
    elif range_atr >= 0.7:
        state = "elevated"
    else:
        state = "normal"
    return VolatilityFeatures(
        atr=atr,
        atr_percent=atr_percent,
        atr_sessions=atr_sessions,
        session_range_percent=range_percent,
        session_range_atr=range_atr,
        state=state,
    )


def _liquidity(
    snapshot: LiveSnapshot,
    max_spread_bps: float,
    min_traded_value_inr: float,
) -> LiquidityFeatures:
    spread = None
    if snapshot.best_bid_price and snapshot.best_ask_price and snapshot.best_ask_price >= snapshot.best_bid_price:
        midpoint = (snapshot.best_bid_price + snapshot.best_ask_price) / 2
        spread = round((snapshot.best_ask_price - snapshot.best_bid_price) / midpoint * 10_000, 4) if midpoint else None
    traded_value = (
        snapshot.ltp * snapshot.total_traded_volume
        if snapshot.ltp is not None and snapshot.total_traded_volume is not None
        else None
    )
    depth_imbalance = None
    if snapshot.total_buy_quantity is not None and snapshot.total_sell_quantity is not None:
        total_depth = snapshot.total_buy_quantity + snapshot.total_sell_quantity
        if total_depth > 0:
            depth_imbalance = round((snapshot.total_buy_quantity - snapshot.total_sell_quantity) / total_depth, 4)
    spread_pass = spread <= max_spread_bps if spread is not None else None
    turnover_pass = traded_value >= min_traded_value_inr if traded_value is not None else None
    if spread_pass is True and turnover_pass is True:
        state = "pass"
    elif spread_pass is False or turnover_pass is False:
        state = "reject"
    else:
        state = "partial"
    return LiquidityFeatures(
        spread_bps=spread,
        total_traded_value_inr=round(traded_value, 2) if traded_value is not None else None,
        depth_imbalance=depth_imbalance,
        passes_spread_filter=spread_pass,
        passes_traded_value_filter=turnover_pass,
        state=state,
    )


def build_stock_features(
    snapshot: LiveSnapshot,
    completed_candle: Candle,
    history: list[Candle],
    snapshots: dict[str, LiveSnapshot],
    sector: str | None,
    relative_volume_metric: RelativeVolumeMetric | None,
    *,
    as_of: datetime,
    max_spread_bps: float = 25.0,
    min_traded_value_inr: float = 10_000_000.0,
) -> StockFeatureSnapshot:
    """Calculate the approved feature groups without assigning trade weights."""
    session_date = completed_candle.timestamp.astimezone(INDIA_TIMEZONE).date()
    session = sorted(
        (
            candle
            for candle in history
            if candle.timestamp.astimezone(INDIA_TIMEZONE).date() == session_date
            and candle.timestamp <= completed_candle.timestamp
        ),
        key=lambda candle: candle.timestamp,
    )
    atr, atr_sessions = _daily_atr(history, session_date)
    vwap = _vwap(session, completed_candle.close)
    gap = _gap(session, completed_candle.close, snapshot.previous_close, atr)
    opening_ranges = [_opening_range(session, completed_candle, as_of, minutes) for minutes in (5, 15, 30)]
    relative_strength = _relative_strength(
        completed_candle.close,
        snapshot.previous_close,
        sector,
        snapshots,
    )
    relative_volume = None
    if relative_volume_metric:
        metric_date = relative_volume_metric.candle_timestamp.astimezone(INDIA_TIMEZONE).date()
        if metric_date == session_date:
            relative_volume = relative_volume_metric.relative_volume
    momentum = _momentum(session)
    volume = _volume(session, relative_volume)
    pullback = _pullback(session, atr)
    volatility = _volatility(session, completed_candle.close, atr, atr_sessions)
    liquidity = _liquidity(snapshot, max_spread_bps, min_traded_value_inr)

    unavailable = []
    if vwap.value is None:
        unavailable.append("vwap")
    if gap.gap_percent is None:
        unavailable.append("opening_gap")
    unavailable.extend(
        f"opening_range_{opening_range.minutes}m_pending"
        for opening_range in opening_ranges
        if not opening_range.ready
    )
    if relative_strength.versus_nifty_percent is None:
        unavailable.append("relative_strength_nifty")
    if relative_strength.sector_index is None or relative_strength.versus_sector_percent is None:
        unavailable.append("relative_strength_sector")
    if volume.relative_volume is None:
        unavailable.append("relative_volume")
    if volatility.atr is None:
        unavailable.append("atr")
    if liquidity.spread_bps is None or liquidity.total_traded_value_inr is None:
        unavailable.append("liquidity")
    data_quality = "complete" if not unavailable else "partial" if len(unavailable) <= 3 else "limited"

    return StockFeatureSnapshot(
        instrument_key=snapshot.instrument_key,
        symbol=snapshot.symbol,
        sector=sector,
        as_of=as_of,
        candle_timestamp=completed_candle.timestamp,
        data_quality=data_quality,
        unavailable=unavailable,
        vwap=vwap,
        gap=gap,
        opening_ranges=opening_ranges,
        relative_strength=relative_strength,
        momentum=momentum,
        volume=volume,
        pullback=pullback,
        volatility=volatility,
        liquidity=liquidity,
    )
