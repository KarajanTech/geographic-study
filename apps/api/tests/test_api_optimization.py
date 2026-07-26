"""Greedy optimization endpoints over HTTP. Requires PostGIS; skipped when absent."""

from __future__ import annotations

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
OPTIMIZATION_SOLUTIONS = f"{API_V1_PREFIX}/optimization-solutions"


def _create_project(
    client: TestClient, metric_dem: Path, name: str = "Optimization"
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


def _project_with_completed_viewsheds(
    api_client: TestClient,
    db_session: Session,
    settings: Settings,
    metric_dem: Path,
    *,
    spacing_m: float = 300.0,
    max_distance_m: float = 1000.0,
) -> dict[str, Any]:
    """Project -> DEM -> candidates -> viewsheds, processed synchronously."""
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

    viewshed_run = api_client.post(
        f"{ANALYSIS_RUNS}/{candidates_run.json()['id']}/viewsheds",
        json={"max_distance_m": max_distance_m},
    )
    assert viewshed_run.status_code == 202, viewshed_run.text

    process_pending_viewshed_runs(db_session, settings)
    db_session.commit()

    return dict(viewshed_run.json())


def test_optimize_selects_candidates_and_returns_a_solution(
    api_client: TestClient, db_session: Session, settings: Settings, metric_dem: Path
) -> None:
    viewshed_run = _project_with_completed_viewsheds(api_client, db_session, settings, metric_dem)

    response = api_client.post(f"{ANALYSIS_RUNS}/{viewshed_run['id']}/optimize", json={})

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["solver"] == "greedy"
    assert len(body["selected_candidate_ids"]) > 0
    assert body["coverage_ratio"] > 0.0
    assert body["weighted_coverage_ratio"] > 0.0
    assert body["visible_area_km2"] > 0.0
    assert body["hidden_area_km2"] >= 0.0
    assert len(body["iterations"]) == len(body["selected_candidate_ids"])


def test_iterations_are_ordered_and_coverage_is_monotonic(
    api_client: TestClient, db_session: Session, settings: Settings, metric_dem: Path
) -> None:
    viewshed_run = _project_with_completed_viewsheds(api_client, db_session, settings, metric_dem)

    body = api_client.post(f"{ANALYSIS_RUNS}/{viewshed_run['id']}/optimize", json={}).json()

    steps = [entry["step"] for entry in body["iterations"]]
    assert steps == list(range(len(steps)))
    coverage = [entry["cumulative_coverage"] for entry in body["iterations"]]
    assert coverage == sorted(coverage)
    candidate_ids = [entry["candidate_id"] for entry in body["iterations"]]
    assert len(candidate_ids) == len(set(candidate_ids))  # never selected twice
    assert candidate_ids == body["selected_candidate_ids"]


def test_max_sites_limits_the_selection(
    api_client: TestClient, db_session: Session, settings: Settings, metric_dem: Path
) -> None:
    viewshed_run = _project_with_completed_viewsheds(api_client, db_session, settings, metric_dem)

    body = api_client.post(
        f"{ANALYSIS_RUNS}/{viewshed_run['id']}/optimize", json={"max_sites": 2}
    ).json()

    assert len(body["selected_candidate_ids"]) <= 2
    assert body["stop_reason"] == "max_sites_reached"


def test_target_coverage_stops_early_when_reached(
    api_client: TestClient, db_session: Session, settings: Settings, metric_dem: Path
) -> None:
    viewshed_run = _project_with_completed_viewsheds(api_client, db_session, settings, metric_dem)

    full = api_client.post(f"{ANALYSIS_RUNS}/{viewshed_run['id']}/optimize", json={}).json()
    low_target = api_client.post(
        f"{ANALYSIS_RUNS}/{viewshed_run['id']}/optimize",
        json={"target_coverage": min(0.5, full["weighted_coverage_ratio"] / 2 or 0.01)},
    ).json()

    assert len(low_target["selected_candidate_ids"]) <= len(full["selected_candidate_ids"])


def test_solution_is_reproducible(
    api_client: TestClient, db_session: Session, settings: Settings, metric_dem: Path
) -> None:
    viewshed_run = _project_with_completed_viewsheds(api_client, db_session, settings, metric_dem)

    first = api_client.post(f"{ANALYSIS_RUNS}/{viewshed_run['id']}/optimize", json={}).json()
    second = api_client.post(f"{ANALYSIS_RUNS}/{viewshed_run['id']}/optimize", json={}).json()

    assert first["selected_candidate_ids"] == second["selected_candidate_ids"]
    assert first["coverage_ratio"] == second["coverage_ratio"]


def test_solution_can_be_fetched_and_listed(
    api_client: TestClient, db_session: Session, settings: Settings, metric_dem: Path
) -> None:
    viewshed_run = _project_with_completed_viewsheds(api_client, db_session, settings, metric_dem)
    created = api_client.post(f"{ANALYSIS_RUNS}/{viewshed_run['id']}/optimize", json={}).json()

    fetched = api_client.get(f"{OPTIMIZATION_SOLUTIONS}/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == created["id"]

    optimization_run_id = created["analysis_run_id"]
    listed = api_client.get(f"{ANALYSIS_RUNS}/{optimization_run_id}/optimization-solutions")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["id"] == created["id"]


def test_optimizing_a_candidates_run_instead_of_a_viewshed_run_is_rejected(
    api_client: TestClient, metric_dem: Path
) -> None:
    project = _create_project(api_client, metric_dem)
    with metric_dem.open("rb") as handle:
        api_client.post(
            f"{PROJECTS}/{project['id']}/datasets",
            files={"file": (metric_dem.name, handle, "image/tiff")},
            data={"buffer_m": "1000"},
        )
    candidates_run = api_client.post(
        f"{PROJECTS}/{project['id']}/candidates", json={"spacing_m": 300.0}
    ).json()

    response = api_client.post(f"{ANALYSIS_RUNS}/{candidates_run['id']}/optimize", json={})

    assert response.status_code == 422


def test_optimizing_before_any_viewshed_completes_is_rejected(
    api_client: TestClient, metric_dem: Path
) -> None:
    project = _create_project(api_client, metric_dem)
    with metric_dem.open("rb") as handle:
        api_client.post(
            f"{PROJECTS}/{project['id']}/datasets",
            files={"file": (metric_dem.name, handle, "image/tiff")},
            data={"buffer_m": "1000"},
        )
    candidates_run = api_client.post(
        f"{PROJECTS}/{project['id']}/candidates", json={"spacing_m": 300.0}
    ).json()
    viewshed_run = api_client.post(
        f"{ANALYSIS_RUNS}/{candidates_run['id']}/viewsheds", json={"max_distance_m": 1000.0}
    ).json()

    # No worker has run yet: every viewshed is still pending.
    response = api_client.post(f"{ANALYSIS_RUNS}/{viewshed_run['id']}/optimize", json={})

    assert response.status_code == 422


def test_optimize_for_unknown_run_returns_404(api_client: TestClient) -> None:
    response = api_client.post(
        f"{ANALYSIS_RUNS}/00000000-0000-0000-0000-000000000000/optimize", json={}
    )

    assert response.status_code == 404


def test_unknown_optimization_solution_returns_404(api_client: TestClient) -> None:
    response = api_client.get(f"{OPTIMIZATION_SOLUTIONS}/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404


def test_a_failed_viewshed_does_not_block_optimization(
    api_client: TestClient,
    db_session: Session,
    settings: Settings,
    metric_dem: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Optimization runs over whichever viewsheds completed, failures excluded."""
    from app.geo.viewshed import LineOfSightViewshedEngine

    project = _create_project(api_client, metric_dem)
    with metric_dem.open("rb") as handle:
        api_client.post(
            f"{PROJECTS}/{project['id']}/datasets",
            files={"file": (metric_dem.name, handle, "image/tiff")},
            data={"buffer_m": "1000"},
        )
    candidates_run = api_client.post(
        f"{PROJECTS}/{project['id']}/candidates", json={"spacing_m": 200.0, "max_slope_deg": 45.0}
    ).json()
    viewshed_run = api_client.post(
        f"{ANALYSIS_RUNS}/{candidates_run['id']}/viewsheds", json={"max_distance_m": 1000.0}
    ).json()

    original_compute = LineOfSightViewshedEngine.compute
    call_count = {"n": 0}

    def flaky_compute(self: LineOfSightViewshedEngine, *args: Any, **kwargs: Any) -> Any:
        call_count["n"] += 1
        if call_count["n"] == 1:
            msg = "Simulated failure"
            raise RuntimeError(msg)
        return original_compute(self, *args, **kwargs)

    monkeypatch.setattr(LineOfSightViewshedEngine, "compute", flaky_compute)
    process_pending_viewshed_runs(db_session, settings)
    db_session.commit()

    response = api_client.post(f"{ANALYSIS_RUNS}/{viewshed_run['id']}/optimize", json={})

    assert response.status_code == 201, response.text


def test_export_geojson_matches_the_solution(
    api_client: TestClient, db_session: Session, settings: Settings, metric_dem: Path
) -> None:
    viewshed_run = _project_with_completed_viewsheds(api_client, db_session, settings, metric_dem)
    solution = api_client.post(f"{ANALYSIS_RUNS}/{viewshed_run['id']}/optimize", json={}).json()

    response = api_client.get(f"{OPTIMIZATION_SOLUTIONS}/{solution['id']}/export.geojson")

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/geo+json")
    body = response.json()
    assert body["type"] == "FeatureCollection"
    assert len(body["features"]) == len(solution["selected_candidate_ids"])

    first = body["features"][0]
    assert first["type"] == "Feature"
    assert first["geometry"]["type"] == "Point"
    assert first["properties"]["rank"] == 1
    assert first["properties"]["candidate_site_id"] == solution["selected_candidate_ids"][0]
    assert isinstance(first["properties"]["elevation_m"], float)


def test_export_csv_matches_the_solution(
    api_client: TestClient, db_session: Session, settings: Settings, metric_dem: Path
) -> None:
    import csv
    import io

    viewshed_run = _project_with_completed_viewsheds(api_client, db_session, settings, metric_dem)
    solution = api_client.post(f"{ANALYSIS_RUNS}/{viewshed_run['id']}/optimize", json={}).json()

    response = api_client.get(f"{OPTIMIZATION_SOLUTIONS}/{solution['id']}/export.csv")

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert len(rows) == len(solution["selected_candidate_ids"])
    assert rows[0]["candidate_site_id"] == solution["selected_candidate_ids"][0]
    assert rows[0]["rank"] == "1"
    assert float(rows[0]["longitude"]) != 0.0
    assert float(rows[0]["latitude"]) != 0.0


def test_export_404s_for_an_unknown_solution(api_client: TestClient) -> None:
    missing_id = "00000000-0000-0000-0000-000000000000"

    geojson_response = api_client.get(f"{OPTIMIZATION_SOLUTIONS}/{missing_id}/export.geojson")
    csv_response = api_client.get(f"{OPTIMIZATION_SOLUTIONS}/{missing_id}/export.csv")

    assert geojson_response.status_code == 404
    assert csv_response.status_code == 404


def test_default_optimize_reports_uniform_weights(
    api_client: TestClient, db_session: Session, settings: Settings, metric_dem: Path
) -> None:
    """ROADMAP.md Phase 6: "los pesos utilizados quedan guardados"."""
    viewshed_run = _project_with_completed_viewsheds(api_client, db_session, settings, metric_dem)

    solution = api_client.post(f"{ANALYSIS_RUNS}/{viewshed_run['id']}/optimize", json={}).json()

    assert solution["weights_summary"] == {"source": "uniform"}
    # Physical and weighted coverage are always reported separately.
    assert "coverage_ratio" in solution
    assert "weighted_coverage_ratio" in solution


def test_optimize_with_a_preset_records_it_in_weights_summary(
    api_client: TestClient, db_session: Session, settings: Settings, metric_dem: Path
) -> None:
    viewshed_run = _project_with_completed_viewsheds(api_client, db_session, settings, metric_dem)

    solution = api_client.post(
        f"{ANALYSIS_RUNS}/{viewshed_run['id']}/optimize", json={"preset": "ridge_priority"}
    ).json()

    assert solution["weights_summary"] == {
        "source": "preset",
        "preset": "ridge_priority",
        "normalization": "min_max",
    }

    # Persisted, not just returned once: fetching it again shows the same weights.
    refetched = api_client.get(f"{OPTIMIZATION_SOLUTIONS}/{solution['id']}").json()
    assert refetched["weights_summary"] == solution["weights_summary"]


def test_optimize_with_a_priorities_raster_records_its_id(
    api_client: TestClient, db_session: Session, settings: Settings, metric_dem: Path
) -> None:
    viewshed_run = _project_with_completed_viewsheds(api_client, db_session, settings, metric_dem)
    project_id = viewshed_run["project_id"]

    with metric_dem.open("rb") as handle:
        ingested = api_client.post(
            f"{PROJECTS}/{project_id}/priorities",
            files={"file": ("risk.tif", handle, "image/tiff")},
        ).json()

    solution = api_client.post(
        f"{ANALYSIS_RUNS}/{viewshed_run['id']}/optimize",
        json={"priorities_dataset_id": ingested["processed"]["id"]},
    ).json()

    assert solution["weights_summary"]["source"] == "raster"
    assert solution["weights_summary"]["priorities_dataset_id"] == ingested["processed"]["id"]


def test_optimize_with_a_priority_zone_records_its_weight(
    api_client: TestClient, db_session: Session, settings: Settings, metric_dem: Path
) -> None:
    viewshed_run = _project_with_completed_viewsheds(api_client, db_session, settings, metric_dem)
    candidates_run_id = viewshed_run["parameters"]["candidates_run_id"]
    candidates = api_client.get(f"{ANALYSIS_RUNS}/{candidates_run_id}/candidates").json()["items"]
    lon, lat = candidates[0]["location"]["coordinates"]
    zone = {
        "type": "Polygon",
        "coordinates": [
            [
                [lon - 0.01, lat - 0.01],
                [lon + 0.01, lat - 0.01],
                [lon + 0.01, lat + 0.01],
                [lon - 0.01, lat + 0.01],
                [lon - 0.01, lat - 0.01],
            ]
        ],
    }

    solution = api_client.post(
        f"{ANALYSIS_RUNS}/{viewshed_run['id']}/optimize",
        json={"priority_zones": [{"geometry": zone, "weight": 4.5}]},
    ).json()

    assert solution["weights_summary"]["priority_zones"] == [{"weight": 4.5}]


def test_priorities_dataset_and_preset_are_mutually_exclusive(
    api_client: TestClient, db_session: Session, settings: Settings, metric_dem: Path
) -> None:
    viewshed_run = _project_with_completed_viewsheds(api_client, db_session, settings, metric_dem)
    project_id = viewshed_run["project_id"]

    with metric_dem.open("rb") as handle:
        ingested = api_client.post(
            f"{PROJECTS}/{project_id}/priorities",
            files={"file": ("risk.tif", handle, "image/tiff")},
        ).json()

    response = api_client.post(
        f"{ANALYSIS_RUNS}/{viewshed_run['id']}/optimize",
        json={"priorities_dataset_id": ingested["processed"]["id"], "preset": "ridge_priority"},
    )

    assert response.status_code == 422, response.text


def test_priorities_dataset_from_another_project_is_rejected(
    api_client: TestClient, db_session: Session, settings: Settings, metric_dem: Path
) -> None:
    viewshed_run = _project_with_completed_viewsheds(api_client, db_session, settings, metric_dem)

    other_project = _create_project(api_client, metric_dem, name="Other project")
    with metric_dem.open("rb") as handle:
        api_client.post(
            f"{PROJECTS}/{other_project['id']}/datasets",
            files={"file": (metric_dem.name, handle, "image/tiff")},
            data={"buffer_m": "1000"},
        )
    with metric_dem.open("rb") as handle:
        foreign_priorities = api_client.post(
            f"{PROJECTS}/{other_project['id']}/priorities",
            files={"file": ("risk.tif", handle, "image/tiff")},
        ).json()

    response = api_client.post(
        f"{ANALYSIS_RUNS}/{viewshed_run['id']}/optimize",
        json={"priorities_dataset_id": foreign_priorities["processed"]["id"]},
    )

    assert response.status_code == 422, response.text
