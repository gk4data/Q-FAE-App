"""Market-day bootstrap, live-stream, candle, and context endpoints."""

from __future__ import annotations

import asyncio
from datetime import date
from functools import lru_cache
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect, status

from app.core.config import get_settings
from app.db.engine import get_engine
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
    DailyReconciliationRecord,
    DailyRegimeSnapshot,
    EvidenceOutcomeObservation,
    FlowLiquidityConfirmation,
    MarketContext,
    MarketRegimeSnapshot,
    MinuteOfDayProfile,
    OpportunityEvidenceSnapshot,
    RiskAssessment,
    StockFeatureSnapshot,
    WatchlistItem,
)
from app.services.equity_universe import EquityUniverseService
from app.services.market_runtime import MarketRuntime, MarketRuntimeError
from app.services.market_state import RedisMarketStateStore
from app.services.upstox_market import MAX_EQUITY_SUBSCRIPTIONS

router = APIRouter(prefix="/market", tags=["market data"])


@lru_cache
def get_market_runtime() -> MarketRuntime:
    settings = get_settings()
    return MarketRuntime(
        settings=settings,
        state_store=RedisMarketStateStore(
            settings.qfae_redis_url,
            retention_days=settings.qfae_market_history_retention_days,
        ),
        universe_service=EquityUniverseService(
            stock_list_path=settings.qfae_stock_list_path,
            output_path=settings.qfae_equity_universe_path,
        ),
        historical_repository=HistoricalMarketRepository(get_engine()),
    )


def _runtime_action(action: Any) -> dict[str, Any]:
    try:
        return action()
    except MarketRuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/bootstrap", status_code=status.HTTP_202_ACCEPTED)
def start_pre_market_bootstrap(
    limit: Annotated[int | None, Query(ge=1, le=2000)] = None,
) -> dict[str, Any]:
    """Start rate-limited 1-minute history and sector loading in the background."""
    return _runtime_action(lambda: get_market_runtime().start_bootstrap(limit))


@router.post("/live/start", status_code=status.HTTP_202_ACCEPTED)
def start_live_market_stream(
    limit: Annotated[int | None, Query(ge=1, le=MAX_EQUITY_SUBSCRIPTIONS)] = None,
) -> dict[str, Any]:
    """Connect to Upstox Market Data Feed V3 in full mode."""
    return _runtime_action(lambda: get_market_runtime().start_live(limit))


@router.post("/live/stop")
def stop_live_market_stream() -> dict[str, Any]:
    """Disconnect the provider stream without clearing cached market state."""
    return _runtime_action(get_market_runtime().stop_live)


@router.get("/status")
def market_runtime_status() -> dict[str, Any]:
    """Return bootstrap, Redis, connection, and minute-calculation health."""
    return get_market_runtime().status()


@router.get("/watchlist", response_model=list[WatchlistItem])
def get_pilot_watchlist(
    limit: Annotated[int | None, Query(ge=1, le=2000)] = None,
) -> list[WatchlistItem]:
    """Return the configured pilot stocks with their latest cached minute data."""
    try:
        return get_market_runtime().get_watchlist(limit)
    except MarketRuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.get("/candles", response_model=list[Candle])
def get_recent_candles(
    instrument_key: str,
    limit: Annotated[int, Query(ge=1, le=5000)] = 500,
) -> list[Candle]:
    """Return cached one-minute candles in ascending timestamp order."""
    try:
        return get_market_runtime().state_store.get_candles(instrument_key, limit)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis market state is unavailable",
        ) from exc


@router.get("/features", response_model=list[StockFeatureSnapshot])
def get_minute_features(
    limit: Annotated[int | None, Query(ge=1, le=2000)] = None,
) -> list[StockFeatureSnapshot]:
    """Return the latest explainable feature snapshot for each pilot stock."""
    try:
        return get_market_runtime().get_features(limit)
    except MarketRuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.get("/daily-regimes", response_model=list[DailyRegimeSnapshot])
def get_daily_regimes(
    limit: Annotated[int | None, Query(ge=1, le=2000)] = None,
) -> list[DailyRegimeSnapshot]:
    """Return independent multi-horizon trend, structure, participation, and risk evidence."""
    try:
        return get_market_runtime().get_daily_regimes(limit)
    except MarketRuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.get("/minute-profiles", response_model=list[MinuteOfDayProfile])
def get_minute_of_day_profiles(instrument_key: str) -> list[MinuteOfDayProfile]:
    """Return the durable rolling intraday baseline for one instrument."""
    try:
        return get_market_runtime().get_minute_profiles(instrument_key)
    except MarketRuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.get("/evidence", response_model=list[OpportunityEvidenceSnapshot])
def get_opportunity_evidence(
    limit: Annotated[int | None, Query(ge=1, le=2000)] = None,
) -> list[OpportunityEvidenceSnapshot]:
    """Return validated, unweighted confluence across the implemented evidence families."""
    try:
        return get_market_runtime().get_opportunity_evidence(limit)
    except MarketRuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.get("/confirmations", response_model=list[FlowLiquidityConfirmation])
def get_flow_liquidity_confirmations(
    limit: Annotated[int | None, Query(ge=1, le=2000)] = None,
) -> list[FlowLiquidityConfirmation]:
    """Return combined RVOL, acceleration, spread, and liquidity confirmation."""
    try:
        return get_market_runtime().get_flow_confirmations(limit)
    except MarketRuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.get("/risk", response_model=list[RiskAssessment])
def get_risk_assessments(
    limit: Annotated[int | None, Query(ge=1, le=2000)] = None,
) -> list[RiskAssessment]:
    """Return execution-quality and tradability gates for the pilot universe."""
    try:
        return get_market_runtime().get_risk_assessments(limit)
    except MarketRuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.get("/regime", response_model=MarketRegimeSnapshot)
def get_broad_market_regime() -> MarketRegimeSnapshot:
    """Return the latest persistent breadth, VIX and sector-participation regime."""
    try:
        regime = get_market_runtime().get_market_regime()
    except MarketRuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    if regime is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Market regime is not available yet")
    return regime


@router.get("/outcomes", response_model=list[EvidenceOutcomeObservation])
def get_evidence_outcomes(
    session_date: date,
    instrument_key: str | None = None,
) -> list[EvidenceOutcomeObservation]:
    """Return point-in-time evidence and forward returns for one session."""
    try:
        return get_market_runtime().get_evidence_outcomes(session_date, instrument_key)
    except MarketRuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.get("/corporate-actions", response_model=list[CorporateAction])
def get_corporate_actions(
    instrument_key: str | None = None,
    isin: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: Annotated[int, Query(ge=1, le=5000)] = 500,
) -> list[CorporateAction]:
    """Return factual Upstox corporate actions; no sentiment is inferred here."""
    try:
        return get_market_runtime().get_corporate_actions(
            instrument_key=instrument_key,
            isin=isin,
            from_date=from_date,
            to_date=to_date,
            limit=limit,
        )
    except MarketRuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.get("/corporate-action-assessments", response_model=list[CorporateActionAssessment])
def get_corporate_action_assessments(
    instrument_key: str | None = None,
    category: str | None = None,
    direction: str | None = None,
    minimum_materiality: Annotated[float | None, Query(ge=0, le=100)] = None,
    limit: Annotated[int, Query(ge=1, le=5000)] = 500,
) -> list[CorporateActionAssessment]:
    """Return versioned deterministic corporate-action classifications and metrics."""
    try:
        return get_market_runtime().get_corporate_action_assessments(
            instrument_key=instrument_key,
            category=category,
            direction=direction,
            minimum_materiality=minimum_materiality,
            limit=limit,
        )
    except MarketRuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.get("/adjusted-candles", response_model=list[AdjustedCandle])
def get_adjusted_candles(
    instrument_key: str,
    interval: str = "day",
    limit: Annotated[int, Query(ge=1, le=5000)] = 300,
) -> list[AdjustedCandle]:
    """Return a corporate-action-adjusted overlay while preserving raw candles."""
    try:
        return get_market_runtime().get_adjusted_candles(
            instrument_key, interval=interval, limit=limit
        )
    except MarketRuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.get("/corporate-action-documents", response_model=list[CorporateActionDocument])
def get_corporate_action_documents(
    instrument_key: str | None = None,
    event_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=5000)] = 500,
) -> list[CorporateActionDocument]:
    """Return official supporting announcement metadata and source links."""
    try:
        return get_market_runtime().get_corporate_action_documents(
            instrument_key=instrument_key, event_id=event_id, limit=limit
        )
    except MarketRuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.get("/corporate-action-ai", response_model=list[CorporateActionAIAnalysis])
def get_corporate_action_ai(
    instrument_key: str | None = None,
    event_id: str | None = None,
) -> list[CorporateActionAIAnalysis]:
    """Return optional, document-grounded AI interpretations and citation IDs."""
    try:
        return get_market_runtime().get_corporate_action_ai_analyses(
            instrument_key=instrument_key, event_id=event_id
        )
    except MarketRuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.get("/corporate-action-outcomes", response_model=list[CorporateActionOutcome])
def get_corporate_action_outcomes(
    instrument_key: str | None = None,
) -> list[CorporateActionOutcome]:
    """Return 1/5/20-session raw and NIFTY-relative event outcomes."""
    try:
        return get_market_runtime().get_corporate_action_outcomes(instrument_key)
    except MarketRuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.get("/corporate-action-calibration", response_model=CorporateActionCalibrationReport)
def get_corporate_action_calibration() -> CorporateActionCalibrationReport:
    """Report outcome buckets; samples under 30 remain explicitly uncalibrated."""
    try:
        return get_market_runtime().get_corporate_action_calibration()
    except MarketRuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.post("/reconcile", status_code=status.HTTP_202_ACCEPTED)
def start_after_market_reconciliation(session_date: date | None = None) -> dict[str, Any]:
    """Fetch official daily candles and compare them with captured minute data."""
    return _runtime_action(lambda: get_market_runtime().start_reconciliation(session_date))


@router.get("/reconciliations", response_model=list[DailyReconciliationRecord])
def get_after_market_reconciliations(session_date: date) -> list[DailyReconciliationRecord]:
    """Return the stored reconciliation audit for one session."""
    try:
        return get_market_runtime().get_reconciliations(session_date)
    except MarketRuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.get("/context", response_model=MarketContext)
def get_latest_market_context() -> MarketContext:
    """Return the most recent minute-level breadth, benchmark, liquidity, and sector context."""
    try:
        context = get_market_runtime().state_store.get_context()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis market state is unavailable",
        ) from exc
    if context is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Market context is not available yet")
    return context


@router.websocket("/stream")
async def stream_minute_market_context(websocket: WebSocket) -> None:
    """Push each new minute-level context snapshot to the React application."""
    await websocket.accept()
    last_timestamp: str | None = None
    try:
        while True:
            context = await asyncio.to_thread(get_market_runtime().state_store.get_context)
            if context is not None:
                timestamp = context.as_of.isoformat()
                if timestamp != last_timestamp:
                    await websocket.send_json(context.model_dump(mode="json"))
                    last_timestamp = timestamp
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        return
    except Exception:
        await websocket.close(code=1011, reason="Market state is unavailable")
