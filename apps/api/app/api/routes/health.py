"""Health and readiness endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.core.config import Settings, get_settings
from app.db.session import check_database
from app.schemas.health import ComponentStatus, HealthResponse, ReadinessResponse
from app.services.storage import check_data_dir_writable

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
def health() -> HealthResponse:
    """Report that the process is alive. Never touches the database."""
    settings: Settings = get_settings()
    return HealthResponse(
        status="ok",
        service=settings.service_name,
        version=settings.version,
        environment=settings.environment.value,
        algorithm_version=settings.algorithm_version,
    )


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe",
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
)
def readiness(response: Response) -> ReadinessResponse:
    """Report dependency status. Returns 503 when a required dependency is down."""
    settings: Settings = get_settings()

    if not settings.database_url:
        database = ComponentStatus.NOT_CONFIGURED
    else:
        database = ComponentStatus.UP if check_database() else ComponentStatus.DOWN

    data_dir = ComponentStatus.UP if check_data_dir_writable() else ComponentStatus.DOWN

    ready = database is ComponentStatus.UP and data_dir is ComponentStatus.UP
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessResponse(
        status="ready" if ready else "not_ready",
        database=database,
        data_dir=data_dir,
    )
