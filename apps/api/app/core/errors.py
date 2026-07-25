"""Domain exceptions and their HTTP representation.

Every error raised by the domain carries a stable machine readable ``code`` so
the frontend can react without parsing prose.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse


class SentinelError(Exception):
    """Base class for every Sentinel Planner domain error."""

    code: str = "sentinel_error"
    http_status: int = status.HTTP_500_INTERNAL_SERVER_ERROR

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details or {}

    def to_payload(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


class ConfigurationError(SentinelError):
    """The service is misconfigured, for example a missing database URL."""

    code = "configuration_error"
    http_status = status.HTTP_500_INTERNAL_SERVER_ERROR


class ResourceNotFoundError(SentinelError):
    """A requested entity does not exist."""

    code = "not_found"
    http_status = status.HTTP_404_NOT_FOUND


class InvalidInputError(SentinelError):
    """Input is syntactically valid but rejected by a domain rule."""

    code = "invalid_input"
    http_status = status.HTTP_422_UNPROCESSABLE_CONTENT


class DependencyUnavailableError(SentinelError):
    """A required dependency (database, storage, worker) is unreachable."""

    code = "dependency_unavailable"
    http_status = status.HTTP_503_SERVICE_UNAVAILABLE


async def sentinel_error_handler(_: Request, exc: Exception) -> JSONResponse:
    """Render a :class:`SentinelError` as a JSON error document."""
    if not isinstance(exc, SentinelError):  # pragma: no cover - defensive
        raise exc
    return JSONResponse(status_code=exc.http_status, content={"error": exc.to_payload()})


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(SentinelError, sentinel_error_handler)
