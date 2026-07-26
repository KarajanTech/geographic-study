"""Priorities/risk raster upload endpoint over HTTP. Requires PostGIS; skipped when absent."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import rasterio
from fastapi.testclient import TestClient
from shapely.geometry import box, mapping

from app.api.router import API_V1_PREFIX
from app.geo.area import reproject_geometry

PROJECTS = f"{API_V1_PREFIX}/projects"


def _create_project_with_dem(
    client: TestClient, metric_dem: Path, name: str = "Priorities"
) -> dict[str, Any]:
    with rasterio.open(metric_dem) as dataset:
        left, bottom, right, top = dataset.bounds
        crs = dataset.crs.to_string()
    inset_x, inset_y = (right - left) * 0.25, (top - bottom) * 0.25
    inner = box(left + inset_x, bottom + inset_y, right - inset_x, top - inset_y)
    area = dict(mapping(reproject_geometry(inner, crs, "EPSG:4326")))

    project = client.post(PROJECTS, json={"name": name, "area": area}).json()

    with metric_dem.open("rb") as handle:
        uploaded = client.post(
            f"{PROJECTS}/{project['id']}/datasets",
            files={"file": (metric_dem.name, handle, "image/tiff")},
            data={"buffer_m": "1000"},
        )
    assert uploaded.status_code == 201, uploaded.text
    return dict(project)


def test_upload_requires_an_existing_dem(api_client: TestClient, metric_dem: Path) -> None:
    with rasterio.open(metric_dem) as dataset:
        left, bottom, right, top = dataset.bounds
        crs = dataset.crs.to_string()
    inner = box(left, bottom, right, top)
    area = dict(mapping(reproject_geometry(inner, crs, "EPSG:4326")))
    project = api_client.post(PROJECTS, json={"name": "No DEM yet", "area": area}).json()

    with metric_dem.open("rb") as handle:
        response = api_client.post(
            f"{PROJECTS}/{project['id']}/priorities",
            files={"file": (metric_dem.name, handle, "image/tiff")},
        )

    assert response.status_code == 422, response.text


def test_upload_aligns_the_raster_to_the_analysis_dem(
    api_client: TestClient, metric_dem: Path
) -> None:
    project = _create_project_with_dem(api_client, metric_dem)
    processed_dem = next(
        d
        for d in api_client.get(f"{PROJECTS}/{project['id']}/datasets").json()["items"]
        if d["role"] == "processed"
    )

    with metric_dem.open("rb") as handle:
        response = api_client.post(
            f"{PROJECTS}/{project['id']}/priorities",
            files={"file": ("risk.tif", handle, "image/tiff")},
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["raw"]["dataset_type"] == "priorities"
    assert body["raw"]["role"] == "raw"
    assert body["processed"]["dataset_type"] == "priorities"
    assert body["processed"]["role"] == "processed"
    assert body["processed"]["crs"] == processed_dem["crs"]
    assert body["processed"]["bounds"] == processed_dem["bounds"]
    assert body["processed"]["resolution_x"] == processed_dem["resolution_x"]
    assert body["processed"]["metadata"]["aligned_to_dataset_id"] == processed_dem["id"]


def test_upload_preview_is_downloadable(api_client: TestClient, metric_dem: Path) -> None:
    project = _create_project_with_dem(api_client, metric_dem)

    with metric_dem.open("rb") as handle:
        ingested = api_client.post(
            f"{PROJECTS}/{project['id']}/priorities",
            files={"file": ("risk.tif", handle, "image/tiff")},
        ).json()

    preview = api_client.get(ingested["preview_url"])

    assert preview.status_code == 200
    assert preview.headers["content-type"] == "image/png"


def test_rejects_a_non_geotiff_upload(api_client: TestClient, metric_dem: Path) -> None:
    project = _create_project_with_dem(api_client, metric_dem)

    response = api_client.post(
        f"{PROJECTS}/{project['id']}/priorities",
        files={"file": ("risk.txt", b"not a raster", "text/plain")},
    )

    assert response.status_code == 422, response.text
