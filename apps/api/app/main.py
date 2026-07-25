"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import API_V1_PREFIX, api_router
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestContextMiddleware
from app.services.storage import ensure_data_dirs

_log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = get_settings()
    ensure_data_dirs(settings)
    _log.info(
        "api_started",
        service=settings.service_name,
        version=settings.version,
        environment=settings.environment.value,
        algorithm_version=settings.algorithm_version,
        data_dir=str(settings.data_dir),
        database_configured=bool(settings.database_url),
    )
    yield
    _log.info("api_stopped")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the ASGI application.

    A factory rather than a module level singleton so tests can build an app
    with explicit settings and no global state.
    """
    cfg = settings or get_settings()
    configure_logging(level=cfg.log_level, json_logs=cfg.use_json_logs)

    app = FastAPI(
        title="Sentinel Planner API",
        version=cfg.version,
        summary="Geospatial planning of wildfire surveillance tower networks.",
        openapi_url=f"{API_V1_PREFIX}/openapi.json",
        docs_url=f"{API_V1_PREFIX}/docs",
        redoc_url=None,
        lifespan=lifespan,
    )

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)
    app.include_router(api_router)
    return app


app = create_app()
