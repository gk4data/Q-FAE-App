"""Broader minute market-regime classification with persistence."""

from __future__ import annotations

from statistics import mean

from app.models.market import MarketContext, MarketRegimeSnapshot


def _breadth(context: MarketContext) -> float | None:
    directional = context.advancers + context.decliners
    return context.advancers / directional if directional else None


def build_market_regime(
    current: MarketContext,
    history: list[MarketContext],
) -> MarketRegimeSnapshot:
    """Combine direction, persistent breadth, VIX and sector participation."""
    window = [*history, current][-5:]
    breadth_values = [value for item in window if (value := _breadth(item)) is not None]
    breadth = _breadth(current)
    persistence = mean(breadth_values) if breadth_values else None
    sectors = [item for item in current.sector_indices if item.change_percent is not None and item.fresh]
    sector_participation = (
        sum(item.change_percent > 0 for item in sectors) / len(sectors) if sectors else None
    )
    vix_values = [
        item.india_vix.change_percent
        for item in window
        if item.india_vix.change_percent is not None and item.india_vix.fresh
    ]
    vix_acceleration = vix_values[-1] - vix_values[0] if len(vix_values) >= 2 else None
    nifty = current.nifty_50.change_percent if current.nifty_50.fresh else None
    vix = current.india_vix.change_percent if current.india_vix.fresh else None

    positive = sum(
        condition
        for condition in (
            nifty is not None and nifty > 0,
            breadth is not None and breadth >= 0.55,
            persistence is not None and persistence >= 0.55,
            sector_participation is not None and sector_participation >= 0.55,
            vix is not None and vix <= 0,
        )
    )
    negative = sum(
        condition
        for condition in (
            nifty is not None and nifty < 0,
            breadth is not None and breadth <= 0.45,
            persistence is not None and persistence <= 0.45,
            sector_participation is not None and sector_participation <= 0.45,
            vix is not None and vix > 0,
        )
    )
    available = sum(value is not None for value in (nifty, breadth, persistence, sector_participation, vix))
    state = "insufficient"
    if available >= 3:
        state = "risk_on" if positive >= 3 and negative < 3 else "risk_off" if negative >= 3 else "mixed"

    evidence: list[str] = []
    cautions: list[str] = []
    if nifty is not None:
        (evidence if nifty > 0 else cautions).append("nifty_positive" if nifty > 0 else "nifty_negative")
    if persistence is not None:
        (evidence if persistence >= 0.55 else cautions if persistence <= 0.45 else evidence).append(
            "breadth_persistently_positive" if persistence >= 0.55 else
            "breadth_persistently_negative" if persistence <= 0.45 else "breadth_balanced"
        )
    if sector_participation is not None:
        (evidence if sector_participation >= 0.55 else cautions).append(
            "broad_sector_participation" if sector_participation >= 0.55 else "narrow_sector_participation"
        )
    if vix is not None:
        (evidence if vix <= 0 else cautions).append("vix_not_rising" if vix <= 0 else "vix_rising")

    unavailable = []
    if nifty is None:
        unavailable.append("nifty")
    if vix is None:
        unavailable.append("india_vix")
    if not sectors:
        unavailable.append("sector_indices")
    unavailable.append("global_market_context")
    return MarketRegimeSnapshot(
        as_of=current.as_of,
        state=state,
        observations=len(window),
        nifty_change_percent=nifty,
        breadth_ratio=round(breadth, 4) if breadth is not None else None,
        breadth_persistence=round(persistence, 4) if persistence is not None else None,
        sector_participation=round(sector_participation, 4) if sector_participation is not None else None,
        vix_change_percent=vix,
        vix_acceleration_percent=round(vix_acceleration, 4) if vix_acceleration is not None else None,
        evidence=evidence,
        cautions=cautions,
        unavailable_inputs=unavailable,
    )
