"""Domain errors map to stable HTTP payloads."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.errors import (
    ConfigurationError,
    DependencyUnavailableError,
    InvalidInputError,
    ResourceNotFoundError,
    SentinelError,
    register_exception_handlers,
)


def test_error_codes_are_stable() -> None:
    assert SentinelError("x").code == "sentinel_error"
    assert ConfigurationError("x").code == "configuration_error"
    assert ResourceNotFoundError("x").code == "not_found"
    assert InvalidInputError("x").code == "invalid_input"
    assert DependencyUnavailableError("x").code == "dependency_unavailable"


def test_payload_carries_message_and_details() -> None:
    error = InvalidInputError("bad crs", details={"crs": "EPSG:4326"})

    assert error.to_payload() == {
        "code": "invalid_input",
        "message": "bad crs",
        "details": {"crs": "EPSG:4326"},
    }


def test_handler_renders_json_error_document() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    def boom() -> None:
        raise ResourceNotFoundError("project missing", details={"project_id": "42"})

    with TestClient(app) as client:
        response = client.get("/boom")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "not_found",
            "message": "project missing",
            "details": {"project_id": "42"},
        }
    }
