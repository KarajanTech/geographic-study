"""Candidate generation over HTTP. Requires PostGIS; skipped when absent."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import rasterio
from fastapi.testclient import TestClient

from app.api.router import API_V1_PREFIX

PROJECTS = f"{API_V1_PREFIX}/projects"
ANALYSIS_RUNS = f"{API_V1_PREFIX}/analysis-runs"


def _create_project(
    client: TestClient, metric_dem: Path, name: str = "Candidates"
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


def _upload(client: TestClient, project_id: str, path: Path, *, buffer_m: float = 1000.0) -> Any:
    with path.open("rb") as handle:
        return client.post(
            f"{PROJECTS}/{project_id}/datasets",
            files={"file": (path.name, handle, "image/tiff")},
            data={"buffer_m": str(buffer_m)},
        )


def _project_with_dem(api_client: TestClient, metric_dem: Path) -> dict[str, Any]:
    project = _create_project(api_client, metric_dem)
    response = _upload(api_client, project["id"], metric_dem)
    assert response.status_code == 201, response.text
    return project


def test_generate_candidates_creates_a_completed_run(
    api_client: TestClient, metric_dem: Path
) -> None:
    project = _project_with_dem(api_client, metric_dem)

    response = api_client.post(f"{PROJECTS}/{project['id']}/candidates", json={"spacing_m": 500.0})

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "completed"
    assert body["kind"] == "candidates"
    assert body["project_id"] == project["id"]
    assert body["error"] is None
    assert body["metrics"]["candidate_count"] > 0


def test_run_parameters_and_seed_are_persisted(api_client: TestClient, metric_dem: Path) -> None:
    project = _project_with_dem(api_client, metric_dem)

    body = api_client.post(
        f"{PROJECTS}/{project['id']}/candidates",
        json={"spacing_m": 300.0, "max_slope_deg": 20.0, "seed": 999},
    ).json()

    assert body["parameters"]["spacing_m"] == 300.0
    assert body["parameters"]["max_slope_deg"] == 20.0
    assert body["random_seed"] == 999
    assert body["algorithm_version"]


def test_candidates_are_listed_for_a_run(api_client: TestClient, metric_dem: Path) -> None:
    project = _project_with_dem(api_client, metric_dem)
    run = api_client.post(
        f"{PROJECTS}/{project['id']}/candidates", json={"spacing_m": 500.0}
    ).json()

    response = api_client.get(f"{ANALYSIS_RUNS}/{run['id']}/candidates")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] > 0
    assert len(body["items"]) == body["total"]
    first = body["items"][0]
    assert first["location"]["type"] == "Point"
    assert first["is_allowed"] is True
    assert first["rank"] == 0


def test_candidates_are_ranked_by_prominence(api_client: TestClient, metric_dem: Path) -> None:
    project = _project_with_dem(api_client, metric_dem)
    run = api_client.post(
        f"{PROJECTS}/{project['id']}/candidates", json={"spacing_m": 400.0}
    ).json()

    items = api_client.get(f"{ANALYSIS_RUNS}/{run['id']}/candidates").json()["items"]

    ranks = [item["rank"] for item in items]
    assert ranks == sorted(ranks)
    prominences = [item["prominence_m"] for item in items]
    assert prominences == sorted(prominences, reverse=True)


def test_max_slope_reduces_candidate_count(api_client: TestClient, metric_dem: Path) -> None:
    project = _project_with_dem(api_client, metric_dem)

    lenient = api_client.post(
        f"{PROJECTS}/{project['id']}/candidates", json={"spacing_m": 300.0, "max_slope_deg": 89.0}
    ).json()
    strict = api_client.post(
        f"{PROJECTS}/{project['id']}/candidates", json={"spacing_m": 300.0, "max_slope_deg": 2.0}
    ).json()

    assert strict["metrics"]["candidate_count"] <= lenient["metrics"]["candidate_count"]


def test_min_separation_reduces_candidate_count(api_client: TestClient, metric_dem: Path) -> None:
    project = _project_with_dem(api_client, metric_dem)

    packed = api_client.post(
        f"{PROJECTS}/{project['id']}/candidates",
        json={"spacing_m": 100.0, "min_separation_m": 0.0},
    ).json()
    thinned = api_client.post(
        f"{PROJECTS}/{project['id']}/candidates",
        json={"spacing_m": 100.0, "min_separation_m": 500.0},
    ).json()

    assert thinned["metrics"]["candidate_count"] < packed["metrics"]["candidate_count"]


def test_exclusion_zone_is_honoured_over_http(api_client: TestClient, metric_dem: Path) -> None:
    project = _project_with_dem(api_client, metric_dem)
    area = project["area"]
    # A polygon covering the west half of the study area's bounding box.
    coords = area["coordinates"][0][0] if area["type"] == "MultiPolygon" else area["coordinates"][0]
    lons = [pt[0] for pt in coords]
    lats = [pt[1] for pt in coords]
    minlon, maxlon = min(lons), max(lons)
    minlat, maxlat = min(lats), max(lats)
    midlon = (minlon + maxlon) / 2

    exclusion = {
        "type": "Polygon",
        "coordinates": [
            [
                [minlon - 1, minlat - 1],
                [midlon, minlat - 1],
                [midlon, maxlat + 1],
                [minlon - 1, maxlat + 1],
                [minlon - 1, minlat - 1],
            ]
        ],
    }

    run = api_client.post(
        f"{PROJECTS}/{project['id']}/candidates",
        json={"spacing_m": 200.0, "exclusion_zones": [exclusion]},
    ).json()

    candidates = api_client.get(f"{ANALYSIS_RUNS}/{run['id']}/candidates").json()["items"]
    for candidate in candidates:
        lon = candidate["location"]["coordinates"][0]
        assert lon >= midlon


def test_required_site_appears_and_is_mandatory(api_client: TestClient, metric_dem: Path) -> None:
    project = _project_with_dem(api_client, metric_dem)
    lon, lat = project["centroid_lon"], project["centroid_lat"]

    run = api_client.post(
        f"{PROJECTS}/{project['id']}/candidates",
        json={
            "spacing_m": 500.0,
            "max_slope_deg": 0.0001,
            "required_sites": [{"lon": lon, "lat": lat}],
        },
    ).json()

    candidates = api_client.get(f"{ANALYSIS_RUNS}/{run['id']}/candidates").json()["items"]
    mandatory = [c for c in candidates if c["is_mandatory"]]
    assert len(mandatory) == 1
    assert mandatory[0]["source"] == "required_site"


def test_run_without_a_dem_is_rejected(
    api_client: TestClient, madrid_area_geojson: dict[str, Any]
) -> None:
    project = api_client.post(PROJECTS, json={"name": "No DEM", "area": madrid_area_geojson}).json()

    response = api_client.post(f"{PROJECTS}/{project['id']}/candidates", json={})

    assert response.status_code == 422
    assert "DEM" in response.json()["error"]["message"]


def test_run_for_unknown_project_returns_404(api_client: TestClient) -> None:
    response = api_client.post(
        f"{PROJECTS}/00000000-0000-0000-0000-000000000000/candidates", json={}
    )

    assert response.status_code == 404


def test_analysis_runs_are_listed_for_a_project(api_client: TestClient, metric_dem: Path) -> None:
    project = _project_with_dem(api_client, metric_dem)
    api_client.post(f"{PROJECTS}/{project['id']}/candidates", json={"spacing_m": 500.0})
    api_client.post(f"{PROJECTS}/{project['id']}/candidates", json={"spacing_m": 300.0})

    response = api_client.get(f"{PROJECTS}/{project['id']}/analysis-runs")

    assert response.status_code == 200
    assert response.json()["total"] == 2


def test_get_single_analysis_run(api_client: TestClient, metric_dem: Path) -> None:
    project = _project_with_dem(api_client, metric_dem)
    created = api_client.post(
        f"{PROJECTS}/{project['id']}/candidates", json={"spacing_m": 500.0}
    ).json()

    response = api_client.get(f"{ANALYSIS_RUNS}/{created['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_unknown_analysis_run_returns_404(api_client: TestClient) -> None:
    response = api_client.get(f"{ANALYSIS_RUNS}/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404


def test_out_of_range_spacing_is_rejected(api_client: TestClient, metric_dem: Path) -> None:
    project = _project_with_dem(api_client, metric_dem)

    response = api_client.post(f"{PROJECTS}/{project['id']}/candidates", json={"spacing_m": -5.0})

    assert response.status_code == 422


def test_generation_reuses_the_latest_processed_dem(
    api_client: TestClient, metric_dem: Path
) -> None:
    """Re-ingesting a DEM does not stop candidate generation from working."""
    project = _project_with_dem(api_client, metric_dem)
    _upload(api_client, project["id"], metric_dem)  # a second ingestion

    response = api_client.post(f"{PROJECTS}/{project['id']}/candidates", json={"spacing_m": 500.0})

    assert response.status_code == 201
