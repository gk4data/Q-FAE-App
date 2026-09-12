"""Repository operations for historical market data."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import Select, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine

from sqlalchemy.orm import Session

from app.db.models import (
    DataSyncStateRecord,
    CorporateActionRecord,
    CorporateActionAssessmentRecord,
    CorporateActionAdjustmentRecord,
    CorporateActionAIAnalysisRecord,
    CorporateActionDocumentRecord,
    CorporateActionOutcomeRecord,
    CorporateFinancialContextRecord,
    EvidenceObservationRecord,
    MarketCandleRecord,
    MinuteOfDayProfileRecord,
    SessionReconciliationRecord,
)
from app.models.market import AdjustedCandle, Candle, CorporateAction, CorporateActionAdjustment, CorporateActionAIAnalysis, CorporateActionAssessment, CorporateActionDocument, CorporateActionOutcome, CorporateFinancialContext, DailyReconciliationRecord, EvidenceOutcomeObservation, MinuteOfDayProfile
from app.services.corporate_action_pipeline import adjust_candles
from app.services.evidence_outcomes import evaluate_observation
from app.services.market_context import INDIA_TIMEZONE
from app.services.minute_profiles import build_minute_profiles, minute_of_session


class HistoricalMarketRepository:
    """Persist candles and sync watermarks using PostgreSQL upserts."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def ping(self) -> bool:
        from app.db.engine import database_is_available

        return database_is_available(self.engine)

    def upsert_candles(self, candles: Iterable[Candle]) -> int:
        candle_list = list(candles)
        values = [self._candle_values(candle) for candle in candle_list]
        if not values:
            return 0
        grouped: dict[tuple[str, str, str], list[Candle]] = defaultdict(list)
        for candle in candle_list:
            grouped[(candle.source, candle.interval, candle.instrument_key)].append(candle)
        with self.engine.begin() as connection:
            for offset in range(0, len(values), 1000):
                statement = insert(MarketCandleRecord).values(values[offset : offset + 1000])
                statement = statement.on_conflict_do_update(
                    index_elements=["instrument_key", "interval", "timestamp"],
                    set_={
                        "open": statement.excluded.open,
                        "high": statement.excluded.high,
                        "low": statement.excluded.low,
                        "close": statement.excluded.close,
                        "volume": statement.excluded.volume,
                        "open_interest": statement.excluded.open_interest,
                        "source": statement.excluded.source,
                        "updated_at": func.now(),
                    },
                )
                connection.execute(statement)
            for (provider, interval, instrument_key), group in grouped.items():
                sync_statement = insert(DataSyncStateRecord).values(
                    provider=provider,
                    dataset=f"candles:{interval}",
                    instrument_key=instrument_key,
                    data_through=max(candle.timestamp for candle in group),
                    last_success_at=datetime.now(UTC),
                    status="ok",
                    rows_written=len(group),
                    error=None,
                )
                sync_statement = sync_statement.on_conflict_do_update(
                    index_elements=["provider", "dataset", "instrument_key"],
                    set_={
                        "data_through": sync_statement.excluded.data_through,
                        "last_success_at": sync_statement.excluded.last_success_at,
                        "status": "ok",
                        "rows_written": sync_statement.excluded.rows_written,
                        "error": None,
                        "updated_at": func.now(),
                    },
                )
                connection.execute(sync_statement)
        return len(values)

    def get_candles(self, instrument_key: str, interval: str, limit: int = 300) -> list[Candle]:
        query: Select[tuple[MarketCandleRecord]] = (
            select(MarketCandleRecord)
            .where(
                MarketCandleRecord.instrument_key == instrument_key,
                MarketCandleRecord.interval == interval,
            )
            .order_by(MarketCandleRecord.timestamp.desc())
            .limit(limit)
        )
        with Session(self.engine) as session:
            records = list(session.scalars(query))
        return [self._to_candle(record) for record in reversed(records)]

    def latest_candle_timestamp(self, instrument_key: str, interval: str) -> datetime | None:
        query = select(func.max(MarketCandleRecord.timestamp)).where(
            MarketCandleRecord.instrument_key == instrument_key,
            MarketCandleRecord.interval == interval,
        )
        with self.engine.connect() as connection:
            return connection.execute(query).scalar_one_or_none()

    def count_instruments(self, interval: str, instrument_keys: Sequence[str]) -> int:
        if not instrument_keys:
            return 0
        query = select(func.count(func.distinct(MarketCandleRecord.instrument_key))).where(
            MarketCandleRecord.interval == interval,
            MarketCandleRecord.instrument_key.in_(instrument_keys),
        )
        with self.engine.connect() as connection:
            return int(connection.execute(query).scalar_one())

    def count_synced_instruments(self, dataset: str, instrument_keys: Sequence[str]) -> int:
        if not instrument_keys:
            return 0
        query = select(func.count(func.distinct(DataSyncStateRecord.instrument_key))).where(
            DataSyncStateRecord.provider == "upstox",
            DataSyncStateRecord.dataset == dataset,
            DataSyncStateRecord.status == "ok",
            DataSyncStateRecord.instrument_key.in_(instrument_keys),
        )
        with self.engine.connect() as connection:
            return int(connection.execute(query).scalar_one())

    def prune_minute_candles(
        self,
        cutoff: datetime,
        instrument_keys: Sequence[str] | None = None,
    ) -> int:
        """Delete only expired operational one-minute rows."""
        statement = delete(MarketCandleRecord).where(
            MarketCandleRecord.interval == "1minute",
            MarketCandleRecord.timestamp < cutoff,
        )
        if instrument_keys is not None:
            if not instrument_keys:
                return 0
            statement = statement.where(MarketCandleRecord.instrument_key.in_(instrument_keys))
        with self.engine.begin() as connection:
            result = connection.execute(statement)
        return int(result.rowcount or 0)

    def refresh_minute_profiles(
        self,
        instrument_key: str,
        *,
        exclude_session_date: date | None = None,
    ) -> int:
        candles = self.get_candles(instrument_key, "1minute", limit=20_000)
        profiles = build_minute_profiles(
            candles,
            exclude_session_date=exclude_session_date,
            calculated_at=datetime.now(UTC),
        )
        with self.engine.begin() as connection:
            connection.execute(
                delete(MinuteOfDayProfileRecord).where(
                    MinuteOfDayProfileRecord.instrument_key == instrument_key
                )
            )
            if profiles:
                connection.execute(
                    insert(MinuteOfDayProfileRecord),
                    [self._profile_values(profile) for profile in profiles],
                )
        return len(profiles)

    def get_minute_profile(
        self,
        instrument_key: str,
        timestamp: datetime,
    ) -> MinuteOfDayProfile | None:
        minute = minute_of_session(timestamp)
        if minute is None:
            return None
        query = select(MinuteOfDayProfileRecord).where(
            MinuteOfDayProfileRecord.instrument_key == instrument_key,
            MinuteOfDayProfileRecord.minute_of_session == minute,
        )
        with Session(self.engine) as session:
            record = session.scalar(query)
        return self._to_profile(record) if record else None

    def get_minute_profiles(self, instrument_key: str) -> list[MinuteOfDayProfile]:
        query = (
            select(MinuteOfDayProfileRecord)
            .where(MinuteOfDayProfileRecord.instrument_key == instrument_key)
            .order_by(MinuteOfDayProfileRecord.minute_of_session)
        )
        with Session(self.engine) as session:
            records = list(session.scalars(query))
        return [self._to_profile(record) for record in records]

    def count_profile_instruments(self, instrument_keys: Sequence[str]) -> int:
        if not instrument_keys:
            return 0
        query = select(func.count(func.distinct(MinuteOfDayProfileRecord.instrument_key))).where(
            MinuteOfDayProfileRecord.instrument_key.in_(instrument_keys)
        )
        with self.engine.connect() as connection:
            return int(connection.execute(query).scalar_one())

    def get_session_candles(
        self,
        instrument_key: str,
        interval: str,
        session_date: date,
    ) -> list[Candle]:
        start = datetime.combine(session_date, time.min, tzinfo=INDIA_TIMEZONE).astimezone(UTC)
        end = start + timedelta(days=1)
        query = (
            select(MarketCandleRecord)
            .where(
                MarketCandleRecord.instrument_key == instrument_key,
                MarketCandleRecord.interval == interval,
                MarketCandleRecord.timestamp >= start,
                MarketCandleRecord.timestamp < end,
            )
            .order_by(MarketCandleRecord.timestamp)
        )
        with Session(self.engine) as session:
            records = list(session.scalars(query))
        return [self._to_candle(record) for record in records]

    def save_reconciliation(self, result: DailyReconciliationRecord) -> None:
        values = result.model_dump()
        for field in ("official_close", "aggregated_close", "volume_difference_percent"):
            if values[field] is not None:
                values[field] = Decimal(str(values[field]))
        statement = insert(SessionReconciliationRecord).values(values)
        statement = statement.on_conflict_do_update(
            index_elements=["session_date", "instrument_key"],
            set_={
                "symbol": statement.excluded.symbol,
                "status": statement.excluded.status,
                "minute_count": statement.excluded.minute_count,
                "expected_minutes": statement.excluded.expected_minutes,
                "official_close": statement.excluded.official_close,
                "official_volume": statement.excluded.official_volume,
                "aggregated_close": statement.excluded.aggregated_close,
                "aggregated_volume": statement.excluded.aggregated_volume,
                "volume_difference_percent": statement.excluded.volume_difference_percent,
                "ohlc_matches": statement.excluded.ohlc_matches,
                "notes": statement.excluded.notes,
                "reconciled_at": statement.excluded.reconciled_at,
                "updated_at": func.now(),
            },
        )
        with self.engine.begin() as connection:
            connection.execute(statement)

    def get_reconciliations(self, session_date: date) -> list[DailyReconciliationRecord]:
        query = (
            select(SessionReconciliationRecord)
            .where(SessionReconciliationRecord.session_date == session_date)
            .order_by(SessionReconciliationRecord.symbol)
        )
        with Session(self.engine) as session:
            records = list(session.scalars(query))
        return [self._to_reconciliation(record) for record in records]

    def save_evidence_observation(self, observation: EvidenceOutcomeObservation) -> None:
        """Upsert immutable point-in-time inputs without erasing already known outcomes."""
        values = observation.model_dump()
        values["reference_price"] = Decimal(str(observation.reference_price))
        values["evidence_payload"] = observation.evidence_payload
        values["risk_payload"] = observation.risk_payload
        values["market_regime_payload"] = observation.market_regime_payload
        numeric_outcomes = (
            "forward_return_5m_percent", "forward_return_15m_percent",
            "forward_return_30m_percent", "forward_return_60m_percent",
            "forward_return_eod_percent", "mfe_60m_percent", "mae_60m_percent",
        )
        for field in numeric_outcomes:
            value = getattr(observation, field)
            values[field] = Decimal(str(value)) if value is not None else None
        statement = insert(EvidenceObservationRecord).values(values)
        statement = statement.on_conflict_do_update(
            index_elements=["instrument_key", "candle_timestamp"],
            set_={
                "symbol": statement.excluded.symbol,
                "sector": statement.excluded.sector,
                "observed_at": statement.excluded.observed_at,
                "reference_price": statement.excluded.reference_price,
                "confluence": statement.excluded.confluence,
                "signal_state": statement.excluded.signal_state,
                "data_quality": statement.excluded.data_quality,
                "evidence_payload": statement.excluded.evidence_payload,
                "risk_payload": statement.excluded.risk_payload,
                "market_regime_payload": statement.excluded.market_regime_payload,
                "updated_at": func.now(),
            },
        )
        with self.engine.begin() as connection:
            connection.execute(statement)

    def upsert_corporate_actions(
        self,
        isin: str,
        instrument_key: str,
        actions: Iterable[CorporateAction],
    ) -> int:
        """Store current provider facts and record a successful sync even for no events."""
        action_list = list(actions)
        with self.engine.begin() as connection:
            for action in action_list:
                values = action.model_dump()
                values["amount"] = Decimal(str(action.amount)) if action.amount is not None else None
                statement = insert(CorporateActionRecord).values(values)
                statement = statement.on_conflict_do_update(
                    index_elements=["event_id"],
                    set_={
                        "instrument_key": statement.excluded.instrument_key,
                        "symbol": statement.excluded.symbol,
                        "action_type": statement.excluded.action_type,
                        "announcement_date": statement.excluded.announcement_date,
                        "ex_date": statement.excluded.ex_date,
                        "record_date": statement.excluded.record_date,
                        "amount": statement.excluded.amount,
                        "ratio": statement.excluded.ratio,
                        "details": statement.excluded.details,
                        "raw_payload": statement.excluded.raw_payload,
                        "source": statement.excluded.source,
                        "ingested_at": statement.excluded.ingested_at,
                        "updated_at": func.now(),
                    },
                )
                connection.execute(statement)
            sync = insert(DataSyncStateRecord).values(
                provider="upstox",
                dataset="corporate_actions",
                instrument_key=instrument_key,
                data_through=datetime.now(UTC),
                last_success_at=datetime.now(UTC),
                status="ok",
                rows_written=len(action_list),
                error=None,
            )
            connection.execute(
                sync.on_conflict_do_update(
                    index_elements=["provider", "dataset", "instrument_key"],
                    set_={
                        "data_through": sync.excluded.data_through,
                        "last_success_at": sync.excluded.last_success_at,
                        "status": "ok",
                        "rows_written": sync.excluded.rows_written,
                        "error": None,
                        "updated_at": func.now(),
                    },
                )
            )
        return len(action_list)

    def get_corporate_actions(
        self,
        *,
        instrument_key: str | None = None,
        isin: str | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        limit: int = 500,
    ) -> list[CorporateAction]:
        query = select(CorporateActionRecord)
        if instrument_key:
            query = query.where(CorporateActionRecord.instrument_key == instrument_key)
        if isin:
            query = query.where(CorporateActionRecord.isin == isin)
        if from_date:
            query = query.where(CorporateActionRecord.ex_date >= from_date)
        if to_date:
            query = query.where(CorporateActionRecord.ex_date <= to_date)
        query = query.order_by(CorporateActionRecord.ex_date.desc().nullslast(), CorporateActionRecord.symbol).limit(limit)
        with Session(self.engine) as session:
            records = list(session.scalars(query))
        return [self._to_corporate_action(record) for record in records]

    def get_reference_daily_close(
        self,
        instrument_key: str,
        before_date: date | None,
    ) -> tuple[float, date] | None:
        """Return the last daily close strictly before an event date, or latest if undated."""
        query = select(MarketCandleRecord).where(
            MarketCandleRecord.instrument_key == instrument_key,
            MarketCandleRecord.interval == "day",
        )
        if before_date is not None:
            cutoff = datetime.combine(before_date, time.min, tzinfo=INDIA_TIMEZONE).astimezone(UTC)
            query = query.where(MarketCandleRecord.timestamp < cutoff)
        query = query.order_by(MarketCandleRecord.timestamp.desc()).limit(1)
        with Session(self.engine) as session:
            record = session.scalar(query)
        if record is None:
            return None
        return float(record.close), record.timestamp.astimezone(INDIA_TIMEZONE).date()

    def upsert_corporate_action_assessments(
        self,
        assessments: Iterable[CorporateActionAssessment],
    ) -> int:
        assessment_list = list(assessments)
        if not assessment_list:
            return 0
        with self.engine.begin() as connection:
            for assessment in assessment_list:
                values = assessment.model_dump()
                for field in ("materiality_score", "sentiment_score", "confidence", "reference_price"):
                    value = values[field]
                    values[field] = Decimal(str(value)) if value is not None else None
                statement = insert(CorporateActionAssessmentRecord).values(values)
                connection.execute(
                    statement.on_conflict_do_update(
                        index_elements=["event_id", "assessment_version"],
                        set_={
                            "isin": statement.excluded.isin,
                            "instrument_key": statement.excluded.instrument_key,
                            "symbol": statement.excluded.symbol,
                            "category": statement.excluded.category,
                            "direction": statement.excluded.direction,
                            "materiality_score": statement.excluded.materiality_score,
                            "sentiment_score": statement.excluded.sentiment_score,
                            "confidence": statement.excluded.confidence,
                            "impact_horizon": statement.excluded.impact_horizon,
                            "reference_price": statement.excluded.reference_price,
                            "reference_price_date": statement.excluded.reference_price_date,
                            "derived_metrics": statement.excluded.derived_metrics,
                            "evidence": statement.excluded.evidence,
                            "cautions": statement.excluded.cautions,
                            "requires_ai_review": statement.excluded.requires_ai_review,
                            "assessed_at": statement.excluded.assessed_at,
                            "updated_at": func.now(),
                        },
                    )
                )
        return len(assessment_list)

    def get_corporate_action_assessments(
        self,
        *,
        instrument_key: str | None = None,
        category: str | None = None,
        direction: str | None = None,
        minimum_materiality: float | None = None,
        limit: int = 500,
    ) -> list[CorporateActionAssessment]:
        query = select(CorporateActionAssessmentRecord)
        if instrument_key:
            query = query.where(CorporateActionAssessmentRecord.instrument_key == instrument_key)
        if category:
            query = query.where(CorporateActionAssessmentRecord.category == category)
        if direction:
            query = query.where(CorporateActionAssessmentRecord.direction == direction)
        if minimum_materiality is not None:
            query = query.where(CorporateActionAssessmentRecord.materiality_score >= minimum_materiality)
        query = query.order_by(CorporateActionAssessmentRecord.materiality_score.desc(), CorporateActionAssessmentRecord.symbol).limit(limit)
        with Session(self.engine) as session:
            records = list(session.scalars(query))
        return [self._to_corporate_action_assessment(record) for record in records]

    def count_corporate_action_assessments(self, instrument_keys: Sequence[str]) -> int:
        if not instrument_keys:
            return 0
        query = select(func.count()).select_from(CorporateActionAssessmentRecord).where(
            CorporateActionAssessmentRecord.instrument_key.in_(instrument_keys)
        )
        with self.engine.connect() as connection:
            return int(connection.execute(query).scalar_one())

    def upsert_corporate_action_adjustments(self, rows: Iterable[CorporateActionAdjustment]) -> int:
        values = list(rows)
        with self.engine.begin() as connection:
            for item in values:
                payload = item.model_dump()
                for field in ("price_factor", "volume_factor", "reference_close"):
                    value = payload[field]
                    payload[field] = Decimal(str(value)) if value is not None else None
                statement = insert(CorporateActionAdjustmentRecord).values(payload)
                connection.execute(statement.on_conflict_do_update(index_elements=["event_id", "calculation_version"], set_={key: getattr(statement.excluded, key) for key in payload if key not in {"event_id", "calculation_version"}}))
        return len(values)

    def get_corporate_action_adjustments(self, instrument_key: str) -> list[CorporateActionAdjustment]:
        query = select(CorporateActionAdjustmentRecord).where(CorporateActionAdjustmentRecord.instrument_key == instrument_key).order_by(CorporateActionAdjustmentRecord.effective_date)
        with Session(self.engine) as session:
            records = list(session.scalars(query))
        return [CorporateActionAdjustment(event_id=r.event_id, calculation_version=r.calculation_version, instrument_key=r.instrument_key, category=r.category, effective_date=r.effective_date, price_factor=float(r.price_factor) if r.price_factor is not None else None, volume_factor=float(r.volume_factor) if r.volume_factor is not None else None, status=r.status, reason=r.reason, reference_close=float(r.reference_close) if r.reference_close is not None else None, calculated_at=r.calculated_at) for r in records]

    def get_adjusted_candles(self, instrument_key: str, *, interval: str = "day", limit: int = 300) -> list[AdjustedCandle]:
        return adjust_candles(self.get_candles(instrument_key, interval, limit), self.get_corporate_action_adjustments(instrument_key))

    def upsert_corporate_action_documents(self, rows: Iterable[CorporateActionDocument]) -> int:
        values = list(rows)
        with self.engine.begin() as connection:
            for item in values:
                payload = item.model_dump()
                statement = insert(CorporateActionDocumentRecord).values(payload)
                connection.execute(statement.on_conflict_do_update(index_elements=["document_id"], set_={key: getattr(statement.excluded, key) for key in payload if key != "document_id"}))
        return len(values)

    def get_corporate_action_documents(self, *, instrument_key: str | None = None, event_id: str | None = None, limit: int = 500) -> list[CorporateActionDocument]:
        query = select(CorporateActionDocumentRecord)
        if instrument_key:
            query = query.where(CorporateActionDocumentRecord.instrument_key == instrument_key)
        query = query.order_by(CorporateActionDocumentRecord.published_at.desc()).limit(limit)
        with Session(self.engine) as session:
            records = list(session.scalars(query))
        rows = [CorporateActionDocument(document_id=r.document_id, instrument_key=r.instrument_key, symbol=r.symbol, source=r.source, published_at=r.published_at, title=r.title, summary=r.summary, source_url=r.source_url, document_text=r.document_text, matched_event_ids=list(r.matched_event_ids), raw_payload=dict(r.raw_payload), ingested_at=r.ingested_at) for r in records]
        return [row for row in rows if event_id in row.matched_event_ids] if event_id else rows

    def upsert_corporate_financial_context(self, item: CorporateFinancialContext) -> None:
        payload = item.model_dump()
        for field in ("latest_revenue_crore", "latest_operating_profit_crore", "latest_net_profit_crore", "latest_operating_cash_flow_crore"):
            value = payload[field]
            payload[field] = Decimal(str(value)) if value is not None else None
        statement = insert(CorporateFinancialContextRecord).values(payload)
        with self.engine.begin() as connection:
            connection.execute(statement.on_conflict_do_update(index_elements=["isin"], set_={key: getattr(statement.excluded, key) for key in payload if key != "isin"}))

    def get_corporate_financial_context(self, isin: str) -> CorporateFinancialContext | None:
        with Session(self.engine) as session:
            r = session.scalar(select(CorporateFinancialContextRecord).where(CorporateFinancialContextRecord.isin == isin))
        if r is None:
            return None
        return CorporateFinancialContext(isin=r.isin, instrument_key=r.instrument_key, symbol=r.symbol, statement_type=r.statement_type, latest_revenue_crore=float(r.latest_revenue_crore) if r.latest_revenue_crore is not None else None, latest_operating_profit_crore=float(r.latest_operating_profit_crore) if r.latest_operating_profit_crore is not None else None, latest_net_profit_crore=float(r.latest_net_profit_crore) if r.latest_net_profit_crore is not None else None, latest_operating_cash_flow_crore=float(r.latest_operating_cash_flow_crore) if r.latest_operating_cash_flow_crore is not None else None, revenue_period=r.revenue_period, cash_flow_period=r.cash_flow_period, raw_payload=dict(r.raw_payload), data_quality=r.data_quality, fetched_at=r.fetched_at)

    def upsert_corporate_action_ai_analyses(self, rows: Iterable[CorporateActionAIAnalysis]) -> int:
        values = list(rows)
        with self.engine.begin() as connection:
            for item in values:
                payload = item.model_dump()
                for field in ("impact_score", "impact_probability", "confidence"):
                    value = payload[field]
                    payload[field] = Decimal(str(value)) if value is not None else None
                statement = insert(CorporateActionAIAnalysisRecord).values(payload)
                connection.execute(statement.on_conflict_do_update(index_elements=["event_id", "analysis_version"], set_={key: getattr(statement.excluded, key) for key in payload if key not in {"event_id", "analysis_version"}}))
        return len(values)

    def get_corporate_action_ai_analyses(self, *, instrument_key: str | None = None, event_id: str | None = None) -> list[CorporateActionAIAnalysis]:
        query = select(CorporateActionAIAnalysisRecord)
        if event_id:
            query = query.where(CorporateActionAIAnalysisRecord.event_id == event_id)
        if instrument_key:
            query = query.join(CorporateActionRecord, CorporateActionRecord.event_id == CorporateActionAIAnalysisRecord.event_id).where(CorporateActionRecord.instrument_key == instrument_key)
        with Session(self.engine) as session:
            records = list(session.scalars(query))
        return [CorporateActionAIAnalysis(event_id=r.event_id, analysis_version=r.analysis_version, provider=r.provider, model=r.model, status=r.status, impact_score=float(r.impact_score) if r.impact_score is not None else None, impact_probability=float(r.impact_probability) if r.impact_probability is not None else None, confidence=float(r.confidence) if r.confidence is not None else None, impact_horizon=r.impact_horizon, rationale=r.rationale, positive_factors=list(r.positive_factors), negative_factors=list(r.negative_factors), citation_document_ids=list(r.citation_document_ids), grounded=r.grounded, error=r.error, analyzed_at=r.analyzed_at) for r in records]

    def upsert_corporate_action_outcomes(self, rows: Iterable[CorporateActionOutcome]) -> int:
        values = list(rows)
        with self.engine.begin() as connection:
            for item in values:
                payload = item.model_dump()
                for field in ("reference_price", "return_1d_percent", "abnormal_return_1d_percent", "return_5d_percent", "abnormal_return_5d_percent", "return_20d_percent", "abnormal_return_20d_percent"):
                    value = payload[field]
                    payload[field] = Decimal(str(value)) if value is not None else None
                statement = insert(CorporateActionOutcomeRecord).values(payload)
                connection.execute(statement.on_conflict_do_update(index_elements=["event_id"], set_={key: getattr(statement.excluded, key) for key in payload if key != "event_id"}))
        return len(values)

    def get_corporate_action_outcomes(self, instrument_key: str | None = None) -> list[CorporateActionOutcome]:
        query = select(CorporateActionOutcomeRecord)
        if instrument_key:
            query = query.where(CorporateActionOutcomeRecord.instrument_key == instrument_key)
        query = query.order_by(CorporateActionOutcomeRecord.event_date.desc())
        with Session(self.engine) as session:
            records = list(session.scalars(query))
        numeric = ("reference_price", "return_1d_percent", "abnormal_return_1d_percent", "return_5d_percent", "abnormal_return_5d_percent", "return_20d_percent", "abnormal_return_20d_percent")
        return [CorporateActionOutcome(event_id=r.event_id, instrument_key=r.instrument_key, event_date=r.event_date, outcome_status=r.outcome_status, evaluated_at=r.evaluated_at, **{field: float(value) if (value := getattr(r, field)) is not None else None for field in numeric}) for r in records]

    def get_evidence_observations(
        self,
        session_date: date,
        instrument_key: str | None = None,
    ) -> list[EvidenceOutcomeObservation]:
        start = datetime.combine(session_date, time.min, tzinfo=INDIA_TIMEZONE).astimezone(UTC)
        end = start + timedelta(days=1)
        query = select(EvidenceObservationRecord).where(
            EvidenceObservationRecord.candle_timestamp >= start,
            EvidenceObservationRecord.candle_timestamp < end,
        )
        if instrument_key:
            query = query.where(EvidenceObservationRecord.instrument_key == instrument_key)
        query = query.order_by(EvidenceObservationRecord.candle_timestamp, EvidenceObservationRecord.symbol)
        with Session(self.engine) as session:
            records = list(session.scalars(query))
        return [self._to_evidence_observation(record) for record in records]

    def evaluate_evidence_outcomes(
        self,
        instrument_key: str,
        session_date: date,
        *,
        eod_close: float | None = None,
    ) -> int:
        observations = self.get_evidence_observations(session_date, instrument_key)
        if not observations:
            return 0
        candles = self.get_session_candles(instrument_key, "1minute", session_date)
        evaluated = [evaluate_observation(item, candles, eod_close=eod_close) for item in observations]
        numeric_fields = (
            "forward_return_5m_percent", "forward_return_15m_percent",
            "forward_return_30m_percent", "forward_return_60m_percent",
            "forward_return_eod_percent", "mfe_60m_percent", "mae_60m_percent",
        )
        with self.engine.begin() as connection:
            for item in evaluated:
                values: dict[str, object] = {
                    field: Decimal(str(value)) if (value := getattr(item, field)) is not None else None
                    for field in numeric_fields
                }
                values.update(
                    outcome_status=item.outcome_status,
                    evaluated_through=item.evaluated_through,
                    updated_at=func.now(),
                )
                connection.execute(
                    update(EvidenceObservationRecord)
                    .where(
                        EvidenceObservationRecord.instrument_key == item.instrument_key,
                        EvidenceObservationRecord.candle_timestamp == item.candle_timestamp,
                    )
                    .values(**values)
                )
        return len(evaluated)

    @staticmethod
    def _candle_values(candle: Candle) -> dict[str, object]:
        return {
            "instrument_key": candle.instrument_key,
            "interval": candle.interval,
            "timestamp": candle.timestamp,
            "open": Decimal(str(candle.open)),
            "high": Decimal(str(candle.high)),
            "low": Decimal(str(candle.low)),
            "close": Decimal(str(candle.close)),
            "volume": candle.volume,
            "open_interest": candle.open_interest,
            "source": candle.source,
        }

    @staticmethod
    def _to_candle(record: MarketCandleRecord) -> Candle:
        return Candle(
            instrument_key=record.instrument_key,
            timestamp=record.timestamp,
            interval=record.interval,
            open=float(record.open),
            high=float(record.high),
            low=float(record.low),
            close=float(record.close),
            volume=record.volume,
            open_interest=record.open_interest,
            source=record.source,
        )

    @staticmethod
    def _profile_values(profile: MinuteOfDayProfile) -> dict[str, object]:
        values = profile.model_dump()
        for field in (
            "mean_volume",
            "median_volume",
            "volume_stddev",
            "volume_p25",
            "volume_p75",
            "mean_range_bps",
            "mean_abs_return_bps",
            "mean_traded_value_inr",
        ):
            if values[field] is not None:
                values[field] = Decimal(str(values[field]))
        return values

    @staticmethod
    def _to_profile(record: MinuteOfDayProfileRecord) -> MinuteOfDayProfile:
        return MinuteOfDayProfile(
            instrument_key=record.instrument_key,
            minute_of_session=record.minute_of_session,
            sample_count=record.sample_count,
            mean_volume=float(record.mean_volume),
            median_volume=float(record.median_volume),
            volume_stddev=float(record.volume_stddev),
            volume_p25=float(record.volume_p25),
            volume_p75=float(record.volume_p75),
            mean_range_bps=float(record.mean_range_bps) if record.mean_range_bps is not None else None,
            mean_abs_return_bps=(
                float(record.mean_abs_return_bps)
                if record.mean_abs_return_bps is not None
                else None
            ),
            mean_traded_value_inr=(
                float(record.mean_traded_value_inr)
                if record.mean_traded_value_inr is not None
                else None
            ),
            calculation_version=record.calculation_version,
            data_through=record.data_through,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _to_reconciliation(record: SessionReconciliationRecord) -> DailyReconciliationRecord:
        return DailyReconciliationRecord(
            session_date=record.session_date,
            instrument_key=record.instrument_key,
            symbol=record.symbol,
            status=record.status,
            minute_count=record.minute_count,
            expected_minutes=record.expected_minutes,
            official_close=float(record.official_close),
            official_volume=record.official_volume,
            aggregated_close=(
                float(record.aggregated_close) if record.aggregated_close is not None else None
            ),
            aggregated_volume=record.aggregated_volume,
            volume_difference_percent=(
                float(record.volume_difference_percent)
                if record.volume_difference_percent is not None
                else None
            ),
            ohlc_matches=record.ohlc_matches,
            notes=list(record.notes),
            reconciled_at=record.reconciled_at,
        )

    @staticmethod
    def _to_evidence_observation(record: EvidenceObservationRecord) -> EvidenceOutcomeObservation:
        numeric_fields = (
            "forward_return_5m_percent", "forward_return_15m_percent",
            "forward_return_30m_percent", "forward_return_60m_percent",
            "forward_return_eod_percent", "mfe_60m_percent", "mae_60m_percent",
        )
        values = {field: float(value) if (value := getattr(record, field)) is not None else None for field in numeric_fields}
        return EvidenceOutcomeObservation(
            instrument_key=record.instrument_key,
            symbol=record.symbol,
            sector=record.sector,
            candle_timestamp=record.candle_timestamp,
            observed_at=record.observed_at,
            reference_price=float(record.reference_price),
            confluence=record.confluence,
            signal_state=record.signal_state,
            data_quality=record.data_quality,
            evidence_payload=dict(record.evidence_payload),
            risk_payload=dict(record.risk_payload) if record.risk_payload else None,
            market_regime_payload=dict(record.market_regime_payload) if record.market_regime_payload else None,
            outcome_status=record.outcome_status,
            evaluated_through=record.evaluated_through,
            **values,
        )

    @staticmethod
    def _to_corporate_action(record: CorporateActionRecord) -> CorporateAction:
        return CorporateAction(
            event_id=record.event_id,
            isin=record.isin,
            instrument_key=record.instrument_key,
            symbol=record.symbol,
            action_type=record.action_type,
            announcement_date=record.announcement_date,
            ex_date=record.ex_date,
            record_date=record.record_date,
            amount=float(record.amount) if record.amount is not None else None,
            ratio=record.ratio,
            details=dict(record.details),
            raw_payload=dict(record.raw_payload),
            source=record.source,
            ingested_at=record.ingested_at,
        )

    @staticmethod
    def _to_corporate_action_assessment(record: CorporateActionAssessmentRecord) -> CorporateActionAssessment:
        return CorporateActionAssessment(
            event_id=record.event_id,
            assessment_version=record.assessment_version,
            isin=record.isin,
            instrument_key=record.instrument_key,
            symbol=record.symbol,
            category=record.category,
            direction=record.direction,
            materiality_score=float(record.materiality_score),
            sentiment_score=float(record.sentiment_score),
            confidence=float(record.confidence),
            impact_horizon=record.impact_horizon,
            reference_price=float(record.reference_price) if record.reference_price is not None else None,
            reference_price_date=record.reference_price_date,
            derived_metrics=dict(record.derived_metrics),
            evidence=list(record.evidence),
            cautions=list(record.cautions),
            requires_ai_review=record.requires_ai_review,
            assessed_at=record.assessed_at,
        )
