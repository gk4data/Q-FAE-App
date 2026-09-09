"""Minute-cadence market-context and relative-volume calculations."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta, timezone
from statistics import median

from app.models.market import (
    BenchmarkState,
    Candle,
    LiveSnapshot,
    MarketContext,
    RelativeVolumeLeader,
    SectorIndexState,
    SectorState,
)
from app.services.upstox_market import (
    INDIA_VIX_KEY,
    NIFTY_50_KEY,
    NIFTY_BANK_KEY,
    SECTOR_INDEX_SYMBOLS,
)

INDIA_TIMEZONE = timezone(timedelta(hours=5, minutes=30))


def calculate_relative_volume(candle: Candle, history: list[Candle]) -> float | None:
    """Compare a completed candle with the same minute-of-session in prior sessions."""
    local_time = candle.timestamp.astimezone(INDIA_TIMEZONE)
    baseline = [
        item.volume
        for item in history
        if item.timestamp.astimezone(INDIA_TIMEZONE).date() != local_time.date()
        and item.timestamp.astimezone(INDIA_TIMEZONE).hour == local_time.hour
        and item.timestamp.astimezone(INDIA_TIMEZONE).minute == local_time.minute
        and item.volume > 0
    ]
    if not baseline:
        return None
    typical = median(baseline)
    return round(candle.volume / typical, 4) if typical > 0 else None


def _change_percent(snapshot: LiveSnapshot | None) -> float | None:
    if not snapshot or snapshot.ltp is None or not snapshot.previous_close:
        return None
    return (snapshot.ltp / snapshot.previous_close - 1) * 100


def _benchmark(
    instrument_key: str,
    snapshots: dict[str, LiveSnapshot],
    fresh_cutoff: datetime,
) -> BenchmarkState:
    snapshot = snapshots.get(instrument_key)
    change = _change_percent(snapshot)
    direction = "unavailable" if change is None else "up" if change > 0 else "down" if change < 0 else "flat"
    return BenchmarkState(
        instrument_key=instrument_key,
        ltp=snapshot.ltp if snapshot else None,
        previous_close=snapshot.previous_close if snapshot else None,
        change_percent=round(change, 4) if change is not None else None,
        direction=direction,
        updated_at=snapshot.received_at if snapshot else None,
        fresh=bool(snapshot and snapshot.received_at >= fresh_cutoff),
    )


def _sector_indices(
    snapshots: dict[str, LiveSnapshot],
    fresh_cutoff: datetime,
) -> list[SectorIndexState]:
    states = []
    for instrument_key, sector in SECTOR_INDEX_SYMBOLS.items():
        benchmark = _benchmark(instrument_key, snapshots, fresh_cutoff)
        states.append(SectorIndexState(sector=sector, **benchmark.model_dump()))
    states.sort(
        key=lambda item: item.change_percent if item.change_percent is not None else float("-inf"),
        reverse=True,
    )
    return states


def build_market_context(
    snapshots: list[LiveSnapshot],
    sectors: dict[str, str],
    *,
    as_of: datetime | None = None,
    cadence_seconds: int = 60,
) -> MarketContext:
    """Build an explainable market snapshot once per configured minute bucket."""
    as_of = as_of or datetime.now(UTC)
    by_key = {snapshot.instrument_key: snapshot for snapshot in snapshots}
    equities = [snapshot for snapshot in snapshots if snapshot.instrument_key.startswith("NSE_EQ|")]
    fresh_cutoff = as_of - timedelta(seconds=cadence_seconds * 2)
    fresh = [snapshot for snapshot in equities if snapshot.received_at >= fresh_cutoff]

    changes = {snapshot.instrument_key: _change_percent(snapshot) for snapshot in fresh}
    advancers = sum(value is not None and value > 0 for value in changes.values())
    decliners = sum(value is not None and value < 0 for value in changes.values())
    unchanged = sum(value == 0 for value in changes.values())
    spreads = []
    for snapshot in fresh:
        if snapshot.best_bid_price and snapshot.best_ask_price and snapshot.best_ask_price >= snapshot.best_bid_price:
            midpoint = (snapshot.best_bid_price + snapshot.best_ask_price) / 2
            if midpoint > 0:
                spreads.append((snapshot.best_ask_price - snapshot.best_bid_price) / midpoint * 10_000)

    sector_members: dict[str, list[float | None]] = defaultdict(list)
    for snapshot in fresh:
        sector = sectors.get(snapshot.instrument_key)
        if sector:
            sector_members[sector].append(changes[snapshot.instrument_key])
    sector_states = []
    for sector, values in sector_members.items():
        available = [value for value in values if value is not None]
        sector_states.append(
            SectorState(
                sector=sector,
                instruments=len(values),
                advancers=sum(value > 0 for value in available),
                decliners=sum(value < 0 for value in available),
                unchanged=sum(value == 0 for value in available),
                average_change_percent=round(sum(available) / len(available), 4) if available else None,
            )
        )
    sector_states.sort(
        key=lambda item: item.average_change_percent
        if item.average_change_percent is not None
        else float("-inf"),
        reverse=True,
    )

    leaders = [
        RelativeVolumeLeader(
            instrument_key=snapshot.instrument_key,
            symbol=snapshot.symbol,
            relative_volume=snapshot.completed_candle_relative_volume,
            candle_timestamp=snapshot.completed_candle_timestamp,
        )
        for snapshot in fresh
        if snapshot.completed_candle_relative_volume is not None and snapshot.completed_candle_timestamp is not None
    ]
    leaders.sort(key=lambda item: item.relative_volume, reverse=True)

    return MarketContext(
        as_of=as_of,
        cadence_seconds=cadence_seconds,
        nifty_50=_benchmark(NIFTY_50_KEY, by_key, fresh_cutoff),
        nifty_bank=_benchmark(NIFTY_BANK_KEY, by_key, fresh_cutoff),
        india_vix=_benchmark(INDIA_VIX_KEY, by_key, fresh_cutoff),
        sector_indices=_sector_indices(by_key, fresh_cutoff),
        universe_size=len(equities),
        fresh_instruments=len(fresh),
        stale_instruments=len(equities) - len(fresh),
        advancers=advancers,
        decliners=decliners,
        unchanged=unchanged,
        advance_decline_ratio=round(advancers / decliners, 4) if decliners else None,
        median_spread_bps=round(median(spreads), 4) if spreads else None,
        liquid_instruments=len(spreads),
        sectors=sector_states,
        relative_volume_leaders=leaders[:20],
    )
