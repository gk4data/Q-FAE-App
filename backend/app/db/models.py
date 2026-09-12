"""SQLAlchemy models for durable historical market data."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Date, DateTime, Index, Integer, JSON, Numeric, SmallInteger, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class MarketCandleRecord(Base):
    """Provider-normalized candle; interval and timestamp make writes idempotent."""

    __tablename__ = "market_candles"

    instrument_key: Mapped[str] = mapped_column(String(160), primary_key=True)
    interval: Mapped[str] = mapped_column(String(20), primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    open: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    open_interest: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="upstox")
    adjustment_status: Mapped[str] = mapped_column(String(24), nullable=False, default="raw")
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_market_candles_interval_timestamp", "interval", "timestamp"),
    )


class DataSyncStateRecord(Base):
    """Watermark and outcome for each provider dataset and instrument."""

    __tablename__ = "data_sync_state"

    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    dataset: Mapped[str] = mapped_column(String(64), primary_key=True)
    instrument_key: Mapped[str] = mapped_column(String(160), primary_key=True)
    data_through: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    rows_written: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class MinuteOfDayProfileRecord(Base):
    """Compact rolling statistics for a normal NSE minute-of-session bucket."""

    __tablename__ = "minute_of_day_profiles"

    instrument_key: Mapped[str] = mapped_column(String(160), primary_key=True)
    minute_of_session: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    mean_volume: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    median_volume: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    volume_stddev: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    volume_p25: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    volume_p75: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    mean_range_bps: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    mean_abs_return_bps: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    mean_traded_value_inr: Mapped[Decimal | None] = mapped_column(Numeric(24, 2))
    calculation_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    data_through: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_minute_profiles_minute_of_session", "minute_of_session"),
    )


class SessionReconciliationRecord(Base):
    """Auditable official-versus-captured result for one market session."""

    __tablename__ = "session_reconciliations"

    session_date: Mapped[date] = mapped_column(Date, primary_key=True)
    instrument_key: Mapped[str] = mapped_column(String(160), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    minute_count: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=375)
    official_close: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    official_volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    aggregated_close: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    aggregated_volume: Mapped[int | None] = mapped_column(BigInteger)
    volume_difference_percent: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    ohlc_matches: Mapped[bool | None]
    notes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    reconciled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (Index("ix_session_reconciliations_status", "session_date", "status"),)


class EvidenceObservationRecord(Base):
    """Immutable minute evidence inputs with progressively filled forward outcomes."""

    __tablename__ = "evidence_observations"

    instrument_key: Mapped[str] = mapped_column(String(160), primary_key=True)
    candle_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(80), nullable=False)
    sector: Mapped[str | None] = mapped_column(String(120))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reference_price: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    confluence: Mapped[str] = mapped_column(String(40), nullable=False)
    signal_state: Mapped[str] = mapped_column(String(40), nullable=False)
    data_quality: Mapped[str] = mapped_column(String(40), nullable=False)
    evidence_payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    risk_payload: Mapped[dict[str, object] | None] = mapped_column(JSON)
    market_regime_payload: Mapped[dict[str, object] | None] = mapped_column(JSON)
    forward_return_5m_percent: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    forward_return_15m_percent: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    forward_return_30m_percent: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    forward_return_60m_percent: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    forward_return_eod_percent: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    mfe_60m_percent: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    mae_60m_percent: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    outcome_status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    evaluated_through: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_evidence_observations_time", "candle_timestamp"),
        Index("ix_evidence_observations_signal", "signal_state", "outcome_status"),
    )


class CorporateActionRecord(Base):
    """Raw, provider-normalized corporate action keyed by stable content hash."""

    __tablename__ = "corporate_actions"

    event_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    isin: Mapped[str] = mapped_column(String(20), nullable=False)
    instrument_key: Mapped[str] = mapped_column(String(160), nullable=False)
    symbol: Mapped[str] = mapped_column(String(80), nullable=False)
    action_type: Mapped[str] = mapped_column(String(80), nullable=False)
    announcement_date: Mapped[date | None] = mapped_column(Date)
    ex_date: Mapped[date | None] = mapped_column(Date)
    record_date: Mapped[date | None] = mapped_column(Date)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    ratio: Mapped[str | None] = mapped_column(String(80))
    details: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    raw_payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="upstox")
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_corporate_actions_isin_ex_date", "isin", "ex_date"),
        Index("ix_corporate_actions_instrument", "instrument_key", "ex_date"),
    )


class CorporateActionAssessmentRecord(Base):
    """Versioned deterministic assessment kept separate from immutable source facts."""

    __tablename__ = "corporate_action_assessments"

    event_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    assessment_version: Mapped[int] = mapped_column(Integer, primary_key=True)
    isin: Mapped[str] = mapped_column(String(20), nullable=False)
    instrument_key: Mapped[str] = mapped_column(String(160), nullable=False)
    symbol: Mapped[str] = mapped_column(String(80), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    direction: Mapped[str] = mapped_column(String(24), nullable=False)
    materiality_score: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    sentiment_score: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    impact_horizon: Mapped[str] = mapped_column(String(80), nullable=False)
    reference_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    reference_price_date: Mapped[date | None] = mapped_column(Date)
    derived_metrics: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    evidence: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    cautions: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    requires_ai_review: Mapped[bool] = mapped_column(nullable=False)
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_corporate_action_assessments_instrument", "instrument_key", "category"),
        Index("ix_corporate_action_assessments_direction", "direction", "materiality_score"),
    )


class CorporateActionAdjustmentRecord(Base):
    __tablename__ = "corporate_action_adjustments"
    event_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    calculation_version: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_key: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    effective_date: Mapped[date | None] = mapped_column(Date)
    price_factor: Mapped[Decimal | None] = mapped_column(Numeric(20, 12))
    volume_factor: Mapped[Decimal | None] = mapped_column(Numeric(20, 12))
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    reason: Mapped[str] = mapped_column(String(160), nullable=False)
    reference_close: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class CorporateActionDocumentRecord(Base):
    __tablename__ = "corporate_action_documents"
    document_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    instrument_key: Mapped[str] = mapped_column(String(160), nullable=False)
    symbol: Mapped[str] = mapped_column(String(80), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    document_text: Mapped[str | None] = mapped_column(Text)
    matched_event_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    raw_payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    __table_args__ = (Index("ix_corporate_action_documents_instrument", "instrument_key", "published_at"),)


class CorporateFinancialContextRecord(Base):
    __tablename__ = "corporate_financial_contexts"
    isin: Mapped[str] = mapped_column(String(20), primary_key=True)
    instrument_key: Mapped[str] = mapped_column(String(160), nullable=False)
    symbol: Mapped[str] = mapped_column(String(80), nullable=False)
    statement_type: Mapped[str] = mapped_column(String(24), nullable=False)
    latest_revenue_crore: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    latest_operating_profit_crore: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    latest_net_profit_crore: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    latest_operating_cash_flow_crore: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    revenue_period: Mapped[str | None] = mapped_column(String(40))
    cash_flow_period: Mapped[str | None] = mapped_column(String(40))
    raw_payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    data_quality: Mapped[str] = mapped_column(String(24), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class CorporateActionAIAnalysisRecord(Base):
    __tablename__ = "corporate_action_ai_analyses"
    event_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    analysis_version: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    impact_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    impact_probability: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    impact_horizon: Mapped[str | None] = mapped_column(String(40))
    rationale: Mapped[str | None] = mapped_column(Text)
    positive_factors: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    negative_factors: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    citation_document_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    grounded: Mapped[bool] = mapped_column(nullable=False)
    error: Mapped[str | None] = mapped_column(String(240))
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class CorporateActionOutcomeRecord(Base):
    __tablename__ = "corporate_action_outcomes"
    event_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    instrument_key: Mapped[str] = mapped_column(String(160), nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    reference_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    return_1d_percent: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    abnormal_return_1d_percent: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    return_5d_percent: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    abnormal_return_5d_percent: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    return_20d_percent: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    abnormal_return_20d_percent: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    outcome_status: Mapped[str] = mapped_column(String(24), nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    __table_args__ = (Index("ix_corporate_action_outcomes_instrument", "instrument_key", "event_date"),)
