"""Project endpoints. Requires a PostGIS database; skipped when unavailable."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.api.router import API_V1_PREFIX
from app.db.models import Project

PROJECTS = f"{API_V1_PREFIX}/projects"


def test_create_project_selects_a_metric_analysis_crs(
    api_client: TestClient, madrid_area_geojson: dict[str, Any]
) -> None:
    response = api_client.post(
        PROJECTS, json={"name": "Sierra de Madrid", "area": madrid_area_geojson}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["analysis_crs"] == "EPSG:25830"
    assert 90.0 < body["area_km2"] < 120.0
    assert body["area"]["type"] == "MultiPolygon"
    assert body["dataset_count"] == 0


def test_created_project_can_be_read_back(
    api_client: TestClient, madrid_area_geojson: dict[str, Any]
) -> None:
    created = api_client.post(
        PROJECTS,
        json={
            "name": "Readback",
            "description": "A study area",
            "area": madrid_area_geojson,
        },
    ).json()

    fetched = api_client.get(f"{PROJECTS}/{created['id']}")

    assert fetched.status_code == 200
    assert fetched.json()["name"] == "Readback"
    assert fetched.json()["description"] == "A study area"
    assert fetched.json()["area"] == created["area"]


def test_analysis_crs_can_be_pinned(
    api_client: TestClient, madrid_area_geojson: dict[str, Any]
) -> None:
    response = api_client.post(
        PROJECTS,
        json={"name": "Pinned", "area": madrid_area_geojson, "analysis_crs": "EPSG:32630"},
    )

    assert response.status_code == 201
    assert response.json()["analysis_crs"] == "EPSG:32630"


def test_geographic_analysis_crs_is_rejected(
    api_client: TestClient, madrid_area_geojson: dict[str, Any]
) -> None:
    response = api_client.post(
        PROJECTS,
        json={"name": "Bad CRS", "area": madrid_area_geojson, "analysis_crs": "EPSG:4326"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_input"


def test_non_polygon_area_is_rejected(api_client: TestClient) -> None:
    response = api_client.post(
        PROJECTS,
        json={"name": "Point", "area": {"type": "Point", "coordinates": [-3.7, 40.4]}},
    )

    assert response.status_code == 422


def test_self_intersecting_area_is_rejected(api_client: TestClient) -> None:
    response = api_client.post(
        PROJECTS,
        json={
            "name": "Bowtie",
            "area": {
                "type": "Polygon",
                "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]],
            },
        },
    )

    assert response.status_code == 422
    assert "invalid" in response.json()["error"]["message"]


def test_projects_are_listed_newest_first(
    api_client: TestClient, db_session: Session, madrid_area_geojson: dict[str, Any]
) -> None:
    older = api_client.post(PROJECTS, json={"name": "First", "area": madrid_area_geojson}).json()
    api_client.post(PROJECTS, json={"name": "Second", "area": madrid_area_geojson})

    # Both inserts share one transaction, so now() gives them the same
    # timestamp. Age the first one so the ordering has something to sort on.
    db_session.execute(
        update(Project)
        .where(Project.id == uuid.UUID(older["id"]))
        .values(created_at=datetime(2020, 1, 1, tzinfo=UTC))
    )

    body = api_client.get(PROJECTS).json()

    assert body["total"] >= 2
    names = [item["name"] for item in body["items"]]
    assert names.index("Second") < names.index("First")


def test_project_can_be_renamed(
    api_client: TestClient, madrid_area_geojson: dict[str, Any]
) -> None:
    created = api_client.post(PROJECTS, json={"name": "Old", "area": madrid_area_geojson}).json()

    response = api_client.patch(f"{PROJECTS}/{created['id']}", json={"name": "New"})

    assert response.status_code == 200
    assert response.json()["name"] == "New"
    # The study area and its CRS are untouched.
    assert response.json()["analysis_crs"] == created["analysis_crs"]
    assert response.json()["area"] == created["area"]


def test_the_study_area_cannot_be_patched(
    api_client: TestClient, madrid_area_geojson: dict[str, Any]
) -> None:
    created = api_client.post(PROJECTS, json={"name": "Fixed", "area": madrid_area_geojson}).json()

    response = api_client.patch(f"{PROJECTS}/{created['id']}", json={"area": madrid_area_geojson})

    assert response.status_code == 422  # extra fields are forbidden


def test_unknown_project_returns_404(api_client: TestClient) -> None:
    response = api_client.get(f"{PROJECTS}/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_malformed_uuid_returns_422(api_client: TestClient) -> None:
    assert api_client.get(f"{PROJECTS}/not-a-uuid").status_code == 422
