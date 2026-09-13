"""Orchestrate pre-market loading and the Upstox live market session."""

from __future__ import annotations

import logging
import threading
from datetime import UTC, date, datetime, time as datetime_time, timedelta
from typing import Any

import upstox_client

from app.core.config import Settings
from app.db.repository import HistoricalMarketRepository
from app.models.market import (
    AdjustedCandle,
    Candle,
    CorporateAction,
    CorporateActionAssessment,
    CorporateActionAIAnalysis,
    CorporateActionCalibrationReport,
    CorporateActionDocument,
    CorporateActionOutcome,
    CorporateFinancialContext,
    DailyReconciliationRecord,
    DailyRegimeSnapshot,
    EvidenceOutcomeObservation,
    FinancialResultAvailability,
    FinancialResultCheckReport,
    FinancialMetricSnapshot,
    FlowLiquidityConfirmation,
    LiveSnapshot,
    MinuteOfDayProfile,
    OpportunityEvidenceSnapshot,
    RankedOpportunity,
    RelativeVolumeMetric,
    StockFeatureSnapshot,
    RiskAssessment,
    MarketRegimeSnapshot,
    WatchlistItem,
)
from app.services.daily_regime import (
    aggregate_session_candle,
    build_daily_regime,
    cumulative_relative_volume,
    merge_daily_history,
)
from app.services.corporate_action_assessment import assess_corporate_action
from app.services.corporate_action_ai import CorporateActionAIScorer, unavailable_ai_analysis
from app.services.corporate_action_documents import NseAnnouncementClient
from app.services.corporate_action_pipeline import (
    build_adjustment,
    build_calibration_report,
    build_corporate_action_context,
    evaluate_action_outcome,
)
from app.services.equity_universe import EquityUniverseService
from app.services.evidence_integration import build_opportunity_evidence
from app.services.flow_confirmation import build_flow_liquidity_confirmation
from app.services.financial_results import (
    context_from_financial_snapshot,
    snapshot_is_reusable,
)
from app.services.financial_metrics import calculate_financial_metrics
from app.services.opportunity_scoring import build_opportunity_score, rank_opportunities
from app.services.market_regime import build_market_regime
from app.services.market_features import build_stock_features
from app.services.market_context import INDIA_TIMEZONE, build_market_context, calculate_relative_volume
from app.services.market_state import MarketStateStore
from app.services.risk_gates import build_risk_assessment
from app.services.signal_persistence import build_signal_persistence
from app.services.session_reconciliation import reconcile_session
from app.services.upstox_auth import TokenCache
from app.services.upstox_market import (
    MARKET_CONTEXT_KEYS,
    MARKET_CONTEXT_SYMBOLS,
    MAX_FULL_FEED_INSTRUMENTS,
    NIFTY_50_KEY,
    RequestRateLimiter,
    SECTOR_INDEX_SYMBOLS,
    UpstoxMarketDataClient,
    normalize_feed_message,
)

logger = logging.getLogger(__name__)
NSE_MARKET_CLOSE = datetime_time(hour=15, minute=30)


def nse_market_close_at(now: datetime) -> datetime:
    """Return the normal NSE cash-market close for the supplied session date."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("market-clock timestamps must include a timezone")
    local_now = now.astimezone(INDIA_TIMEZONE)
    return datetime.combine(local_now.date(), NSE_MARKET_CLOSE, tzinfo=INDIA_TIMEZONE)


class MarketRuntimeError(RuntimeError):
    """Raised when a requested market operation cannot start safely."""


class MarketRuntime:
    """Single-process coordinator for background bootstrap and live streaming."""

    def __init__(
        self,
        settings: Settings,
        state_store: MarketStateStore,
        universe_service: EquityUniverseService,
        historical_repository: HistoricalMarketRepository | None = None,
    ) -> None:
        self.settings = settings
        self.state_store = state_store
        self.universe_service = universe_service
        self.historical_repository = historical_repository
        self._lock = threading.RLock()
        self._bootstrap_thread: threading.Thread | None = None
        self._stream_thread: threading.Thread | None = None
        self._reconciliation_thread: threading.Thread | None = None
        self._streamer: Any | None = None
        self._context_timer: threading.Timer | None = None
        self._market_close_timer: threading.Timer | None = None
        self._last_context_bucket: int | None = None
        self._persisted_minute_watermarks: dict[str, datetime | None] = {}
        self._symbols: dict[str, str] = {}
        self._bootstrap: dict[str, Any] = {
            "state": "idle",
            "total": 0,
            "processed": 0,
            "history_loaded": 0,
            "minute_history_persisted": 0,
            "minute_profiles_built": 0,
            "daily_history_loaded": 0,
            "daily_history_persisted": 0,
            "benchmark_daily_loaded": 0,
            "sectors_loaded": 0,
            "corporate_actions_synced": 0,
            "corporate_actions_stored": 0,
            "corporate_actions_assessed": 0,
            "corporate_adjustments_built": 0,
            "corporate_documents_stored": 0,
            "corporate_financial_contexts": 0,
            "financial_results_reused": 0,
            "corporate_ai_analyzed": 0,
            "corporate_outcomes_evaluated": 0,
            "errors": 0,
            "started_at": None,
            "finished_at": None,
            "recent_errors": [],
        }
        self._live: dict[str, Any] = {
            "state": "stopped",
            "connected": False,
            "subscribed": 0,
            "last_message_at": None,
            "last_context_at": None,
            "scheduled_stop_at": None,
            "error": None,
        }
        self._reconciliation: dict[str, Any] = {
            "state": "idle",
            "session_date": None,
            "total": 0,
            "processed": 0,
            "matched": 0,
            "with_differences": 0,
            "official_only": 0,
            "missing": 0,
            "errors": 0,
            "started_at": None,
            "finished_at": None,
            "recent_errors": [],
        }

    def status(self) -> dict[str, Any]:
        try:
            redis_available = self.state_store.ping()
        except Exception:
            redis_available = False
        try:
            database_available = bool(
                self.historical_repository and self.historical_repository.ping()
            )
        except Exception:
            database_available = False
        with self._lock:
            bootstrap = dict(self._bootstrap)
            live = dict(self._live)
            reconciliation = dict(self._reconciliation)
        if redis_available and bootstrap["state"] != "running":
            try:
                instruments = self._resolved_instruments(None)
                keys = [instrument["instrument_key"] for instrument in instruments]
                sectors = self.state_store.get_sectors()
                benchmark_keys = tuple(dict.fromkeys((NIFTY_50_KEY, *SECTOR_INDEX_SYMBOLS.keys())))
                bootstrap.update(
                    {
                        "total": len(keys),
                        "history_loaded": sum(self.state_store.has_candles(key) for key in keys),
                        "daily_history_loaded": sum(
                            self.state_store.has_daily_candles(key) for key in keys
                        ),
                        "benchmark_daily_loaded": sum(
                            self.state_store.has_daily_candles(key) for key in benchmark_keys
                        ),
                        "sectors_loaded": sum(key in sectors for key in keys),
                    }
                )
            except Exception:
                pass
        if database_available and bootstrap["state"] != "running":
            try:
                instruments = self._resolved_instruments(None)
                keys = [instrument["instrument_key"] for instrument in instruments]
                bootstrap["daily_history_persisted"] = (
                    self.historical_repository.count_instruments("day", keys)
                    if self.historical_repository
                    else 0
                )
                bootstrap["minute_history_persisted"] = (
                    self.historical_repository.count_instruments("1minute", keys)
                    if self.historical_repository
                    else 0
                )
                bootstrap["minute_profiles_built"] = (
                    self.historical_repository.count_profile_instruments(keys)
                    if self.historical_repository
                    else 0
                )
                bootstrap["corporate_actions_synced"] = (
                    self.historical_repository.count_synced_instruments("corporate_actions", keys)
                    if self.historical_repository
                    else 0
                )
                bootstrap["corporate_actions_assessed"] = (
                    self.historical_repository.count_corporate_action_assessments(keys)
                    if self.historical_repository
                    else 0
                )
            except Exception:
                pass
        return {
            "cadence_seconds": self.settings.qfae_market_snapshot_interval_seconds,
            "pilot_size": self.settings.qfae_market_pilot_size,
            "redis_available": redis_available,
            "database_available": database_available,
            "bootstrap": bootstrap,
            "live": live,
            "reconciliation": reconciliation,
        }

    def get_watchlist(self, limit: int | None = None) -> list[WatchlistItem]:
        """Build a compact view of cached historical and live data for the pilot universe."""
        self._require_state_store()
        instruments = self._resolved_instruments(limit)
        snapshots = {
            snapshot.instrument_key: snapshot
            for snapshot in self.state_store.get_snapshots()
        }
        sectors = self.state_store.get_sectors()
        relative_volumes = self.state_store.get_relative_volumes()
        with self._lock:
            live_connected = bool(self._live["connected"])
        rows: list[WatchlistItem] = []

        for instrument in instruments:
            key = instrument["instrument_key"]
            snapshot = snapshots.get(key)
            history = self.state_store.get_candles(key, limit=self._history_limit())
            candle = snapshot.current_candle if snapshot and snapshot.current_candle else (
                history[-1] if history else None
            )
            ltp = snapshot.ltp if snapshot and snapshot.ltp is not None else (
                candle.close if candle else None
            )
            previous_close = snapshot.previous_close if snapshot else None
            if previous_close is None:
                previous_close = self._previous_session_close(history)
            change_percent = None
            if ltp is not None and previous_close:
                change_percent = ((ltp - previous_close) / previous_close) * 100

            spread_bps = None
            if snapshot and snapshot.best_bid_price and snapshot.best_ask_price:
                midpoint = (snapshot.best_bid_price + snapshot.best_ask_price) / 2
                if midpoint > 0:
                    spread_bps = ((snapshot.best_ask_price - snapshot.best_bid_price) / midpoint) * 10_000

            relative_volume = None
            relative_volume_metric = relative_volumes.get(key)
            if relative_volume_metric and candle:
                metric_date = relative_volume_metric.candle_timestamp.astimezone(INDIA_TIMEZONE).date()
                candle_date = candle.timestamp.astimezone(INDIA_TIMEZONE).date()
                if metric_date == candle_date:
                    relative_volume = relative_volume_metric.relative_volume

            rows.append(
                WatchlistItem(
                    instrument_key=key,
                    symbol=instrument["symbol"],
                    company_name=instrument.get("company_name") or instrument["symbol"],
                    sector=sectors.get(key),
                    ltp=ltp,
                    previous_close=previous_close,
                    change_percent=change_percent,
                    open=candle.open if candle else None,
                    high=candle.high if candle else None,
                    low=candle.low if candle else None,
                    close=candle.close if candle else None,
                    volume=candle.volume if candle else None,
                    relative_volume=relative_volume,
                    spread_bps=spread_bps,
                    updated_at=(snapshot.received_at if snapshot else candle.timestamp if candle else None),
                    data_state=(
                        "live"
                        if snapshot and live_connected
                        else "cached"
                        if snapshot
                        else "history"
                        if candle
                        else "waiting"
                    ),
                )
            )
        return rows

    def get_features(self, limit: int | None = None) -> list[StockFeatureSnapshot]:
        """Return current-session features in approved-universe order."""
        self._require_state_store()
        instruments = self._resolved_instruments(limit)
        features = self.state_store.get_features()
        snapshots = {
            snapshot.instrument_key: snapshot
            for snapshot in self.state_store.get_snapshots()
        }
        today = datetime.now(INDIA_TIMEZONE).date()
        rows = []
        for instrument in instruments:
            key = instrument["instrument_key"]
            feature = features.get(key)
            snapshot = snapshots.get(key)
            if feature is None or snapshot is None or snapshot.current_candle is None:
                continue
            feature_date = feature.candle_timestamp.astimezone(INDIA_TIMEZONE).date()
            snapshot_date = snapshot.current_candle.timestamp.astimezone(INDIA_TIMEZONE).date()
            if feature_date == snapshot_date == today:
                rows.append(feature)
        return rows

    def get_daily_regimes(self, limit: int | None = None) -> list[DailyRegimeSnapshot]:
        """Return multi-horizon evidence in approved-universe order."""
        self._require_state_store()
        instruments = self._resolved_instruments(limit)
        regimes = self.state_store.get_daily_regimes()
        return [regimes[item["instrument_key"]] for item in instruments if item["instrument_key"] in regimes]

    def get_minute_profiles(self, instrument_key: str) -> list[MinuteOfDayProfile]:
        if self.historical_repository is None:
            raise MarketRuntimeError("PostgreSQL historical storage is not configured")
        try:
            return self.historical_repository.get_minute_profiles(instrument_key)
        except Exception as exc:
            raise MarketRuntimeError("PostgreSQL minute profiles are unavailable") from exc

    def get_opportunity_evidence(self, limit: int | None = None) -> list[OpportunityEvidenceSnapshot]:
        """Return validated feature families and their stored point-in-time score."""
        self._require_state_store()
        instruments = self._resolved_instruments(limit)
        features = self.state_store.get_features()
        regimes = self.state_store.get_daily_regimes()
        context = self.state_store.get_context()
        as_of = datetime.now(UTC)
        rows = []
        signals = self.state_store.get_signals()
        risks = self.state_store.get_risk_assessments()
        corporate_contexts = self.state_store.get_corporate_action_contexts()
        for instrument in instruments:
            feature = features.get(instrument["instrument_key"])
            if feature is None:
                continue
            cached = self.state_store.get_evidence_history(feature.instrument_key, 1)
            if cached and cached[-1].as_of == feature.as_of:
                rows.append(cached[-1])
                continue
            flow_liquidity = self._build_flow_confirmation(feature)
            evidence = build_opportunity_evidence(
                    feature,
                    regimes.get(instrument["instrument_key"]),
                    context,
                    as_of=as_of,
                    freshness_seconds=self.settings.qfae_market_snapshot_interval_seconds * 2,
                    flow_liquidity=flow_liquidity,
                )
            rows.append(
                evidence.model_copy(
                    update={
                        "signal_persistence": signals.get(feature.instrument_key),
                        "risk_assessment": risks.get(feature.instrument_key),
                        "corporate_action_context": corporate_contexts.get(feature.instrument_key),
                    }
                )
            )
        confluence_order = {
            "strong_support": 0,
            "supportive": 1,
            "mixed": 2,
            "caution": 3,
            "insufficient": 4,
        }
        return sorted(rows, key=lambda row: (confluence_order.get(row.confluence, 9), row.symbol))

    def get_ranked_opportunities(self, limit: int | None = None) -> list[RankedOpportunity]:
        """Rank current long-continuation candidates with explicit coverage and gates."""
        evidence = self.get_opportunity_evidence(limit)
        market_regime = self.state_store.get_market_regime()
        features = self.state_store.get_features()
        snapshots = {
            snapshot.instrument_key: snapshot
            for snapshot in self.state_store.get_snapshots()
        }
        evidence = [
            item.model_copy(update={"market_regime": market_regime})
            for item in evidence
        ]
        try:
            return rank_opportunities(
                evidence,
                self._latest_financial_metrics_by_instrument(),
                {
                    key: feature.relative_strength.session_return_percent
                    for key, feature in features.items()
                },
                {
                    key: snapshot.ltp if snapshot.ltp is not None and snapshot.ltp > 0 else None
                    for key, snapshot in snapshots.items()
                },
                weights=self._opportunity_scoring_weights(),
            )
        except ValueError as exc:
            raise MarketRuntimeError(f"Opportunity scoring configuration is invalid: {exc}") from exc

    def get_risk_assessments(self, limit: int | None = None) -> list[RiskAssessment]:
        instruments = self._resolved_instruments(limit)
        values = self.state_store.get_risk_assessments()
        return [values[item["instrument_key"]] for item in instruments if item["instrument_key"] in values]

    def get_market_regime(self) -> MarketRegimeSnapshot | None:
        self._require_state_store()
        return self.state_store.get_market_regime()

    def get_evidence_outcomes(
        self,
        session_date: date,
        instrument_key: str | None = None,
    ) -> list[EvidenceOutcomeObservation]:
        if self.historical_repository is None:
            raise MarketRuntimeError("PostgreSQL historical storage is not configured")
        try:
            return self.historical_repository.get_evidence_observations(session_date, instrument_key)
        except Exception as exc:
            raise MarketRuntimeError("Evidence outcome records are unavailable") from exc

    def get_corporate_actions(
        self,
        *,
        instrument_key: str | None = None,
        isin: str | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        limit: int = 500,
    ) -> list[CorporateAction]:
        if self.historical_repository is None:
            raise MarketRuntimeError("PostgreSQL historical storage is not configured")
        try:
            return self.historical_repository.get_corporate_actions(
                instrument_key=instrument_key,
                isin=isin,
                from_date=from_date,
                to_date=to_date,
                limit=limit,
            )
        except Exception as exc:
            raise MarketRuntimeError("Corporate-action records are unavailable") from exc

    def get_corporate_action_assessments(
        self,
        *,
        instrument_key: str | None = None,
        category: str | None = None,
        direction: str | None = None,
        minimum_materiality: float | None = None,
        limit: int = 500,
    ) -> list[CorporateActionAssessment]:
        if self.historical_repository is None:
            raise MarketRuntimeError("PostgreSQL historical storage is not configured")
        try:
            return self.historical_repository.get_corporate_action_assessments(
                instrument_key=instrument_key,
                category=category,
                direction=direction,
                minimum_materiality=minimum_materiality,
                limit=limit,
            )
        except Exception as exc:
            raise MarketRuntimeError("Corporate-action assessments are unavailable") from exc

    def get_adjusted_candles(
        self, instrument_key: str, *, interval: str = "day", limit: int = 300
    ) -> list[AdjustedCandle]:
        if self.historical_repository is None:
            raise MarketRuntimeError("PostgreSQL historical storage is not configured")
        try:
            return self.historical_repository.get_adjusted_candles(
                instrument_key, interval=interval, limit=limit
            )
        except Exception as exc:
            raise MarketRuntimeError("Adjusted candles are unavailable") from exc

    def get_corporate_action_documents(
        self, *, instrument_key: str | None = None, event_id: str | None = None, limit: int = 500
    ) -> list[CorporateActionDocument]:
        if self.historical_repository is None:
            raise MarketRuntimeError("PostgreSQL historical storage is not configured")
        try:
            return self.historical_repository.get_corporate_action_documents(
                instrument_key=instrument_key, event_id=event_id, limit=limit
            )
        except Exception as exc:
            raise MarketRuntimeError("Corporate-action documents are unavailable") from exc

    def get_corporate_action_ai_analyses(
        self, *, instrument_key: str | None = None, event_id: str | None = None
    ) -> list[CorporateActionAIAnalysis]:
        if self.historical_repository is None:
            raise MarketRuntimeError("PostgreSQL historical storage is not configured")
        try:
            return self.historical_repository.get_corporate_action_ai_analyses(
                instrument_key=instrument_key, event_id=event_id
            )
        except Exception as exc:
            raise MarketRuntimeError("Corporate-action AI analyses are unavailable") from exc

    def get_corporate_action_outcomes(
        self, instrument_key: str | None = None
    ) -> list[CorporateActionOutcome]:
        if self.historical_repository is None:
            raise MarketRuntimeError("PostgreSQL historical storage is not configured")
        try:
            return self.historical_repository.get_corporate_action_outcomes(instrument_key)
        except Exception as exc:
            raise MarketRuntimeError("Corporate-action outcomes are unavailable") from exc

    def get_corporate_action_calibration(self) -> CorporateActionCalibrationReport:
        if self.historical_repository is None:
            raise MarketRuntimeError("PostgreSQL historical storage is not configured")
        try:
            return build_calibration_report(
                self.historical_repository.get_corporate_action_assessments(limit=10000),
                self.historical_repository.get_corporate_action_outcomes(),
            )
        except Exception as exc:
            raise MarketRuntimeError("Corporate-action calibration is unavailable") from exc

    def check_financial_results(
        self,
        limit: int | None = None,
    ) -> FinancialResultCheckReport:
        """Check the pilot universe, reusing latest-quarter snapshots younger than the cache window."""
        if self.historical_repository is None:
            raise MarketRuntimeError("PostgreSQL historical storage is not configured")
        instruments = self._resolved_instruments(limit)
        limiter = RequestRateLimiter(
            self.settings.qfae_market_request_rate_per_second,
            self.settings.qfae_market_request_rate_per_minute,
        )
        items: list[FinancialResultAvailability] = []
        with UpstoxMarketDataClient(self._require_access_token(), limiter) as client:
            for instrument in instruments:
                try:
                    item, _ = self._sync_financial_result(client, instrument)
                except Exception as exc:
                    item = FinancialResultAvailability(
                        instrument_key=instrument["instrument_key"],
                        symbol=instrument["symbol"],
                        isin=instrument.get("isin"),
                        state="failed",
                        reason=f"provider_check_failed:{type(exc).__name__}",
                    )
                items.append(item)
        return FinancialResultCheckReport(
            generated_at=datetime.now(UTC),
            cache_days=self.settings.qfae_financial_results_cache_days,
            total=len(items),
            fetched=sum(item.state == "fetched" for item in items),
            reused=sum(item.state == "reused" for item in items),
            unavailable=sum(item.state == "unavailable" for item in items),
            failed=sum(item.state == "failed" for item in items),
            items=items,
        )

    def get_financial_metrics(
        self,
        *,
        instrument_key: str | None = None,
        limit: int = 500,
        latest_only: bool = False,
    ) -> list[FinancialMetricSnapshot]:
        if self.historical_repository is None:
            raise MarketRuntimeError("PostgreSQL historical storage is not configured")
        try:
            snapshots = self.historical_repository.get_financial_metric_snapshots(
                instrument_key=instrument_key,
                limit=limit,
            )
            if not latest_only:
                return snapshots
            latest_by_instrument: dict[str, FinancialMetricSnapshot] = {}
            for snapshot in snapshots:
                latest_by_instrument.setdefault(snapshot.instrument_key, snapshot)
            return sorted(latest_by_instrument.values(), key=lambda item: item.symbol)
        except Exception as exc:
            raise MarketRuntimeError("Financial metric snapshots are unavailable") from exc

    def get_flow_confirmations(self, limit: int | None = None) -> list[FlowLiquidityConfirmation]:
        """Return current-session volume and executable-liquidity confirmation."""
        self._require_state_store()
        instruments = self._resolved_instruments(limit)
        features = self.state_store.get_features()
        return [
            self._build_flow_confirmation(features[instrument["instrument_key"]])
            for instrument in instruments
            if instrument["instrument_key"] in features
        ]

    def _build_flow_confirmation(
        self,
        feature: StockFeatureSnapshot,
    ) -> FlowLiquidityConfirmation:
        result = build_flow_liquidity_confirmation(
            feature,
            active_rvol=self.settings.qfae_confirmation_active_rvol,
            strong_rvol=self.settings.qfae_confirmation_strong_rvol,
            active_acceleration=self.settings.qfae_confirmation_active_acceleration,
            strong_acceleration=self.settings.qfae_confirmation_strong_acceleration,
        )
        now = datetime.now(UTC)
        current = (
            feature.candle_timestamp.astimezone(INDIA_TIMEZONE).date()
            == now.astimezone(INDIA_TIMEZONE).date()
            and -5
            <= (now - feature.as_of).total_seconds()
            <= self.settings.qfae_market_snapshot_interval_seconds * 2
        )
        if current:
            return result
        return result.model_copy(
            update={
                "data_quality": "stale",
                "confirmation": "insufficient",
                "evidence": [],
                "cautions": ["intraday_evidence_stale"],
            }
        )

    def get_reconciliations(self, session_date: date) -> list[DailyReconciliationRecord]:
        if self.historical_repository is None:
            raise MarketRuntimeError("PostgreSQL historical storage is not configured")
        try:
            return self.historical_repository.get_reconciliations(session_date)
        except Exception as exc:
            raise MarketRuntimeError("Daily reconciliation records are unavailable") from exc

    def start_bootstrap(self, limit: int | None = None) -> dict[str, Any]:
        self._require_access_token()
        self._require_state_store()
        instruments = self._resolved_instruments(limit)
        with self._lock:
            if self._bootstrap_thread and self._bootstrap_thread.is_alive():
                raise MarketRuntimeError("Pre-market bootstrap is already running")
            if self._reconciliation_thread and self._reconciliation_thread.is_alive():
                raise MarketRuntimeError("After-market reconciliation is running")
            self._bootstrap = {
                "state": "running",
                "total": len(instruments),
                "processed": 0,
                "history_loaded": 0,
                "minute_history_persisted": 0,
                "minute_profiles_built": 0,
                "daily_history_loaded": 0,
                "daily_history_persisted": 0,
                "benchmark_daily_loaded": 0,
                "sectors_loaded": 0,
                "corporate_actions_synced": 0,
                "corporate_actions_stored": 0,
                "corporate_actions_assessed": 0,
                "corporate_adjustments_built": 0,
                "corporate_documents_stored": 0,
                "corporate_financial_contexts": 0,
                "financial_results_reused": 0,
                "corporate_ai_analyzed": 0,
                "corporate_outcomes_evaluated": 0,
                "errors": 0,
                "started_at": datetime.now(UTC).isoformat(),
                "finished_at": None,
                "recent_errors": [],
            }
            self._bootstrap_thread = threading.Thread(
                target=self._run_bootstrap,
                args=(instruments,),
                name="qfae-pre-market-bootstrap",
                daemon=True,
            )
            self._bootstrap_thread.start()
            return dict(self._bootstrap)

    def start_reconciliation(self, session_date: date | None = None) -> dict[str, Any]:
        """Start manual official daily-candle reconciliation after market close."""
        self._require_access_token()
        self._require_state_store()
        repository = self.historical_repository
        if repository is None or not repository.ping():
            raise MarketRuntimeError("PostgreSQL historical storage is unavailable")
        now = datetime.now(INDIA_TIMEZONE)
        session_date = session_date or now.date()
        if session_date > now.date():
            raise MarketRuntimeError("A future market session cannot be reconciled")
        if session_date == now.date() and now.time() < NSE_MARKET_CLOSE:
            raise MarketRuntimeError("Today's daily candle can be reconciled only after 3:30 PM IST")
        equities = self._resolved_instruments(None)
        instruments = list(equities)
        instruments.extend(
            {
                "instrument_key": key,
                "symbol": MARKET_CONTEXT_SYMBOLS[key],
                "isin": "",
                "company_name": MARKET_CONTEXT_SYMBOLS[key],
            }
            for key in MARKET_CONTEXT_KEYS
        )
        with self._lock:
            if self._reconciliation_thread and self._reconciliation_thread.is_alive():
                raise MarketRuntimeError("After-market reconciliation is already running")
            if self._bootstrap_thread and self._bootstrap_thread.is_alive():
                raise MarketRuntimeError("Pre-market bootstrap is running")
            self._reconciliation = {
                "state": "running",
                "session_date": session_date.isoformat(),
                "total": len(instruments),
                "processed": 0,
                "matched": 0,
                "with_differences": 0,
                "official_only": 0,
                "missing": 0,
                "errors": 0,
                "started_at": datetime.now(UTC).isoformat(),
                "finished_at": None,
                "recent_errors": [],
            }
            self._reconciliation_thread = threading.Thread(
                target=self._run_reconciliation,
                args=(session_date, instruments, {item["instrument_key"] for item in equities}),
                name="qfae-after-market-reconciliation",
                daemon=True,
            )
            self._reconciliation_thread.start()
            return dict(self._reconciliation)

    def _run_reconciliation(
        self,
        session_date: date,
        instruments: list[dict[str, str]],
        equity_keys: set[str],
    ) -> None:
        limiter = RequestRateLimiter(
            self.settings.qfae_market_request_rate_per_second,
            self.settings.qfae_market_request_rate_per_minute,
        )
        repository = self.historical_repository
        assert repository is not None
        try:
            with UpstoxMarketDataClient(self._require_access_token(), limiter) as client:
                for instrument in instruments:
                    result_status: str | None = None
                    errors: list[str] = []
                    try:
                        daily_candles = client.fetch_daily_history(
                            instrument["instrument_key"],
                            5,
                            as_of=session_date,
                            from_date=session_date - timedelta(days=4),
                        )
                        official = next(
                            (
                                candle
                                for candle in reversed(daily_candles)
                                if candle.timestamp.astimezone(INDIA_TIMEZONE).date() == session_date
                            ),
                            None,
                        )
                        if official is None:
                            result_status = "missing"
                            errors.append(f"{instrument['symbol']}: official daily candle unavailable")
                        else:
                            minute_candles = repository.get_session_candles(
                                instrument["instrument_key"],
                                "1minute",
                                session_date,
                            )
                            result = reconcile_session(
                                official,
                                minute_candles,
                                symbol=instrument["symbol"],
                                reconciled_at=datetime.now(UTC),
                            )
                            repository.upsert_candles([official])
                            repository.save_reconciliation(result)
                            repository.evaluate_evidence_outcomes(
                                instrument["instrument_key"],
                                session_date,
                                eod_close=official.close,
                            )
                            self.state_store.save_daily_candles([official])
                            result_status = result.status
                            if instrument["instrument_key"] in equity_keys:
                                repository.refresh_minute_profiles(instrument["instrument_key"])
                    except Exception as exc:
                        errors.append(f"{instrument['symbol']}: reconciliation: {exc}")
                    with self._lock:
                        self._reconciliation["processed"] += 1
                        if result_status == "matched":
                            self._reconciliation["matched"] += 1
                        elif result_status == "reconciled_with_differences":
                            self._reconciliation["with_differences"] += 1
                        elif result_status == "official_only":
                            self._reconciliation["official_only"] += 1
                        elif result_status == "missing":
                            self._reconciliation["missing"] += 1
                        self._reconciliation["errors"] += len(errors)
                        if errors:
                            self._reconciliation["recent_errors"] = (
                                self._reconciliation["recent_errors"] + errors
                            )[-25:]
            reconciliation_time = datetime.combine(
                session_date,
                datetime_time(hour=16),
                tzinfo=INDIA_TIMEZONE,
            ).astimezone(UTC)
            self._calculate_daily_regimes(reconciliation_time, include_provisional=False)
            with self._lock:
                self._reconciliation["state"] = "completed"
        except Exception as exc:
            logger.exception("After-market reconciliation stopped unexpectedly")
            with self._lock:
                self._reconciliation["state"] = "failed"
                self._reconciliation["errors"] += 1
                self._reconciliation["recent_errors"] = (
                    self._reconciliation["recent_errors"] + [f"reconciliation: {exc}"]
                )[-25:]
        finally:
            with self._lock:
                self._reconciliation["finished_at"] = datetime.now(UTC).isoformat()

    def _run_bootstrap(self, instruments: list[dict[str, str]]) -> None:
        limiter = RequestRateLimiter(
            self.settings.qfae_market_request_rate_per_second,
            self.settings.qfae_market_request_rate_per_minute,
        )
        try:
            with UpstoxMarketDataClient(self._require_access_token(), limiter) as client:
                for instrument in instruments:
                    errors: list[str] = []
                    daily_history_loaded = False
                    sector_loaded = False
                    corporate_actions_synced = False
                    corporate_actions_stored = 0
                    corporate_actions_assessed = 0
                    history_loaded, minute_persisted, profile_built, minute_errors = (
                        self._prepare_minute_history(client, instrument["instrument_key"])
                    )
                    errors.extend(f"{instrument['symbol']}: {error}" for error in minute_errors)

                    daily_history_loaded, daily_history_persisted, daily_errors = (
                        self._prepare_daily_history(client, instrument["instrument_key"])
                    )
                    errors.extend(f"{instrument['symbol']}: {error}" for error in daily_errors)

                    isin = instrument.get("isin")
                    if isin:
                        try:
                            sector = client.fetch_sector(isin)
                            if sector:
                                self.state_store.save_sector(instrument["instrument_key"], sector)
                                sector_loaded = True
                        except Exception as exc:
                            errors.append(f"{instrument['symbol']}: sector: {exc}")
                        if repository := self.historical_repository:
                            try:
                                actions = client.fetch_corporate_actions(
                                    isin,
                                    instrument["instrument_key"],
                                    instrument["symbol"],
                                )
                                corporate_actions_stored = repository.upsert_corporate_actions(
                                    isin,
                                    instrument["instrument_key"],
                                    actions,
                                )
                                assessments: list[CorporateActionAssessment] = []
                                for action in actions:
                                    reference_date = (
                                        action.announcement_date or action.ex_date or action.record_date
                                    )
                                    reference = repository.get_reference_daily_close(
                                        action.instrument_key,
                                        reference_date,
                                    )
                                    assessments.append(
                                        assess_corporate_action(
                                            action,
                                            reference_price=reference[0] if reference else None,
                                            reference_price_date=reference[1] if reference else None,
                                        )
                                    )
                                corporate_actions_assessed = (
                                    repository.upsert_corporate_action_assessments(assessments)
                                )
                                corporate_actions_synced = True
                            except Exception as exc:
                                errors.append(f"{instrument['symbol']}: corporate actions: {exc}")

                    with self._lock:
                        self._bootstrap["processed"] += 1
                        self._bootstrap["history_loaded"] += int(history_loaded)
                        self._bootstrap["minute_history_persisted"] += int(minute_persisted)
                        self._bootstrap["minute_profiles_built"] += int(profile_built)
                        self._bootstrap["daily_history_loaded"] += int(daily_history_loaded)
                        self._bootstrap["daily_history_persisted"] += int(daily_history_persisted)
                        self._bootstrap["sectors_loaded"] += int(sector_loaded)
                        self._bootstrap["corporate_actions_synced"] += int(corporate_actions_synced)
                        self._bootstrap["corporate_actions_stored"] += corporate_actions_stored
                        self._bootstrap["corporate_actions_assessed"] += corporate_actions_assessed
                        self._bootstrap["errors"] += len(errors)
                        if errors:
                            self._bootstrap["recent_errors"] = (
                                self._bootstrap["recent_errors"] + errors
                            )[-25:]
                benchmark_keys = (NIFTY_50_KEY, *SECTOR_INDEX_SYMBOLS.keys())
                for instrument_key in dict.fromkeys(benchmark_keys):
                    loaded, _, errors = self._prepare_daily_history(client, instrument_key)
                    if loaded:
                        with self._lock:
                            self._bootstrap["benchmark_daily_loaded"] += 1
                    if errors:
                        label = MARKET_CONTEXT_SYMBOLS.get(instrument_key, instrument_key)
                        with self._lock:
                            self._bootstrap["errors"] += len(errors)
                            self._bootstrap["recent_errors"] = (
                                self._bootstrap["recent_errors"]
                                + [f"{label}: {error}" for error in errors]
                            )[-25:]
                enrichment, enrichment_errors = self._enrich_corporate_actions(client, instruments)
                with self._lock:
                    for key, value in enrichment.items():
                        self._bootstrap[key] += value
                    self._bootstrap["errors"] += len(enrichment_errors)
                    if enrichment_errors:
                        self._bootstrap["recent_errors"] = (
                            self._bootstrap["recent_errors"] + enrichment_errors
                        )[-25:]
            self._calculate_daily_regimes(datetime.now(UTC))
            with self._lock:
                self._bootstrap["state"] = "completed"
        except Exception as exc:
            logger.exception("Pre-market bootstrap stopped unexpectedly")
            with self._lock:
                self._bootstrap["state"] = "failed"
                self._bootstrap["recent_errors"] = (
                    self._bootstrap["recent_errors"] + [f"bootstrap: {exc}"]
                )[-25:]
                self._bootstrap["errors"] += 1
        finally:
            with self._lock:
                self._bootstrap["finished_at"] = datetime.now(UTC).isoformat()

    def _enrich_corporate_actions(
        self,
        client: UpstoxMarketDataClient,
        instruments: list[dict[str, str]],
    ) -> tuple[dict[str, int], list[str]]:
        """Build optional event enrichment after stock and benchmark history are durable."""
        counters = {
            "corporate_adjustments_built": 0,
            "corporate_documents_stored": 0,
            "corporate_financial_contexts": 0,
            "financial_results_reused": 0,
            "corporate_ai_analyzed": 0,
            "corporate_outcomes_evaluated": 0,
        }
        repository = self.historical_repository
        if repository is None:
            return counters, []
        errors: list[str] = []
        today = datetime.now(INDIA_TIMEZONE).date()
        cutoff = today - timedelta(days=self.settings.qfae_corporate_action_lookback_days)
        benchmark = repository.get_candles(NIFTY_50_KEY, "day", 1000)
        nse_client: NseAnnouncementClient | None = None
        ai_scorer: CorporateActionAIScorer | None = None
        if self.settings.qfae_corporate_documents_enabled:
            try:
                nse_client = NseAnnouncementClient()
            except Exception as exc:
                errors.append(f"NSE documents unavailable: {type(exc).__name__}")
        if (
            self.settings.qfae_corporate_action_ai_enabled
            and self.settings.openai_api_key
            and self.settings.qfae_ai_model
        ):
            ai_scorer = CorporateActionAIScorer(
                self.settings.openai_api_key,
                self.settings.qfae_ai_model,
            )
        try:
            for instrument in instruments:
                key = instrument["instrument_key"]
                symbol = instrument["symbol"]
                isin = instrument.get("isin")
                try:
                    actions = repository.get_corporate_actions(instrument_key=key, limit=5000)
                    assessments = repository.get_corporate_action_assessments(
                        instrument_key=key, limit=5000
                    )
                    assessment_by_id = {item.event_id: item for item in assessments}
                    adjustments = []
                    for action in actions:
                        effective_date = action.ex_date or action.record_date
                        reference = repository.get_reference_daily_close(key, effective_date)
                        adjustments.append(
                            build_adjustment(
                                action,
                                reference_close=reference[0] if reference else None,
                            )
                        )
                    counters["corporate_adjustments_built"] += (
                        repository.upsert_corporate_action_adjustments(adjustments)
                    )

                    financial_context = None
                    if isin:
                        try:
                            financial_status, financial_context = self._sync_financial_result(
                                client, instrument
                            )
                            counters["corporate_financial_contexts"] += int(
                                financial_status.state == "fetched"
                            )
                            counters["financial_results_reused"] += int(
                                financial_status.state == "reused"
                            )
                        except Exception as exc:
                            errors.append(f"{symbol}: financial context: {type(exc).__name__}")

                    if nse_client is not None and actions:
                        try:
                            documents = nse_client.fetch(
                                key,
                                symbol,
                                actions,
                                from_date=cutoff,
                                to_date=today,
                            )
                            counters["corporate_documents_stored"] += (
                                repository.upsert_corporate_action_documents(documents)
                            )
                        except Exception as exc:
                            errors.append(f"{symbol}: NSE documents: {type(exc).__name__}")
                            nse_client.close()
                            nse_client = None

                    adjusted_rows = repository.get_adjusted_candles(
                        key, interval="day", limit=1000
                    )
                    stock = [
                        Candle(
                            instrument_key=row.instrument_key,
                            timestamp=row.timestamp,
                            interval=row.interval,
                            open=row.adjusted_open,
                            high=row.adjusted_high,
                            low=row.adjusted_low,
                            close=row.adjusted_close,
                            volume=row.adjusted_volume,
                            source="qfae_adjusted",
                        )
                        for row in adjusted_rows
                    ]
                    adjustment_by_id = {item.event_id: item for item in adjustments}
                    outcomes: list[CorporateActionOutcome] = []
                    for action in actions:
                        adjustment = adjustment_by_id.get(action.event_id)
                        event_date = action.ex_date or action.announcement_date or action.record_date
                        if adjustment and adjustment.status == "unavailable" and event_date:
                            outcomes.append(
                                CorporateActionOutcome(
                                    event_id=action.event_id,
                                    instrument_key=key,
                                    event_date=event_date,
                                    outcome_status="unavailable_adjustment",
                                    evaluated_at=datetime.now(UTC),
                                )
                            )
                            continue
                        outcome = evaluate_action_outcome(action, stock, benchmark)
                        if outcome is not None:
                            outcomes.append(outcome)
                    counters["corporate_outcomes_evaluated"] += (
                        repository.upsert_corporate_action_outcomes(outcomes)
                    )

                    analyses: list[CorporateActionAIAnalysis] = []
                    for action in actions:
                        event_date = action.announcement_date or action.ex_date or action.record_date
                        assessment = assessment_by_id.get(action.event_id)
                        if assessment is None or event_date is None or event_date < cutoff:
                            continue
                        documents = repository.get_corporate_action_documents(
                            instrument_key=key, event_id=action.event_id
                        )
                        if ai_scorer is not None:
                            analysis = ai_scorer.analyze(
                                action, assessment, documents, financial_context
                            )
                        else:
                            reason = (
                                "ai_scoring_disabled"
                                if not self.settings.qfae_corporate_action_ai_enabled
                                else "openai_key_or_model_unavailable"
                            )
                            analysis = unavailable_ai_analysis(
                                action.event_id,
                                model=self.settings.qfae_ai_model,
                                reason=reason,
                            )
                        analyses.append(analysis)
                    repository.upsert_corporate_action_ai_analyses(analyses)
                    counters["corporate_ai_analyzed"] += sum(
                        item.status == "complete" for item in analyses
                    )
                    all_analyses = repository.get_corporate_action_ai_analyses(
                        instrument_key=key
                    )
                    self.state_store.save_corporate_action_context(
                        build_corporate_action_context(
                            key,
                            actions,
                            assessments,
                            all_analyses,
                            as_of=datetime.now(UTC),
                        )
                    )
                except Exception as exc:
                    errors.append(f"{symbol}: corporate enrichment: {type(exc).__name__}")
        finally:
            if nse_client is not None:
                nse_client.close()
            if ai_scorer is not None:
                ai_scorer.close()
        return counters, errors

    def _sync_financial_result(
        self,
        client: UpstoxMarketDataClient,
        instrument: dict[str, str],
    ) -> tuple[FinancialResultAvailability, CorporateFinancialContext | None]:
        repository = self.historical_repository
        if repository is None:
            raise MarketRuntimeError("PostgreSQL historical storage is not configured")
        key = instrument["instrument_key"]
        symbol = instrument["symbol"]
        isin = instrument.get("isin")
        if not isin:
            return (
                FinancialResultAvailability(
                    instrument_key=key,
                    symbol=symbol,
                    state="unavailable",
                    reason="isin_unavailable",
                ),
                None,
            )
        now = datetime.now(UTC)
        snapshot = repository.get_latest_financial_result_snapshot(isin=isin)
        if snapshot_is_reusable(
            snapshot,
            now=now,
            cache_days=self.settings.qfae_financial_results_cache_days,
        ):
            context = repository.get_corporate_financial_context(isin)
            if context is None and snapshot is not None:
                context = context_from_financial_snapshot(snapshot)
                repository.upsert_corporate_financial_context(context)
            if snapshot is not None:
                repository.upsert_financial_metric_snapshot(
                    calculate_financial_metrics(snapshot)
                )
            return (
                FinancialResultAvailability(
                    instrument_key=key,
                    symbol=symbol,
                    isin=isin,
                    state="reused",
                    reason="latest_quarter_snapshot_younger_than_cache_window",
                    quarterly_period=snapshot.quarterly_period if snapshot else None,
                    annual_period=snapshot.annual_period if snapshot else None,
                    quarterly_available=bool(snapshot and snapshot.quarterly_available),
                    annual_available=bool(snapshot and snapshot.annual_available),
                    snapshot_at=snapshot.last_seen_at if snapshot else None,
                    cache_fresh=True,
                ),
                context,
            )
        snapshot, context = client.fetch_financial_results(isin, key, symbol)
        repository.upsert_financial_result_snapshot(snapshot)
        repository.upsert_corporate_financial_context(context)
        repository.upsert_financial_metric_snapshot(calculate_financial_metrics(snapshot))
        available = snapshot.quarterly_available or snapshot.annual_available
        return (
            FinancialResultAvailability(
                instrument_key=key,
                symbol=symbol,
                isin=isin,
                state="fetched" if available else "unavailable",
                reason=(
                    "provider_snapshot_stored"
                    if available
                    else "provider_has_no_quarterly_or_annual_results"
                ),
                quarterly_period=snapshot.quarterly_period,
                annual_period=snapshot.annual_period,
                quarterly_available=snapshot.quarterly_available,
                annual_available=snapshot.annual_available,
                snapshot_at=snapshot.last_seen_at,
                cache_fresh=snapshot_is_reusable(
                    snapshot,
                    now=now,
                    cache_days=self.settings.qfae_financial_results_cache_days,
                ),
            ),
            context,
        )

    def _prepare_minute_history(
        self,
        client: UpstoxMarketDataClient,
        instrument_key: str,
    ) -> tuple[bool, bool, bool, list[str]]:
        """Hydrate Redis and refresh bounded minute history and its rolling profile."""
        errors: list[str] = []
        stored: list[Candle] = []
        repository = self.historical_repository
        if repository is not None:
            try:
                stored = repository.get_candles(
                    instrument_key,
                    "1minute",
                    self._history_limit(),
                )
                if stored:
                    self.state_store.save_candles(stored)
            except Exception as exc:
                errors.append(f"minute database read: {exc}")

        from_date = None
        if stored:
            latest_date = stored[-1].timestamp.astimezone(INDIA_TIMEZONE).date()
            from_date = latest_date - timedelta(days=2)

        downloaded: list[Candle] = []
        try:
            downloaded = client.fetch_recent_minute_history(
                instrument_key,
                self.settings.qfae_market_history_days,
                from_date=from_date,
            )
            self.state_store.save_candles(downloaded)
        except Exception as exc:
            errors.append(f"minute history: {exc}")

        persisted = bool(stored)
        profile_built = False
        if repository is not None:
            try:
                if downloaded:
                    repository.upsert_candles(downloaded)
                    persisted = True
                cutoff = datetime.now(INDIA_TIMEZONE) - timedelta(
                    days=self.settings.qfae_minute_history_retention_days
                )
                repository.prune_minute_candles(cutoff, [instrument_key])
                profile_built = repository.refresh_minute_profiles(
                    instrument_key,
                    exclude_session_date=datetime.now(INDIA_TIMEZONE).date(),
                ) > 0
            except Exception as exc:
                errors.append(f"minute database/profile write: {exc}")
        return bool(stored or downloaded), persisted, profile_built, errors

    def _prepare_daily_history(
        self,
        client: UpstoxMarketDataClient,
        instrument_key: str,
    ) -> tuple[bool, bool, list[str]]:
        """Hydrate Redis, incrementally refresh Upstox, and durably upsert daily candles."""
        errors: list[str] = []
        stored: list[Candle] = []
        repository = self.historical_repository
        if repository is not None:
            try:
                stored = repository.get_candles(
                    instrument_key,
                    "day",
                    self.settings.qfae_daily_history_sessions,
                )
                if stored:
                    self.state_store.save_daily_candles(stored)
            except Exception as exc:
                errors.append(f"database read: {exc}")

        from_date = None
        if stored:
            latest_date = stored[-1].timestamp.astimezone(INDIA_TIMEZONE).date()
            from_date = latest_date - timedelta(days=5)

        downloaded: list[Candle] = []
        try:
            downloaded = client.fetch_daily_history(
                instrument_key,
                self.settings.qfae_daily_history_sessions,
                from_date=from_date,
            )
            self.state_store.save_daily_candles(downloaded)
        except Exception as exc:
            errors.append(f"daily history: {exc}")

        persisted = bool(stored)
        if repository is not None and downloaded:
            try:
                repository.upsert_candles(downloaded)
                persisted = True
            except Exception as exc:
                errors.append(f"database write: {exc}")
        return bool(stored or downloaded), persisted, errors

    def start_live(self, limit: int | None = None) -> dict[str, Any]:
        now = datetime.now(INDIA_TIMEZONE)
        market_close = nse_market_close_at(now)
        if now >= market_close:
            raise MarketRuntimeError("The NSE cash market is closed after 3:30 PM IST")
        token = self._require_access_token()
        self._require_state_store()
        instruments = self._resolved_instruments(limit)
        symbols = {item["instrument_key"]: item["symbol"] for item in instruments}
        symbols.update(MARKET_CONTEXT_SYMBOLS)
        instrument_keys = list(dict.fromkeys([*symbols.keys()]))
        if len(instrument_keys) > MAX_FULL_FEED_INSTRUMENTS:
            raise MarketRuntimeError("A Full-feed connection supports at most 2,000 instrument keys")
        with self._lock:
            if self._stream_thread and self._stream_thread.is_alive():
                raise MarketRuntimeError("Live market stream is already running")
            self._symbols = symbols
            self._live = {
                "state": "connecting",
                "connected": False,
                "subscribed": len(instrument_keys),
                "last_message_at": None,
                "last_context_at": None,
                "scheduled_stop_at": market_close.isoformat(),
                "error": None,
            }
            configuration = upstox_client.Configuration()
            configuration.access_token = token
            api_client = upstox_client.ApiClient(configuration)
            streamer = upstox_client.MarketDataStreamerV3(api_client, instrument_keys, "full")
            streamer.auto_reconnect(True, 10, 12)
            streamer.on("open", self._on_stream_open)
            streamer.on("message", self._on_stream_message)
            streamer.on("error", self._on_stream_error)
            streamer.on("close", self._on_stream_close)
            streamer.on("reconnecting", self._on_stream_reconnecting)
            streamer.on("autoReconnectStopped", self._on_reconnect_stopped)
            self._streamer = streamer
            self._stream_thread = threading.Thread(
                target=self._connect_stream,
                name="qfae-upstox-market-stream",
                daemon=True,
            )
            self._stream_thread.start()
            self._schedule_market_close(market_close, now)
            return dict(self._live)

    def stop_live(self, *, reason: str = "manual") -> dict[str, Any]:
        with self._lock:
            streamer = self._streamer
            market_close_timer = self._market_close_timer
            self._market_close_timer = None
        if market_close_timer is not None:
            market_close_timer.cancel()
        if streamer is not None:
            try:
                streamer.disconnect()
            except Exception as exc:
                raise MarketRuntimeError(f"Could not stop the live market stream: {exc}") from exc
        with self._lock:
            self._live["state"] = "market_closed" if reason == "market_close" else "stopped"
            self._live["connected"] = False
            self._live["subscribed"] = 0
            self._live["scheduled_stop_at"] = None
            self._streamer = None
            return dict(self._live)

    def _schedule_market_close(self, market_close: datetime, now: datetime) -> None:
        delay_seconds = max(0.0, (market_close - now).total_seconds())
        timer = threading.Timer(delay_seconds, self._stop_at_market_close)
        timer.name = "qfae-market-close"
        timer.daemon = True
        self._market_close_timer = timer
        timer.start()

    def _stop_at_market_close(self) -> None:
        try:
            self.stop_live(reason="market_close")
            logger.info("Upstox live feed stopped at the NSE cash-market close")
        except Exception:
            logger.exception("Could not stop the Upstox live feed at market close")

    def _connect_stream(self) -> None:
        try:
            self._streamer.connect()
        except Exception as exc:
            self._on_stream_error(exc)

    def _on_stream_open(self) -> None:
        with self._lock:
            self._live["state"] = "connected"
            self._live["connected"] = True
            self._live["error"] = None

    def _on_stream_message(self, message: dict[str, Any]) -> None:
        try:
            snapshots = normalize_feed_message(message, self._symbols)
            for snapshot in snapshots:
                if snapshot.current_candle:
                    self.state_store.save_candles([snapshot.current_candle])
                self.state_store.save_snapshot(snapshot)
            received_at = datetime.now(UTC)
            with self._lock:
                self._live["last_message_at"] = received_at.isoformat()
            provider_time = message.get("currentTs")
            try:
                bucket = int(provider_time) // (self.settings.qfae_market_snapshot_interval_seconds * 1000)
            except (TypeError, ValueError):
                bucket = int(received_at.timestamp()) // self.settings.qfae_market_snapshot_interval_seconds
            self._queue_minute_context(bucket)
        except Exception as exc:
            logger.exception("Could not normalize an Upstox live-feed message")
            self._on_stream_error(exc)

    def _queue_minute_context(self, bucket: int) -> None:
        with self._lock:
            if self._last_context_bucket == bucket:
                return
            self._last_context_bucket = bucket
            if self._context_timer:
                self._context_timer.cancel()
            self._context_timer = threading.Timer(2.0, self._calculate_minute_context)
            self._context_timer.daemon = True
            self._context_timer.start()

    def _calculate_minute_context(self) -> None:
        try:
            as_of = datetime.now(UTC)
            all_snapshots = self.state_store.get_snapshots()
            snapshots_by_key = {snapshot.instrument_key: snapshot for snapshot in all_snapshots}
            feature_snapshots_by_key = dict(snapshots_by_key)
            for instrument_key, snapshot in snapshots_by_key.items():
                if instrument_key.startswith("NSE_EQ|"):
                    continue
                history = self.state_store.get_candles(instrument_key, limit=5)
                completed = self._latest_completed_candle(snapshot, history)
                feature_snapshots_by_key[instrument_key] = snapshot.model_copy(
                    update={"ltp": completed.close if completed else None}
                )
            active_equity_keys = {
                instrument["instrument_key"]
                for instrument in self._resolved_instruments(None)
            }
            selected_snapshots = [
                snapshot
                for snapshot in all_snapshots
                if not snapshot.instrument_key.startswith("NSE_EQ|")
                or snapshot.instrument_key in active_equity_keys
            ]
            sectors = self.state_store.get_sectors()
            enriched: list[LiveSnapshot] = []
            calculated_features: list[StockFeatureSnapshot] = []
            completed_for_persistence: dict[tuple[str, datetime], Candle] = {}
            for snapshot in selected_snapshots:
                if not snapshot.instrument_key.startswith("NSE_EQ|"):
                    enriched.append(snapshot)
                    continue
                history = self.state_store.get_candles(
                    snapshot.instrument_key,
                    limit=self._history_limit(),
                )
                completed = self._latest_completed_candle(snapshot, history)
                relative_volume = self._profile_relative_volume(completed) if completed else None
                if completed and relative_volume is None:
                    relative_volume = calculate_relative_volume(completed, history)
                relative_volume_metric = None
                if completed and relative_volume is not None:
                    relative_volume_metric = RelativeVolumeMetric(
                        instrument_key=snapshot.instrument_key,
                        relative_volume=relative_volume,
                        candle_timestamp=completed.timestamp,
                        calculated_at=as_of,
                    )
                    self.state_store.save_relative_volume(relative_volume_metric)
                    snapshot = snapshot.model_copy(
                        update={
                            "completed_candle_relative_volume": relative_volume,
                            "completed_candle_timestamp": completed.timestamp,
                        }
                    )
                else:
                    self.state_store.delete_relative_volume(snapshot.instrument_key)
                if completed:
                    self._collect_unpersisted_minutes(
                        snapshot,
                        history,
                        completed,
                        completed_for_persistence,
                    )
                    try:
                        calculated_features.append(
                            build_stock_features(
                                snapshot,
                                completed,
                                history,
                                feature_snapshots_by_key,
                                sectors.get(snapshot.instrument_key),
                                relative_volume_metric,
                                as_of=as_of,
                                max_spread_bps=self.settings.qfae_feature_max_spread_bps,
                                min_traded_value_inr=self.settings.qfae_feature_min_traded_value_inr,
                            )
                        )
                    except Exception:
                        logger.exception("Feature calculation failed for %s", snapshot.symbol)
                        self.state_store.delete_features(snapshot.instrument_key)
                else:
                    self.state_store.delete_features(snapshot.instrument_key)
                enriched.append(snapshot)

            if self.historical_repository is not None and completed_for_persistence:
                try:
                    self.historical_repository.upsert_candles(completed_for_persistence.values())
                    for instrument_key, timestamp in completed_for_persistence:
                        previous = self._persisted_minute_watermarks.get(instrument_key)
                        if previous is None or timestamp > previous:
                            self._persisted_minute_watermarks[instrument_key] = timestamp
                except Exception:
                    logger.exception("Could not persist completed live minute candles")

            ranked_returns = sorted(
                feature.relative_strength.session_return_percent
                for feature in calculated_features
                if feature.relative_strength.session_return_percent is not None
            )
            for feature in calculated_features:
                session_return = feature.relative_strength.session_return_percent
                percentile = None
                if session_return is not None and ranked_returns:
                    percentile = round(
                        sum(value <= session_return for value in ranked_returns) / len(ranked_returns) * 100,
                        2,
                    )
                feature = feature.model_copy(
                    update={
                        "relative_strength": feature.relative_strength.model_copy(
                            update={"universe_percentile": percentile}
                        )
                    }
                )
                self.state_store.save_features(feature)
            self._calculate_daily_regimes(as_of)
            context = build_market_context(
                enriched,
                sectors,
                as_of=as_of,
                cadence_seconds=self.settings.qfae_market_snapshot_interval_seconds,
            )
            self.state_store.save_context(context)
            context_history = self.state_store.get_context_history(limit=5)
            market_regime = build_market_regime(context, context_history[:-1])
            self.state_store.save_market_regime(market_regime)
            self._record_minute_evidence(
                list(self.state_store.get_features().values()),
                snapshots_by_key,
                context,
                market_regime,
                as_of,
            )
            with self._lock:
                self._live["last_context_at"] = context.as_of.isoformat()
        except Exception as exc:
            logger.exception("Minute-level market context calculation failed")
            self._on_stream_error(exc)

    def _record_minute_evidence(
        self,
        features: list[StockFeatureSnapshot],
        snapshots: dict[str, LiveSnapshot],
        context: Any,
        market_regime: MarketRegimeSnapshot,
        as_of: datetime,
    ) -> None:
        regimes = self.state_store.get_daily_regimes()
        previous_signals = self.state_store.get_signals()
        corporate_contexts = self.state_store.get_corporate_action_contexts()
        repository = self.historical_repository
        financial_metrics = self._latest_financial_metrics_by_instrument()
        for feature in features:
            try:
                if feature.as_of != as_of:
                    continue
                flow = self._build_flow_confirmation(feature)
                evidence = build_opportunity_evidence(
                    feature,
                    regimes.get(feature.instrument_key),
                    context,
                    as_of=as_of,
                    freshness_seconds=self.settings.qfae_market_snapshot_interval_seconds * 2,
                    flow_liquidity=flow,
                )
                prior = [
                    item
                    for item in self.state_store.get_evidence_history(feature.instrument_key, 3)
                    if item.as_of < evidence.as_of
                ][-2:]
                signal = build_signal_persistence(
                    evidence,
                    prior,
                    previous_signals.get(feature.instrument_key),
                    as_of=as_of,
                )
                risk = build_risk_assessment(
                    feature,
                    snapshots.get(feature.instrument_key),
                    as_of=as_of,
                    freshness_seconds=self.settings.qfae_market_snapshot_interval_seconds * 2,
                    reference_order_value_inr=self.settings.qfae_risk_reference_order_value_inr,
                    max_slippage_bps=self.settings.qfae_risk_max_slippage_bps,
                    min_circuit_distance_percent=self.settings.qfae_risk_min_circuit_distance_percent,
                    max_gap_atr=self.settings.qfae_risk_max_gap_atr,
                    risk_capital_inr=self.settings.qfae_risk_capital_inr,
                    recent_spreads_bps=[
                        value
                        for item in [*prior, evidence]
                        if (value := item.flow_liquidity.spread_bps) is not None
                    ],
                    recent_depth_imbalances=[
                        value
                        for item in [*prior, evidence]
                        if (value := item.flow_liquidity.depth_imbalance) is not None
                    ],
                    max_spread_range_bps=self.settings.qfae_risk_max_spread_range_bps,
                )
                evidence = evidence.model_copy(
                    update={
                        "signal_persistence": signal,
                        "risk_assessment": risk,
                        "market_regime": market_regime,
                        "corporate_action_context": corporate_contexts.get(feature.instrument_key),
                    }
                )
                evidence = evidence.model_copy(
                    update={
                        "opportunity_score": build_opportunity_score(
                            evidence,
                            financial_metrics.get(feature.instrument_key),
                            weights=self._opportunity_scoring_weights(),
                        )
                    }
                )
                self.state_store.save_signal(signal)
                self.state_store.save_risk_assessment(risk)
                self.state_store.save_evidence(evidence)
                if repository is None:
                    continue
                candles = self.state_store.get_candles(feature.instrument_key, limit=5)
                reference = next(
                    (item.close for item in reversed(candles) if item.timestamp == feature.candle_timestamp),
                    None,
                )
                if reference is None or reference <= 0:
                    continue
                observation = EvidenceOutcomeObservation(
                    instrument_key=feature.instrument_key,
                    symbol=feature.symbol,
                    sector=feature.sector,
                    candle_timestamp=feature.candle_timestamp,
                    observed_at=as_of,
                    reference_price=reference,
                    confluence=evidence.confluence,
                    signal_state=signal.state,
                    data_quality=evidence.data_quality,
                    evidence_payload=evidence.model_dump(mode="json"),
                    risk_payload=risk.model_dump(mode="json"),
                    market_regime_payload=market_regime.model_dump(mode="json"),
                )
                repository.save_evidence_observation(observation)
                repository.evaluate_evidence_outcomes(
                    feature.instrument_key,
                    feature.candle_timestamp.astimezone(INDIA_TIMEZONE).date(),
                )
            except Exception:
                logger.exception("Could not record minute evidence for %s", feature.symbol)

    def _opportunity_scoring_weights(self) -> dict[str, float]:
        return {
            "price_trend": self.settings.qfae_score_weight_price_trend,
            "participation": self.settings.qfae_score_weight_participation,
            "market_sector": self.settings.qfae_score_weight_market_sector,
            "liquidity_execution": self.settings.qfae_score_weight_liquidity_execution,
            "fundamental": self.settings.qfae_score_weight_fundamental,
            "catalyst": self.settings.qfae_score_weight_catalyst,
        }

    def _latest_financial_metrics_by_instrument(self) -> dict[str, FinancialMetricSnapshot]:
        repository = self.historical_repository
        if repository is None:
            return {}
        try:
            result: dict[str, FinancialMetricSnapshot] = {}
            for item in repository.get_financial_metric_snapshots(limit=5000):
                result.setdefault(item.instrument_key, item)
            return result
        except Exception:
            logger.exception("Could not load financial metrics for opportunity scoring")
            return {}

    def _profile_relative_volume(self, candle: Candle) -> float | None:
        repository = self.historical_repository
        if repository is None:
            return None
        try:
            profile = repository.get_minute_profile(candle.instrument_key, candle.timestamp)
        except Exception:
            logger.exception("Could not read minute profile for %s", candle.instrument_key)
            return None
        if (
            profile is None
            or profile.sample_count < self.settings.qfae_minute_profile_min_samples
            or profile.median_volume <= 0
        ):
            return None
        return round(candle.volume / profile.median_volume, 4)

    def _collect_unpersisted_minutes(
        self,
        snapshot: LiveSnapshot,
        history: list[Candle],
        completed: Candle,
        target: dict[tuple[str, datetime], Candle],
    ) -> None:
        """Collect every newly completed current-session candle, including outage gaps."""
        repository = self.historical_repository
        if repository is None:
            return
        instrument_key = snapshot.instrument_key
        if instrument_key not in self._persisted_minute_watermarks:
            try:
                self._persisted_minute_watermarks[instrument_key] = (
                    repository.latest_candle_timestamp(instrument_key, "1minute")
                )
            except Exception:
                logger.exception("Could not read minute watermark for %s", instrument_key)
                self._persisted_minute_watermarks[instrument_key] = None
        watermark = self._persisted_minute_watermarks[instrument_key]
        session_date = completed.timestamp.astimezone(INDIA_TIMEZONE).date()
        for candle in history:
            if (
                candle.interval == "1minute"
                and candle.timestamp <= completed.timestamp
                and candle.timestamp.astimezone(INDIA_TIMEZONE).date() == session_date
                and (watermark is None or candle.timestamp > watermark)
            ):
                target[(instrument_key, candle.timestamp)] = candle

    def _calculate_daily_regimes(
        self,
        as_of: datetime,
        *,
        include_provisional: bool = True,
    ) -> None:
        instruments = self._resolved_instruments(None)
        sectors = self.state_store.get_sectors()
        snapshots = {
            snapshot.instrument_key: snapshot
            for snapshot in self.state_store.get_snapshots()
        }
        benchmark_keys = tuple(dict.fromkeys((NIFTY_50_KEY, *SECTOR_INDEX_SYMBOLS.keys())))
        benchmark_histories: dict[str, list[Candle]] = {}
        for instrument_key in benchmark_keys:
            history = self.state_store.get_daily_candles(
                instrument_key,
                self.settings.qfae_daily_history_sessions,
            )
            provisional, _ = (
                self._provisional_daily_evidence(
                    instrument_key,
                    snapshots.get(instrument_key),
                    as_of,
                )
                if include_provisional
                else (None, None)
            )
            benchmark_histories[instrument_key] = merge_daily_history(history, provisional)

        for instrument in instruments:
            instrument_key = instrument["instrument_key"]
            history = self.state_store.get_daily_candles(
                instrument_key,
                self.settings.qfae_daily_history_sessions,
            )
            provisional, live_relative_volume = (
                self._provisional_daily_evidence(
                    instrument_key,
                    snapshots.get(instrument_key),
                    as_of,
                )
                if include_provisional
                else (None, None)
            )
            regime = build_daily_regime(
                instrument_key,
                instrument["symbol"],
                sectors.get(instrument_key),
                merge_daily_history(history, provisional),
                benchmark_histories,
                as_of=as_of,
                live_relative_volume=live_relative_volume,
            )
            if regime is not None:
                self.state_store.save_daily_regime(regime)

    def _provisional_daily_evidence(
        self,
        instrument_key: str,
        snapshot: LiveSnapshot | None,
        as_of: datetime,
    ) -> tuple[Candle | None, float | None]:
        if snapshot is None:
            return None, None
        history = self.state_store.get_candles(instrument_key, limit=self._history_limit())
        completed = self._latest_completed_candle(snapshot, history)
        if completed is None:
            return None, None
        session_date = completed.timestamp.astimezone(INDIA_TIMEZONE).date()
        if session_date != as_of.astimezone(INDIA_TIMEZONE).date():
            return None, None
        return (
            aggregate_session_candle(instrument_key, history, completed),
            cumulative_relative_volume(history, completed),
        )

    def _history_limit(self) -> int:
        return min(10_000, (self.settings.qfae_market_history_days + 2) * 400)

    @staticmethod
    def _latest_completed_candle(snapshot: LiveSnapshot, history: list[Any]) -> Any | None:
        if not history or snapshot.current_candle is None:
            return None
        current = snapshot.current_candle
        current_date = current.timestamp.astimezone(INDIA_TIMEZONE).date()
        completed = [
            candle
            for candle in history
            if candle.timestamp < current.timestamp
            and candle.timestamp.astimezone(INDIA_TIMEZONE).date() == current_date
        ]
        return completed[-1] if completed else None

    @staticmethod
    def _previous_session_close(history: list[Candle]) -> float | None:
        if not history:
            return None
        latest_date = history[-1].timestamp.date()
        for candle in reversed(history[:-1]):
            if candle.timestamp.date() != latest_date:
                return candle.close
        return None

    def _on_stream_error(self, error: Any) -> None:
        safe_error = str(error).replace(self._access_token() or "<no-token>", "<redacted>")[:500]
        with self._lock:
            self._live["error"] = safe_error
            if not self._live["connected"]:
                self._live["state"] = "error"

    def _on_stream_close(self, *_: Any) -> None:
        with self._lock:
            self._live["connected"] = False
            if self._live["state"] != "stopped":
                self._live["state"] = "disconnected"

    def _on_stream_reconnecting(self, message: Any) -> None:
        with self._lock:
            self._live["state"] = "reconnecting"
            self._live["connected"] = False
            self._live["error"] = str(message)[:500]

    def _on_reconnect_stopped(self, message: Any) -> None:
        with self._lock:
            self._live["state"] = "reconnect_exhausted"
            self._live["connected"] = False
            self._live["error"] = str(message)[:500]

    def _resolved_instruments(self, limit: int | None) -> list[dict[str, str]]:
        try:
            universe = self.universe_service.load()
        except (FileNotFoundError, ValueError) as exc:
            raise MarketRuntimeError(str(exc)) from exc
        instruments: list[dict[str, str]] = []
        for row in universe.get("instruments", []):
            candidate = row.get("candidate") if isinstance(row, dict) else None
            if row.get("status") != "resolved" or not isinstance(candidate, dict):
                continue
            key = candidate.get("instrument_key")
            symbol = candidate.get("trading_symbol")
            if key and symbol:
                instruments.append(
                    {
                        "instrument_key": str(key),
                        "symbol": str(symbol),
                        "isin": str(candidate.get("isin") or ""),
                        "company_name": str(row.get("requested_name") or candidate.get("name") or symbol),
                    }
                )
        effective_limit = limit if limit is not None else self.settings.qfae_market_pilot_size
        instruments = instruments[:effective_limit]
        if not instruments:
            raise MarketRuntimeError("The approved universe has no resolved instruments")
        return instruments

    def _access_token(self) -> str | None:
        cached = TokenCache(self.settings.upstox_token_cache_path).load()
        return cached["access_token"] if cached else None

    def _require_access_token(self) -> str:
        token = self._access_token()
        if not token:
            raise MarketRuntimeError("A current Upstox login is required")
        return token

    def _require_state_store(self) -> None:
        try:
            if not self.state_store.ping():
                raise MarketRuntimeError("Redis is unavailable")
        except MarketRuntimeError:
            raise
        except Exception as exc:
            raise MarketRuntimeError("Redis is unavailable; start it with docker compose up -d redis") from exc
