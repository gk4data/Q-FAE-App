"""Market-day bootstrap, live-stream, candle, and context endpoints."""

from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect, status

from app.core.config import get_settings
from app.models.market import Candle, DailyRegimeSnapshot, MarketContext, StockFeatureSnapshot, WatchlistItem
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
