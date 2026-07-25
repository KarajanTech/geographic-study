"""Health and readiness endpoint behaviour."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import ALGORITHM_VERSION, __version__
from app.api.router import API_V1_PREFIX
from app.core.config import Environment, Settings
from app.core.middleware import REQUEST_ID_HEADER


def test_health_reports_service_identity(client: TestClient) -> None:
    response = client.get(f"{API_V1_PREFIX}/health")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "status": "ok",
        "service": "sentinel-planner-api",
        "version": __version__,
        "environment": Environment.CI.value,
        "algorithm_version": ALGORITHM_VERSION,
    }


def test_health_does_not_touch_the_database(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _explode() -> bool:  # pragma: no cover - must never run
        raise AssertionError("liveness must not query the database")

    monkeypatch.setattr("app.api.routes.health.check_database", _explode)
    assert client.get(f"{API_V1_PREFIX}/health").status_code == 200


def test_health_echoes_request_id(client: TestClient) -> None:
    response = client.get(f"{API_V1_PREFIX}/health", headers={REQUEST_ID_HEADER: "abc123"})

    assert response.headers[REQUEST_ID_HEADER] == "abc123"


def test_health_generates_request_id_when_absent(client: TestClient) -> None:
    response = client.get(f"{API_V1_PREFIX}/health")

    assert response.headers[REQUEST_ID_HEADER]


def test_readiness_reports_unconfigured_database(client: TestClient) -> None:
    response = client.get(f"{API_V1_PREFIX}/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["database"] == "not_configured"
    assert body["data_dir"] == "up"


def test_readiness_is_ready_when_database_is_up(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured = settings.model_copy(
        update={"database_url": "postgresql+psycopg://user:pw@db:5432/sentinel"}
    )
    monkeypatch.setattr("app.api.routes.health.get_settings", lambda: configured)
    monkeypatch.setattr("app.services.storage.get_settings", lambda: configured)
    monkeypatch.setattr("app.api.routes.health.check_database", lambda: True)

    from app.main import create_app

    with TestClient(create_app(configured)) as client:
        response = client.get(f"{API_V1_PREFIX}/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "up", "data_dir": "up"}


def test_readiness_reports_database_down(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured = settings.model_copy(
        update={"database_url": "postgresql+psycopg://user:pw@db:5432/sentinel"}
    )
    monkeypatch.setattr("app.api.routes.health.get_settings", lambda: configured)
    monkeypatch.setattr("app.services.storage.get_settings", lambda: configured)
    monkeypatch.setattr("app.api.routes.health.check_database", lambda: False)

    from app.main import create_app

    with TestClient(create_app(configured)) as client:
        response = client.get(f"{API_V1_PREFIX}/health/ready")

    assert response.status_code == 503
    assert response.json()["database"] == "down"


def test_openapi_document_is_served(client: TestClient) -> None:
    response = client.get(f"{API_V1_PREFIX}/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert f"{API_V1_PREFIX}/health" in paths
    assert f"{API_V1_PREFIX}/health/ready" in paths
