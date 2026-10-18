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
from app.models.backtest import BacktestRun, BacktestRunListItem, BacktestRunRequest
from app.models.market import (
    Candle,
    DailyReconciliationRecord,
    DailyRegimeSnapshot,
    EvidenceOutcomeObservation,
    FinancialResultCheckReport,
    FinancialMetricSnapshot,
    FlowLiquidityConfirmation,
    MarketContext,
    MarketRegimeSnapshot,
    MinuteOfDayProfile,
    OpportunityEvidenceSnapshot,
    RankedOpportunity,
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
            output_path=settings.qfae_equity_universe_path,
            minimum_market_cap_crore=settings.qfae_min_market_cap_crore,
            minimum_share_price_inr=settings.qfae_min_share_price_inr,
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
    """Prepare the universe and automatically start live data when preparation finishes."""
    return _runtime_action(
        lambda: get_market_runtime().start_bootstrap(limit, auto_start_live=True)
    )


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
    """Return approved stocks with their latest cached minute data."""
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


@router.get("/opportunities", response_model=list[RankedOpportunity])
def get_ranked_opportunities(
    limit: Annotated[int | None, Query(ge=1, le=2000)] = None,
) -> list[RankedOpportunity]:
    """Return the provisional, explainable long-continuation ranking."""
    try:
        return get_market_runtime().get_ranked_opportunities(limit)
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
    """Return execution-quality and tradability gates for the approved universe."""
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


@router.post("/backtests", response_model=BacktestRun)
def run_opportunity_backtest(config: BacktestRunRequest) -> BacktestRun:
    """Run and persist a point-in-time simulation of recorded recommendations."""
    return _runtime_action(lambda: get_market_runtime().run_backtest(config))


@router.get("/backtests", response_model=list[BacktestRunListItem])
def list_opportunity_backtests(
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[BacktestRunListItem]:
    return _runtime_action(lambda: get_market_runtime().list_backtest_runs(limit))


@router.get("/backtests/{run_id}", response_model=BacktestRun)
def get_opportunity_backtest(run_id: str) -> BacktestRun:
    result = _runtime_action(lambda: get_market_runtime().get_backtest_run(run_id))
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backtest run not found")
    return result


@router.post("/financial-results/check", response_model=FinancialResultCheckReport)
def check_financial_results(
    limit: Annotated[int | None, Query(ge=1, le=250)] = None,
) -> FinancialResultCheckReport:
    """Check a bounded quarterly/annual batch, reusing protected recent snapshots."""
    try:
        return get_market_runtime().check_financial_results(limit)
    except MarketRuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.get("/financial-metrics", response_model=list[FinancialMetricSnapshot])
def get_financial_metrics(
    instrument_key: str | None = None,
    limit: Annotated[int, Query(ge=1, le=5000)] = 500,
    latest_only: bool = False,
) -> list[FinancialMetricSnapshot]:
    """Return versioned, deterministic statement-derived metrics without model weights."""
    try:
        return get_market_runtime().get_financial_metrics(
            instrument_key=instrument_key,
            limit=limit,
            latest_only=latest_only,
        )
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
        context = get_market_runtime().get_market_context()
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
            context = await asyncio.to_thread(get_market_runtime().get_market_context)
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
