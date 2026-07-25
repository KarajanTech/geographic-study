"""Viewshed endpoints over HTTP. Requires PostGIS; skipped when absent.

The worker is simulated by calling ``process_pending_viewshed_runs`` directly
against the test's own session — exactly what ``app.workers.viewshed_worker``
does in production, just without a second process.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest
import rasterio
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.router import API_V1_PREFIX
from app.core.config import Settings
from app.services.viewsheds import process_pending_viewshed_runs

PROJECTS = f"{API_V1_PREFIX}/projects"
ANALYSIS_RUNS = f"{API_V1_PREFIX}/analysis-runs"
VIEWSHEDS = f"{API_V1_PREFIX}/viewsheds"


def _create_project(
    client: TestClient, metric_dem: Path, name: str = "Viewsheds"
) -> dict[str, Any]:
    from shapely.geometry import box, mapping

    from app.geo.area import reproject_geometry

    with rasterio.open(metric_dem) as dataset:
        left, bottom, right, top = dataset.bounds
        crs = dataset.crs.to_string()

    inset_x, inset_y = (right - left) * 0.25, (top - bottom) * 0.25
    inner = box(left + inset_x, bottom + inset_y, right - inset_x, top - inset_y)
    area = dict(mapping(reproject_geometry(inner, crs, "EPSG:4326")))

    response = client.post(PROJECTS, json={"name": name, "area": area})
    assert response.status_code == 201, response.text
    return dict(response.json())


def _project_with_candidates(
    api_client: TestClient, metric_dem: Path, *, spacing_m: float = 300.0
) -> tuple[dict[str, Any], dict[str, Any]]:
    project = _create_project(api_client, metric_dem)

    with metric_dem.open("rb") as handle:
        uploaded = api_client.post(
            f"{PROJECTS}/{project['id']}/datasets",
            files={"file": (metric_dem.name, handle, "image/tiff")},
            data={"buffer_m": "1000"},
        )
    assert uploaded.status_code == 201, uploaded.text

    candidates_run = api_client.post(
        f"{PROJECTS}/{project['id']}/candidates",
        json={"spacing_m": spacing_m, "max_slope_deg": 45.0},
    )
    assert candidates_run.status_code == 201, candidates_run.text
    return project, candidates_run.json()


def test_enqueue_creates_a_pending_run(api_client: TestClient, metric_dem: Path) -> None:
    _, candidates_run = _project_with_candidates(api_client, metric_dem)

    response = api_client.post(
        f"{ANALYSIS_RUNS}/{candidates_run['id']}/viewsheds",
        json={"max_distance_m": 1000.0},
    )

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["kind"] == "viewshed"
    assert body["status"] == "pending"
    assert body["metrics"]["total"] > 0
    assert body["metrics"]["pending"] == body["metrics"]["total"]


def test_no_viewshed_is_computed_by_the_enqueue_request(
    api_client: TestClient, metric_dem: Path
) -> None:
    """The defining property: enqueuing alone leaves every row unpicked."""
    _, candidates_run = _project_with_candidates(api_client, metric_dem)

    run = api_client.post(
        f"{ANALYSIS_RUNS}/{candidates_run['id']}/viewsheds", json={"max_distance_m": 1000.0}
    ).json()
    items = api_client.get(f"{ANALYSIS_RUNS}/{run['id']}/viewsheds").json()["items"]

    assert all(item["status"] == "pending" for item in items)
    assert all(item["visible_cell_count"] is None for item in items)


def test_worker_processes_pending_runs_to_completion(
    api_client: TestClient, db_session: Session, settings: Settings, metric_dem: Path
) -> None:
    _, candidates_run = _project_with_candidates(api_client, metric_dem)
    run = api_client.post(
        f"{ANALYSIS_RUNS}/{candidates_run['id']}/viewsheds", json={"max_distance_m": 1000.0}
    ).json()

    processed = process_pending_viewshed_runs(db_session, settings)
    db_session.commit()

    assert len(processed) == 1
    assert processed[0].id == uuid.UUID(run["id"])

    body = api_client.get(f"{ANALYSIS_RUNS}/{run['id']}").json()
    assert body["status"] == "completed"
    assert body["metrics"]["completed"] == body["metrics"]["total"]
    assert body["metrics"]["failed"] == 0

    items = api_client.get(f"{ANALYSIS_RUNS}/{run['id']}/viewsheds").json()["items"]
    assert all(item["status"] == "completed" for item in items)
    assert all(item["visible_cell_count"] is not None for item in items)
    assert all(item["coverage_ratio"] is not None for item in items)
    assert all(0.0 <= item["coverage_ratio"] <= 1.0 for item in items)


def test_repeating_an_identical_request_uses_the_cache(
    api_client: TestClient, db_session: Session, settings: Settings, metric_dem: Path
) -> None:
    _, candidates_run = _project_with_candidates(api_client, metric_dem)
    payload = {"max_distance_m": 1000.0, "observer_height_m": 10.0}

    first = api_client.post(
        f"{ANALYSIS_RUNS}/{candidates_run['id']}/viewsheds", json=payload
    ).json()
    process_pending_viewshed_runs(db_session, settings)
    db_session.commit()

    second = api_client.post(
        f"{ANALYSIS_RUNS}/{candidates_run['id']}/viewsheds", json=payload
    ).json()

    # Every candidate was already computed under an identical cache key, so
    # the second run is immediately complete with zero new computation.
    assert second["status"] == "completed"
    assert second["metrics"]["cache_hits"] == second["metrics"]["total"]
    assert second["metrics"]["pending"] == 0

    first_ids = {
        i["id"] for i in api_client.get(f"{ANALYSIS_RUNS}/{first['id']}/viewsheds").json()["items"]
    }
    second_ids = {
        i["id"] for i in api_client.get(f"{ANALYSIS_RUNS}/{second['id']}/viewsheds").json()["items"]
    }
    assert first_ids == second_ids  # literally the same rows, not recomputed


def test_different_parameters_do_not_share_the_cache(
    api_client: TestClient, metric_dem: Path
) -> None:
    _, candidates_run = _project_with_candidates(api_client, metric_dem)

    first = api_client.post(
        f"{ANALYSIS_RUNS}/{candidates_run['id']}/viewsheds", json={"max_distance_m": 1000.0}
    ).json()
    second = api_client.post(
        f"{ANALYSIS_RUNS}/{candidates_run['id']}/viewsheds", json={"max_distance_m": 1500.0}
    ).json()

    assert second["metrics"]["cache_hits"] == 0
    assert first["id"] != second["id"]


def test_mask_and_preview_are_downloadable_after_processing(
    api_client: TestClient, db_session: Session, settings: Settings, metric_dem: Path
) -> None:
    _, candidates_run = _project_with_candidates(api_client, metric_dem)
    run = api_client.post(
        f"{ANALYSIS_RUNS}/{candidates_run['id']}/viewsheds", json={"max_distance_m": 1000.0}
    ).json()
    process_pending_viewshed_runs(db_session, settings)
    db_session.commit()

    viewshed = api_client.get(f"{ANALYSIS_RUNS}/{run['id']}/viewsheds").json()["items"][0]
    assert viewshed["preview_url"] is not None
    assert viewshed["bounds_wgs84"] is not None

    mask_response = api_client.get(f"{VIEWSHEDS}/{viewshed['id']}/mask.tif")
    assert mask_response.status_code == 200
    assert mask_response.headers["content-type"] == "image/tiff"

    preview_response = api_client.get(f"{VIEWSHEDS}/{viewshed['id']}/preview.png")
    assert preview_response.status_code == 200
    assert preview_response.headers["content-type"] == "image/png"
    assert preview_response.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_unavailable_mask_before_processing_is_a_404(
    api_client: TestClient, metric_dem: Path
) -> None:
    _, candidates_run = _project_with_candidates(api_client, metric_dem)
    run = api_client.post(
        f"{ANALYSIS_RUNS}/{candidates_run['id']}/viewsheds", json={"max_distance_m": 1000.0}
    ).json()
    viewshed_id = api_client.get(f"{ANALYSIS_RUNS}/{run['id']}/viewsheds").json()["items"][0]["id"]

    response = api_client.get(f"{VIEWSHEDS}/{viewshed_id}/mask.tif")

    assert response.status_code == 404


def test_a_failed_candidate_does_not_abort_the_batch(
    api_client: TestClient,
    db_session: Session,
    settings: Settings,
    metric_dem: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """'un fallo en un candidato no destruye toda la ejecución'."""
    _, candidates_run = _project_with_candidates(api_client, metric_dem, spacing_m=200.0)
    run = api_client.post(
        f"{ANALYSIS_RUNS}/{candidates_run['id']}/viewsheds", json={"max_distance_m": 1000.0}
    ).json()

    from app.geo.viewshed import LineOfSightViewshedEngine

    original_compute = LineOfSightViewshedEngine.compute
    call_count = {"n": 0}

    def flaky_compute(self: LineOfSightViewshedEngine, *args: Any, **kwargs: Any) -> Any:
        call_count["n"] += 1
        if call_count["n"] == 1:
            msg = "Simulated failure for the first candidate"
            raise RuntimeError(msg)
        return original_compute(self, *args, **kwargs)

    monkeypatch.setattr(LineOfSightViewshedEngine, "compute", flaky_compute)
    process_pending_viewshed_runs(db_session, settings)
    db_session.commit()

    body = api_client.get(f"{ANALYSIS_RUNS}/{run['id']}").json()
    assert body["status"] == "completed"
    assert body["metrics"]["failed"] == 1
    assert body["metrics"]["completed"] == body["metrics"]["total"] - 1

    items = api_client.get(f"{ANALYSIS_RUNS}/{run['id']}/viewsheds").json()["items"]
    statuses = [item["status"] for item in items]
    assert statuses.count("failed") == 1
    assert statuses.count("completed") == len(items) - 1


def test_enqueue_for_a_non_candidates_run_is_rejected(
    api_client: TestClient, metric_dem: Path
) -> None:
    _, candidates_run = _project_with_candidates(api_client, metric_dem)
    viewshed_run = api_client.post(
        f"{ANALYSIS_RUNS}/{candidates_run['id']}/viewsheds", json={"max_distance_m": 1000.0}
    ).json()

    response = api_client.post(
        f"{ANALYSIS_RUNS}/{viewshed_run['id']}/viewsheds", json={"max_distance_m": 1000.0}
    )

    assert response.status_code == 422


def test_enqueue_for_unknown_run_returns_404(api_client: TestClient) -> None:
    response = api_client.post(
        f"{ANALYSIS_RUNS}/00000000-0000-0000-0000-000000000000/viewsheds",
        json={"max_distance_m": 1000.0},
    )

    assert response.status_code == 404


def test_enqueue_a_subset_of_candidates(api_client: TestClient, metric_dem: Path) -> None:
    _, candidates_run = _project_with_candidates(api_client, metric_dem)
    all_candidates = api_client.get(f"{ANALYSIS_RUNS}/{candidates_run['id']}/candidates").json()[
        "items"
    ]
    subset = [c["id"] for c in all_candidates[:2]]

    run = api_client.post(
        f"{ANALYSIS_RUNS}/{candidates_run['id']}/viewsheds",
        json={"max_distance_m": 1000.0, "candidate_site_ids": subset},
    ).json()

    assert run["metrics"]["total"] == 2


def test_unknown_viewshed_returns_404(api_client: TestClient) -> None:
    response = api_client.get(f"{VIEWSHEDS}/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
