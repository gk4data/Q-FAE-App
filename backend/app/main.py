"""FastAPI entry point for Q-FAE."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.auth import router as auth_router
from app.api.routes.health import router as health_router
from app.api.routes.instruments import router as instruments_router
from app.api.routes.market import get_market_runtime, router as market_router
from app.core.config import get_settings


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    runtime = get_market_runtime()
    if runtime.status()["live"]["state"] != "stopped":
        runtime.stop_live()


def create_app() -> FastAPI:
    """Create the Q-FAE API application."""
    settings = get_settings()
    app = FastAPI(title="Q-FAE API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(instruments_router, prefix="/api/v1")
    app.include_router(market_router, prefix="/api/v1")
    return app


app = create_app()
