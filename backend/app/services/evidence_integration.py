"""Validate and combine existing feature families without arbitrary weights."""

from __future__ import annotations

from datetime import datetime

from app.models.market import (
    DailyRegimeSnapshot,
    EvidencePillar,
    FlowLiquidityConfirmation,
    MarketContext,
    OpportunityEvidenceSnapshot,
    StockFeatureSnapshot,
)
from app.services.market_context import INDIA_TIMEZONE
from app.services.flow_confirmation import build_flow_liquidity_confirmation


class _PillarBuilder:
    def __init__(self, key: str, label: str) -> None:
        self.key = key
        self.label = label
        self.available = 0
        self.supportive = 0
        self.caution = 0
        self.evidence: list[str] = []
        self.cautions: list[str] = []

    def check(self, value: object | None, supportive: bool, positive: str, negative: str) -> None:
        if value is None:
            return
        self.available += 1
        if supportive:
            self.supportive += 1
            self.evidence.append(positive)
        else:
            self.caution += 1
            self.cautions.append(negative)

    def build(self) -> EvidencePillar:
        if self.available == 0:
            state = "unavailable"
        elif self.supportive >= 2 and self.supportive > self.caution:
            state = "supportive"
        elif self.caution >= 2 and self.caution > self.supportive:
            state = "caution"
        else:
            state = "mixed"
        return EvidencePillar(
            key=self.key,
            label=self.label,
            state=state,
            available_checks=self.available,
            supportive_checks=self.supportive,
            caution_checks=self.caution,
            evidence=self.evidence,
            cautions=self.cautions,
        )


def build_opportunity_evidence(
    feature: StockFeatureSnapshot,
    regime: DailyRegimeSnapshot | None,
    context: MarketContext | None,
    *,
    as_of: datetime,
    freshness_seconds: int = 120,
    flow_liquidity: FlowLiquidityConfirmation | None = None,
) -> OpportunityEvidenceSnapshot:
    """Create unweighted confluence while making stale or missing inputs explicit."""
    if regime is not None and regime.instrument_key != feature.instrument_key:
        raise ValueError("feature and regime instruments must match")

    notes: list[str] = []
    feature_age = (as_of - feature.as_of).total_seconds()
    feature_current = (
        feature.candle_timestamp.astimezone(INDIA_TIMEZONE).date()
        == as_of.astimezone(INDIA_TIMEZONE).date()
        and -5 <= feature_age <= freshness_seconds
    )
    if not feature_current:
        notes.append("intraday_evidence_stale")
    regime_valid = regime is not None and regime.data_through <= as_of
    if regime is None:
        notes.append("daily_regime_unavailable")
    elif not regime_valid:
        notes.append("daily_regime_contains_future_data")
    elif regime.data_quality == "limited":
        notes.append("daily_regime_limited_history")
    context_current = bool(
        context is not None
        and context.nifty_50.fresh
        and -5 <= (as_of - context.as_of).total_seconds() <= freshness_seconds
    )
    if context is None:
        notes.append("market_context_unavailable")
    elif not context_current:
        notes.append("market_context_stale")
    if feature.sector is None or feature.relative_strength.sector_index is None:
        notes.append("sector_benchmark_unavailable")

    intraday = _intraday_pillar(feature) if feature_current else _PillarBuilder(
        "intraday", "Intraday technical"
    ).build()
    validated_regime = regime if regime_valid else None
    daily = _daily_pillar(validated_regime)
    relative_strength = _relative_strength_pillar(
        feature if feature_current else None,
        validated_regime,
        context if context_current else None,
    )
    flow_liquidity = flow_liquidity or build_flow_liquidity_confirmation(feature)
    if not feature_current:
        flow_liquidity = flow_liquidity.model_copy(
            update={
                "data_quality": "stale",
                "confirmation": "insufficient",
                "evidence": [],
                "cautions": ["intraday_evidence_stale"],
            }
        )
    confirmation = _confirmation_pillar(flow_liquidity) if feature_current else _PillarBuilder(
        "confirmation", "Volume and liquidity"
    ).build()
    pillars = [intraday, daily, relative_strength, confirmation]
    available_pillars = [pillar for pillar in pillars if pillar.state != "unavailable"]
    supportive = sum(pillar.state == "supportive" for pillar in available_pillars)
    cautions = sum(pillar.state == "caution" for pillar in available_pillars)
    if len(available_pillars) < 3:
        confluence = "insufficient"
    elif supportive >= 3 and cautions == 0:
        confluence = "strong_support"
    elif supportive >= 2 and supportive > cautions:
        confluence = "supportive"
    elif cautions >= 2 and cautions > supportive:
        confluence = "caution"
    else:
        confluence = "mixed"
    if len(available_pillars) == 4 and not notes:
        data_quality = "complete"
    elif len(available_pillars) >= 3:
        data_quality = "partial"
    else:
        data_quality = "limited"
    return OpportunityEvidenceSnapshot(
        instrument_key=feature.instrument_key,
        symbol=feature.symbol,
        sector=feature.sector,
        as_of=as_of,
        data_quality=data_quality,
        confluence=confluence,
        pillars=pillars,
        flow_liquidity=flow_liquidity,
        validation_notes=notes,
    )


def _intraday_pillar(feature: StockFeatureSnapshot) -> EvidencePillar:
    pillar = _PillarBuilder("intraday", "Intraday technical")
    value = feature.vwap.position_percent
    pillar.check(value, bool(value is not None and value > 0), "price_above_vwap", "price_below_vwap")
    slope = feature.vwap.slope_5m_percent_per_minute
    pillar.check(slope, bool(slope is not None and slope > 0), "vwap_slope_rising", "vwap_slope_falling")
    ready_ranges = [item for item in feature.opening_ranges if item.ready]
    if ready_ranges:
        position = max(ready_ranges, key=lambda item: item.minutes).position
        if position in {"above", "below"}:
            pillar.check(position, position == "above", "above_opening_range", "below_opening_range")
    momentum = feature.momentum.return_5m_percent
    pillar.check(momentum, bool(momentum is not None and momentum > 0), "positive_5m_momentum", "negative_5m_momentum")
    efficiency = feature.momentum.efficiency_ratio_15m
    if momentum is not None and efficiency is not None and efficiency >= 0.35:
        pillar.check(
            efficiency,
            momentum > 0,
            "efficient_upward_path",
            "efficient_downward_path",
        )
    gap = feature.gap
    if gap.gap_percent is not None and gap.gap_percent > 0 and gap.state != "flat_open":
        pillar.check(
            gap.retention_percent,
            gap.state in {"holding", "extending"},
            "positive_gap_retained",
            "positive_gap_fading_or_filled",
        )
    elif gap.gap_percent is not None and gap.gap_percent < 0 and gap.state != "flat_open":
        pillar.check(
            gap.retention_percent,
            gap.state == "filled_or_reversed",
            "negative_gap_recovered",
            "negative_gap_retained",
        )
    pullback = feature.pullback
    if pullback.direction in {"up", "down"} and pullback.quality != "unavailable":
        pillar.check(
            pullback.quality,
            pullback.direction == "up" and pullback.quality in {"holding_extreme", "orderly"},
            "constructive_uptrend_pullback",
            "pullback_or_direction_unsupportive",
        )
    range_atr = feature.volatility.session_range_atr
    if range_atr is not None and momentum is not None and range_atr >= 0.7:
        pillar.check(
            range_atr,
            momentum > 0,
            "positive_volatility_expansion",
            "negative_volatility_expansion",
        )
    return pillar.build()


def _daily_pillar(regime: DailyRegimeSnapshot | None) -> EvidencePillar:
    pillar = _PillarBuilder("daily", "Daily trend and regime")
    if regime is None:
        return pillar.build()
    trend = regime.trend.regime
    if trend not in {"forming", "mixed"}:
        pillar.check(
            trend,
            trend in {"emerging_uptrend", "established_uptrend", "pullback_in_uptrend"},
            trend,
            trend,
        )
    alignment = regime.trend.alignment
    if alignment in {"bullish", "bearish"}:
        pillar.check(alignment, alignment == "bullish", "bullish_sma_alignment", "bearish_sma_alignment")
    structure = regime.structure.state
    if structure != "unavailable":
        pillar.check(
            structure,
            structure in {"breakout_20d", "near_20d_high", "tight_base"},
            structure,
            structure,
        )
    slope = regime.trend.sma_20_slope_5d_percent
    pillar.check(slope, bool(slope is not None and slope > 0), "sma20_rising", "sma20_falling")
    return pillar.build()


def _relative_strength_pillar(
    feature: StockFeatureSnapshot | None,
    regime: DailyRegimeSnapshot | None,
    context: MarketContext | None,
) -> EvidencePillar:
    pillar = _PillarBuilder("relative_strength", "NIFTY and sector strength")
    if feature is not None:
        versus_nifty = feature.relative_strength.versus_nifty_percent
        pillar.check(
            versus_nifty,
            bool(versus_nifty is not None and versus_nifty > 0),
            "intraday_outperforming_nifty",
            "intraday_lagging_nifty",
        )
        versus_sector = feature.relative_strength.versus_sector_percent
        pillar.check(
            versus_sector,
            bool(versus_sector is not None and versus_sector > 0),
            "intraday_outperforming_sector",
            "intraday_lagging_sector",
        )
        if context is not None and context.nifty_50.change_percent is not None:
            stock_return = feature.relative_strength.session_return_percent
            if stock_return is not None:
                pillar.check(
                    stock_return,
                    stock_return > context.nifty_50.change_percent,
                    "strength_confirmed_against_market_tape",
                    "weakness_confirmed_against_market_tape",
                )
    if regime is not None:
        by_horizon = {row.sessions: row for row in regime.horizon_performance}
        for sessions in (20, 60):
            horizon = by_horizon.get(sessions)
            if horizon is None:
                continue
            value = horizon.versus_nifty_percent
            pillar.check(
                value,
                bool(value is not None and value > 0),
                f"outperforming_nifty_{sessions}d",
                f"lagging_nifty_{sessions}d",
            )
            sector_value = horizon.versus_sector_percent
            pillar.check(
                sector_value,
                bool(sector_value is not None and sector_value > 0),
                f"outperforming_sector_{sessions}d",
                f"lagging_sector_{sessions}d",
            )
    return pillar.build()


def _confirmation_pillar(result: FlowLiquidityConfirmation) -> EvidencePillar:
    available = sum(
        value is not None
        for value in (
            result.relative_volume,
            result.volume_acceleration,
            result.passes_spread_filter,
            result.passes_traded_value_filter,
            result.depth_imbalance,
        )
    )
    supportive = len(result.evidence)
    cautions = len(result.cautions)
    if result.confirmation in {"strong_confirmation", "confirmed"}:
        state = "supportive"
    elif result.confirmation in {"rejected", "liquid_but_unconfirmed"}:
        state = "caution"
    elif result.confirmation == "insufficient":
        state = "unavailable" if available == 0 else "mixed"
    else:
        state = "mixed"
    return EvidencePillar(
        key="confirmation",
        label="Volume and liquidity",
        state=state,
        available_checks=available,
        supportive_checks=supportive,
        caution_checks=cautions,
        evidence=result.evidence,
        cautions=result.cautions,
    )
