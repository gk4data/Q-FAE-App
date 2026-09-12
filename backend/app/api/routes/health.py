"""Operational health endpoint."""

from fastapi import APIRouter, Response, status

from app.core.config import get_settings
from app.db.engine import database_is_available

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check() -> dict[str, str]:
    """Return process health without exposing configuration or credentials."""
    settings = get_settings()
    return {"status": "ok", "environment": settings.qfae_environment}


@router.get("/health/database")
def database_health_check(response: Response) -> dict[str, str]:
    """Report PostgreSQL connectivity without returning its URL or credentials."""
    available = database_is_available()
    if not available:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ok" if available else "unavailable",
        "database": "postgresql",
    }
