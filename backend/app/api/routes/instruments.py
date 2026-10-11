"""Instrument-universe endpoints."""

from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.core.config import get_settings
from app.services.equity_universe import EquityUniverseService

router = APIRouter(prefix="/instruments", tags=["instruments"])


def get_universe_service() -> EquityUniverseService:
    settings = get_settings()
    return EquityUniverseService(
        output_path=settings.qfae_equity_universe_path,
        minimum_market_cap_crore=settings.qfae_min_market_cap_crore,
        minimum_share_price_inr=settings.qfae_min_share_price_inr,
    )


@router.get("/universe")
def get_instrument_universe() -> dict[str, Any]:
    """Return the latest local instrument mapping without refreshing it."""
    try:
        return get_universe_service().load()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/refresh")
def refresh_instrument_universe() -> dict[str, Any]:
    """Download the Upstox master and regenerate Q-FAE's equity mapping."""
    try:
        return get_universe_service().refresh()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
