"""Operational health endpoint."""

from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check() -> dict[str, str]:
    """Return process health without exposing configuration or credentials."""
    settings = get_settings()
    return {"status": "ok", "environment": settings.qfae_environment}
