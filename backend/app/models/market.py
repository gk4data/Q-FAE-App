"""Provider-neutral market-data models used throughout Q-FAE."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FrozenModel(BaseModel):
    """Immutable value object safe to share across worker threads."""

    model_config = ConfigDict(frozen=True)


class Candle(FrozenModel):
    """One normalized OHLCV candle."""

    instrument_key: str
    timestamp: datetime
    interval: str = "1minute"
    open: float
    high: float
    low: float
    close: float
    volume: int = Field(ge=0)
    open_interest: int = Field(default=0, ge=0)
    source: str = "upstox"

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("candle timestamps must include a timezone")
        return value


class MarketDepthLevel(FrozenModel):
    """One normalized bid/ask level from the provider's D5 order book."""

    bid_price: float | None = None
    bid_quantity: int | None = Field(default=None, ge=0)
    ask_price: float | None = None
    ask_quantity: int | None = Field(default=None, ge=0)


class LiveSnapshot(FrozenModel):
    """Latest normalized state for one equity or benchmark."""

    instrument_key: str
    symbol: str
    received_at: datetime
    last_trade_at: datetime | None = None
    ltp: float | None = None
    previous_close: float | None = None
    last_trade_quantity: int | None = Field(default=None, ge=0)
    total_traded_volume: int | None = Field(default=None, ge=0)
    average_traded_price: float | None = None
    best_bid_price: float | None = None
    best_bid_quantity: int | None = Field(default=None, ge=0)
    best_ask_price: float | None = None
    best_ask_quantity: int | None = Field(default=None, ge=0)
    total_buy_quantity: int | None = Field(default=None, ge=0)
    total_sell_quantity: int | None = Field(default=None, ge=0)
    lower_circuit: float | None = None
    upper_circuit: float | None = None
    market_depth: list[MarketDepthLevel] = Field(default_factory=list)
    current_candle: Candle | None = None
    completed_candle_relative_volume: float | None = Field(default=None, ge=0)
    completed_candle_timestamp: datetime | None = None


class RelativeVolumeMetric(FrozenModel):
    """RVOL for a specific completed one-minute candle."""

    instrument_key: str
    relative_volume: float = Field(ge=0)
    candle_timestamp: datetime
    calculated_at: datetime


class MinuteOfDayProfile(FrozenModel):
    """Rolling baseline for one instrument and regular-session minute."""

    instrument_key: str
    minute_of_session: int = Field(ge=0, le=374)
    sample_count: int = Field(ge=1)
    mean_volume: float = Field(ge=0)
    median_volume: float = Field(ge=0)
    volume_stddev: float = Field(ge=0)
    volume_p25: float = Field(ge=0)
    volume_p75: float = Field(ge=0)
    mean_range_bps: float | None = Field(default=None, ge=0)
    mean_abs_return_bps: float | None = Field(default=None, ge=0)
    mean_traded_value_inr: float | None = Field(default=None, ge=0)
    calculation_version: int = Field(default=1, ge=1)
    data_through: datetime
    updated_at: datetime


class WatchlistItem(FrozenModel):
    """Frontend-ready state for one stock in the active pilot universe."""

    instrument_key: str
    symbol: str
    company_name: str
    sector: str | None = None
    ltp: float | None = None
    previous_close: float | None = None
    change_percent: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: int | None = Field(default=None, ge=0)
    relative_volume: float | None = Field(default=None, ge=0)
    spread_bps: float | None = Field(default=None, ge=0)
    updated_at: datetime | None = None
    data_state: str = "waiting"


class VWAPFeatures(FrozenModel):
    value: float | None = None
    position_percent: float | None = None
    slope_5m_percent_per_minute: float | None = None
    state: str = "unavailable"


class GapFeatures(FrozenModel):
    previous_close: float | None = None
    opening_price: float | None = None
    gap_percent: float | None = None
    gap_atr: float | None = None
    retention_percent: float | None = None
    state: str = "unavailable"


class OpeningRangeFeatures(FrozenModel):
    minutes: int
    ready: bool = False
    high: float | None = None
    low: float | None = None
    width_percent: float | None = None
    breakout_percent: float | None = None
    position: str = "pending"


class RelativeStrengthFeatures(FrozenModel):
    session_return_percent: float | None = None
    nifty_return_percent: float | None = None
    versus_nifty_percent: float | None = None
    sector_index: str | None = None
    sector_return_percent: float | None = None
    versus_sector_percent: float | None = None
    universe_percentile: float | None = None


class MomentumFeatures(FrozenModel):
    return_1m_percent: float | None = None
    return_5m_percent: float | None = None
    return_15m_percent: float | None = None
    return_30m_percent: float | None = None
    efficiency_ratio_15m: float | None = None
    bullish_candle_ratio_10m: float | None = None
    state: str = "unavailable"


class VolumeFeatures(FrozenModel):
    completed_minute_volume: int | None = Field(default=None, ge=0)
    acceleration_ratio: float | None = Field(default=None, ge=0)
    relative_volume: float | None = Field(default=None, ge=0)
    state: str = "unavailable"


class PullbackFeatures(FrozenModel):
    direction: str = "unavailable"
    distance_from_extreme_percent: float | None = Field(default=None, ge=0)
    recovery_fraction: float | None = Field(default=None, ge=0, le=1)
    countertrend_volume_ratio: float | None = Field(default=None, ge=0)
    quality: str = "unavailable"


class VolatilityFeatures(FrozenModel):
    atr: float | None = Field(default=None, ge=0)
    atr_percent: float | None = Field(default=None, ge=0)
    atr_sessions: int = Field(default=0, ge=0)
    session_range_percent: float | None = Field(default=None, ge=0)
    session_range_atr: float | None = Field(default=None, ge=0)
    state: str = "unavailable"


class LiquidityFeatures(FrozenModel):
    spread_bps: float | None = Field(default=None, ge=0)
    total_traded_value_inr: float | None = Field(default=None, ge=0)
    depth_imbalance: float | None = Field(default=None, ge=-1, le=1)
    passes_spread_filter: bool | None = None
    passes_traded_value_filter: bool | None = None
    state: str = "unavailable"


class StockFeatureSnapshot(FrozenModel):
    """Explainable feature state calculated for one completed market minute."""

    instrument_key: str
    symbol: str
    sector: str | None = None
    as_of: datetime
    candle_timestamp: datetime
    data_quality: str
    unavailable: list[str] = Field(default_factory=list)
    vwap: VWAPFeatures
    gap: GapFeatures
    opening_ranges: list[OpeningRangeFeatures]
    relative_strength: RelativeStrengthFeatures
    momentum: MomentumFeatures
    volume: VolumeFeatures
    pullback: PullbackFeatures
    volatility: VolatilityFeatures
    liquidity: LiquidityFeatures


class HorizonPerformance(FrozenModel):
    sessions: int
    stock_return_percent: float | None = None
    nifty_return_percent: float | None = None
    versus_nifty_percent: float | None = None
    sector_return_percent: float | None = None
    versus_sector_percent: float | None = None


class DailyTrendFeatures(FrozenModel):
    sma_20: float | None = None
    sma_50: float | None = None
    sma_100: float | None = None
    sma_200: float | None = None
    above_sma_20_percent: float | None = None
    above_sma_50_percent: float | None = None
    sma_20_slope_5d_percent: float | None = None
    sma_50_slope_10d_percent: float | None = None
    alignment: str = "unavailable"
    regime: str = "unavailable"


class DailyStructureFeatures(FrozenModel):
    distance_to_20d_high_percent: float | None = None
    distance_to_60d_high_percent: float | None = None
    drawdown_from_252d_high_percent: float | None = None
    close_location_20d: float | None = Field(default=None, ge=0, le=1)
    range_20d_percent: float | None = Field(default=None, ge=0)
    positive_close_ratio_20d: float | None = Field(default=None, ge=0, le=1)
    trend_efficiency_20d: float | None = Field(default=None, ge=0, le=1)
    state: str = "unavailable"


class DailyParticipationFeatures(FrozenModel):
    latest_volume: int | None = Field(default=None, ge=0)
    relative_volume: float | None = Field(default=None, ge=0)
    relative_volume_basis: str = "unavailable"
    up_down_volume_ratio_20: float | None = Field(default=None, ge=0)
    high_volume_direction: str = "unavailable"


class DailyVolatilityFeatures(FrozenModel):
    atr_14: float | None = Field(default=None, ge=0)
    atr_14_percent: float | None = Field(default=None, ge=0)
    atr_14_vs_50: float | None = Field(default=None, ge=0)
    latest_range_atr: float | None = Field(default=None, ge=0)
    state: str = "unavailable"


class DailyRegimeSnapshot(FrozenModel):
    """Independent multi-horizon evidence; no horizon is a hard gate."""

    instrument_key: str
    symbol: str
    sector: str | None = None
    as_of: datetime
    data_through: datetime
    sessions_available: int = Field(ge=1)
    data_quality: str
    horizon_performance: list[HorizonPerformance]
    trend: DailyTrendFeatures
    structure: DailyStructureFeatures
    participation: DailyParticipationFeatures
    volatility: DailyVolatilityFeatures
    evidence: list[str] = Field(default_factory=list)
    cautions: list[str] = Field(default_factory=list)


class EvidencePillar(FrozenModel):
    """Validated, explainable evidence for one analysis family."""

    key: str
    label: str
    state: str
    available_checks: int = Field(ge=0)
    supportive_checks: int = Field(ge=0)
    caution_checks: int = Field(ge=0)
    evidence: list[str] = Field(default_factory=list)
    cautions: list[str] = Field(default_factory=list)


class FlowLiquidityConfirmation(FrozenModel):
    """Joint interpretation of participation and execution-quality evidence."""

    instrument_key: str
    symbol: str
    as_of: datetime
    data_quality: str
    relative_volume: float | None = Field(default=None, ge=0)
    volume_acceleration: float | None = Field(default=None, ge=0)
    spread_bps: float | None = Field(default=None, ge=0)
    traded_value_inr: float | None = Field(default=None, ge=0)
    depth_imbalance: float | None = Field(default=None, ge=-1, le=1)
    passes_spread_filter: bool | None = None
    passes_traded_value_filter: bool | None = None
    volume_state: str
    liquidity_state: str
    confirmation: str
    evidence: list[str] = Field(default_factory=list)
    cautions: list[str] = Field(default_factory=list)


class OpportunityEvidenceSnapshot(FrozenModel):
    """Unweighted confluence view combining validated technical and market evidence."""

    instrument_key: str
    symbol: str
    sector: str | None = None
    as_of: datetime
    data_quality: str
    confluence: str
    pillars: list[EvidencePillar]
    flow_liquidity: FlowLiquidityConfirmation
    signal_persistence: SignalPersistenceSnapshot | None = None
    risk_assessment: RiskAssessment | None = None
    derivatives_confirmation: DerivativesConfirmation = Field(
        default_factory=lambda: DerivativesConfirmation()
    )
    corporate_action_context: CorporateActionContext | None = None
    validation_notes: list[str] = Field(default_factory=list)


class SignalPersistenceSnapshot(FrozenModel):
    """Multi-minute confirmation state, deliberately separate from raw evidence."""

    instrument_key: str
    symbol: str
    as_of: datetime
    state: str
    supportive_minutes: int = Field(ge=0, le=3)
    caution_minutes: int = Field(ge=0, le=3)
    observed_minutes: int = Field(ge=1, le=3)
    transition: str | None = None
    reason: str


class RiskGateResult(FrozenModel):
    key: str
    status: str
    value: float | str | bool | None = None
    threshold: float | str | None = None
    reason: str


class RiskAssessment(FrozenModel):
    """Pre-trade tradability checks; unavailable inputs never silently pass."""

    instrument_key: str
    symbol: str
    as_of: datetime
    eligible: bool
    status: str
    reference_order_value_inr: float = Field(gt=0)
    estimated_buy_slippage_bps: float | None = Field(default=None, ge=0)
    estimated_sell_slippage_bps: float | None = Field(default=None, ge=0)
    spread_range_bps: float | None = Field(default=None, ge=0)
    depth_imbalance_range: float | None = Field(default=None, ge=0, le=2)
    distance_to_upper_circuit_percent: float | None = Field(default=None, ge=0)
    distance_to_lower_circuit_percent: float | None = Field(default=None, ge=0)
    gates: list[RiskGateResult] = Field(default_factory=list)


class DerivativesConfirmation(FrozenModel):
    """Provider-neutral F&O confirmation contract for mapped eligible instruments."""

    availability: str = "unavailable"
    futures_basis_percent: float | None = None
    open_interest_change_percent: float | None = None
    price_oi_state: str = "unavailable"
    put_call_ratio: float | None = Field(default=None, ge=0)
    reason: str = "cash_to_derivatives_mapping_not_configured"


class MarketRegimeSnapshot(FrozenModel):
    """Persistent broad-market participation and volatility regime."""

    as_of: datetime
    state: str
    observations: int = Field(ge=1, le=5)
    nifty_change_percent: float | None = None
    breadth_ratio: float | None = Field(default=None, ge=0, le=1)
    breadth_persistence: float | None = Field(default=None, ge=0, le=1)
    sector_participation: float | None = Field(default=None, ge=0, le=1)
    vix_change_percent: float | None = None
    vix_acceleration_percent: float | None = None
    evidence: list[str] = Field(default_factory=list)
    cautions: list[str] = Field(default_factory=list)
    unavailable_inputs: list[str] = Field(default_factory=list)


class EvidenceOutcomeObservation(FrozenModel):
    """Point-in-time evidence plus forward returns for honest evaluation."""

    instrument_key: str
    symbol: str
    sector: str | None = None
    candle_timestamp: datetime
    observed_at: datetime
    reference_price: float = Field(gt=0)
    confluence: str
    signal_state: str
    data_quality: str
    evidence_payload: dict[str, object]
    risk_payload: dict[str, object] | None = None
    market_regime_payload: dict[str, object] | None = None
    forward_return_5m_percent: float | None = None
    forward_return_15m_percent: float | None = None
    forward_return_30m_percent: float | None = None
    forward_return_60m_percent: float | None = None
    forward_return_eod_percent: float | None = None
    mfe_60m_percent: float | None = None
    mae_60m_percent: float | None = None
    outcome_status: str = "pending"
    evaluated_through: datetime | None = None


class CorporateAction(FrozenModel):
    """Provider-normalized corporate action stored without an AI interpretation."""

    event_id: str
    isin: str
    instrument_key: str
    symbol: str
    action_type: str
    announcement_date: date | None = None
    ex_date: date | None = None
    record_date: date | None = None
    amount: float | None = None
    ratio: str | None = None
    details: dict[str, str] = Field(default_factory=dict)
    raw_payload: dict[str, object]
    source: str = "upstox"
    ingested_at: datetime


class CorporateActionAssessment(FrozenModel):
    """Versioned deterministic interpretation; never overwrites provider facts."""

    event_id: str
    assessment_version: int = Field(default=1, ge=1)
    isin: str
    instrument_key: str
    symbol: str
    category: str
    direction: str
    materiality_score: float = Field(ge=0, le=100)
    sentiment_score: float = Field(ge=-100, le=100)
    confidence: float = Field(ge=0, le=1)
    impact_horizon: str
    reference_price: float | None = Field(default=None, gt=0)
    reference_price_date: date | None = None
    derived_metrics: dict[str, float | str | None] = Field(default_factory=dict)
    evidence: list[str] = Field(default_factory=list)
    cautions: list[str] = Field(default_factory=list)
    requires_ai_review: bool = True
    assessed_at: datetime


class CorporateActionAdjustment(FrozenModel):
    """Versioned backward-adjustment factor; raw candles remain untouched."""

    event_id: str
    calculation_version: int = Field(default=1, ge=1)
    instrument_key: str
    category: str
    effective_date: date | None = None
    price_factor: float | None = Field(default=None, gt=0)
    volume_factor: float | None = Field(default=None, gt=0)
    status: str
    reason: str
    reference_close: float | None = Field(default=None, gt=0)
    calculated_at: datetime


class AdjustedCandle(FrozenModel):
    instrument_key: str
    timestamp: datetime
    interval: str
    raw_open: float
    raw_high: float
    raw_low: float
    raw_close: float
    raw_volume: int = Field(ge=0)
    adjusted_open: float
    adjusted_high: float
    adjusted_low: float
    adjusted_close: float
    adjusted_volume: int = Field(ge=0)
    cumulative_price_factor: float = Field(gt=0)
    cumulative_volume_factor: float = Field(gt=0)
    adjustment_status: str


class CorporateActionDocument(FrozenModel):
    document_id: str
    instrument_key: str
    symbol: str
    source: str
    published_at: datetime
    title: str
    summary: str | None = None
    source_url: str
    document_text: str | None = None
    matched_event_ids: list[str] = Field(default_factory=list)
    raw_payload: dict[str, object] = Field(default_factory=dict)
    ingested_at: datetime


class CorporateFinancialContext(FrozenModel):
    isin: str
    instrument_key: str
    symbol: str
    statement_type: str = "consolidated"
    latest_revenue_crore: float | None = None
    latest_operating_profit_crore: float | None = None
    latest_net_profit_crore: float | None = None
    latest_operating_cash_flow_crore: float | None = None
    revenue_period: str | None = None
    cash_flow_period: str | None = None
    raw_payload: dict[str, object]
    data_quality: str
    fetched_at: datetime


class CorporateActionAIAnalysis(FrozenModel):
    event_id: str
    analysis_version: int = Field(default=1, ge=1)
    provider: str
    model: str | None = None
    status: str
    impact_score: float | None = Field(default=None, ge=-100, le=100)
    impact_probability: float | None = Field(default=None, ge=0, le=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    impact_horizon: str | None = None
    rationale: str | None = None
    positive_factors: list[str] = Field(default_factory=list)
    negative_factors: list[str] = Field(default_factory=list)
    citation_document_ids: list[str] = Field(default_factory=list)
    grounded: bool = False
    error: str | None = None
    analyzed_at: datetime


class CorporateActionOutcome(FrozenModel):
    event_id: str
    instrument_key: str
    event_date: date
    reference_price: float | None = Field(default=None, gt=0)
    return_1d_percent: float | None = None
    abnormal_return_1d_percent: float | None = None
    return_5d_percent: float | None = None
    abnormal_return_5d_percent: float | None = None
    return_20d_percent: float | None = None
    abnormal_return_20d_percent: float | None = None
    outcome_status: str
    evaluated_at: datetime


class CorporateActionContext(FrozenModel):
    instrument_key: str
    as_of: datetime
    state: str
    active_events: int = Field(ge=0)
    maximum_materiality: float | None = Field(default=None, ge=0, le=100)
    deterministic_sentiment: float | None = Field(default=None, ge=-100, le=100)
    ai_impact_score: float | None = Field(default=None, ge=-100, le=100)
    effective_score: float | None = Field(default=None, ge=-100, le=100)
    evidence: list[str] = Field(default_factory=list)
    cautions: list[str] = Field(default_factory=list)


class CorporateActionCalibrationBucket(FrozenModel):
    category: str
    direction: str
    horizon_sessions: int = Field(ge=1)
    observations: int = Field(ge=0)
    mean_abnormal_return_percent: float | None = None
    positive_rate: float | None = Field(default=None, ge=0, le=1)
    readiness: str


class CorporateActionCalibrationReport(FrozenModel):
    generated_at: datetime
    minimum_observations: int = Field(ge=1)
    buckets: list[CorporateActionCalibrationBucket] = Field(default_factory=list)


class DailyReconciliationRecord(FrozenModel):
    """Comparison of an official daily candle with captured intraday evidence."""

    session_date: date
    instrument_key: str
    symbol: str
    status: str
    minute_count: int = Field(ge=0)
    expected_minutes: int = Field(default=375, ge=1)
    official_close: float
    official_volume: int = Field(ge=0)
    aggregated_close: float | None = None
    aggregated_volume: int | None = Field(default=None, ge=0)
    volume_difference_percent: float | None = None
    ohlc_matches: bool | None = None
    notes: list[str] = Field(default_factory=list)
    reconciled_at: datetime


class BenchmarkState(FrozenModel):
    instrument_key: str
    ltp: float | None = None
    previous_close: float | None = None
    change_percent: float | None = None
    direction: str = "unavailable"
    updated_at: datetime | None = None
    fresh: bool = False


class SectorIndexState(BenchmarkState):
    sector: str


class SectorState(FrozenModel):
    sector: str
    instruments: int
    advancers: int
    decliners: int
    unchanged: int
    average_change_percent: float | None = None


class RelativeVolumeLeader(FrozenModel):
    instrument_key: str
    symbol: str
    relative_volume: float
    candle_timestamp: datetime


class MarketContext(FrozenModel):
    """Minute-level market context derived from the latest complete state."""

    as_of: datetime
    cadence_seconds: int = 60
    nifty_50: BenchmarkState
    nifty_bank: BenchmarkState
    india_vix: BenchmarkState
    sector_indices: list[SectorIndexState] = Field(default_factory=list)
    universe_size: int
    fresh_instruments: int
    stale_instruments: int
    advancers: int
    decliners: int
    unchanged: int
    advance_decline_ratio: float | None = None
    median_spread_bps: float | None = None
    liquid_instruments: int
    sectors: list[SectorState] = Field(default_factory=list)
    relative_volume_leaders: list[RelativeVolumeLeader] = Field(default_factory=list)
