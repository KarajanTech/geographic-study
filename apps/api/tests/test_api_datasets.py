"""DEM upload and ingestion over HTTP. Requires PostGIS; skipped when absent."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import rasterio
from fastapi.testclient import TestClient

from app.api.router import API_V1_PREFIX
from app.core.checksum import sha256_file
from app.core.config import Settings

PROJECTS = f"{API_V1_PREFIX}/projects"
DATASETS = f"{API_V1_PREFIX}/datasets"


def _create_project(
    client: TestClient, metric_dem: Path, name: str = "Ingestion"
) -> dict[str, Any]:
    """A project whose study area sits inside ``metric_dem``."""
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


def test_upload_produces_raw_and_processed_datasets(
    api_client: TestClient, metric_dem: Path
) -> None:
    project = _create_project(api_client, metric_dem)

    response = _upload(api_client, project["id"], metric_dem)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["raw"]["role"] == "raw"
    assert body["raw"]["status"] == "ready"
    assert body["processed"]["role"] == "processed"
    assert body["processed"]["status"] == "ready"
    assert body["processed"]["derived_from_id"] == body["raw"]["id"]
    assert body["validation"]["ok"]


def test_stored_metadata_covers_crs_bounds_resolution_and_checksum(
    api_client: TestClient, metric_dem: Path
) -> None:
    project = _create_project(api_client, metric_dem)

    body = _upload(api_client, project["id"], metric_dem).json()

    raw = body["raw"]
    assert raw["checksum_sha256"] == sha256_file(metric_dem)
    assert raw["crs"] is not None and "25830" in raw["crs"]
    assert raw["units"] == "m"
    assert raw["resolution_x"] == 50.0
    assert raw["nodata"] == -9999.0
    assert raw["bounds"]["crs"] == raw["crs"]
    assert raw["bounds"]["units"] == "m"
    assert raw["bounds"]["right"] - raw["bounds"]["left"] == 8000.0
    assert raw["bounds_wgs84"]["west"] < raw["bounds_wgs84"]["east"]


def test_processed_dataset_is_in_the_project_analysis_crs(
    api_client: TestClient, metric_dem: Path
) -> None:
    project = _create_project(api_client, metric_dem)

    body = _upload(api_client, project["id"], metric_dem).json()

    processed = body["processed"]
    assert processed["crs"] is not None
    assert project["analysis_crs"].split(":")[-1] in processed["crs"]
    assert processed["units"] == "m"
    assert processed["metadata"]["analysis_crs"] == project["analysis_crs"]


def test_processing_history_is_persisted(api_client: TestClient, metric_dem: Path) -> None:
    project = _create_project(api_client, metric_dem)

    body = _upload(api_client, project["id"], metric_dem, buffer_m=500.0).json()

    steps = [entry["step"] for entry in body["processed"]["processing_history"]]
    assert steps == ["validate", "reproject", "clip", "hillshade", "preview"]
    clip = next(e for e in body["processed"]["processing_history"] if e["step"] == "clip")
    assert clip["buffer_m"] == 500.0


def test_raw_upload_is_stored_untouched(
    api_client: TestClient, metric_dem: Path, settings: Settings
) -> None:
    project = _create_project(api_client, metric_dem)

    body = _upload(api_client, project["id"], metric_dem).json()

    stored = list(settings.raw_dir.rglob("*.tif"))
    assert len(stored) == 1
    assert sha256_file(stored[0]) == sha256_file(metric_dem)
    assert body["raw"]["original_filename"] == metric_dem.name
    # Immutable on disk: no write permission.
    assert not stored[0].stat().st_mode & 0o222


def test_derived_products_are_written_to_the_processed_directory(
    api_client: TestClient, metric_dem: Path, settings: Settings
) -> None:
    project = _create_project(api_client, metric_dem)

    _upload(api_client, project["id"], metric_dem)

    names = {path.name for path in settings.processed_dir.rglob("*") if path.is_file()}
    assert names == {"dem_analysis.tif", "hillshade.tif", "preview.png", "hillshade_preview.png"}


def test_preview_endpoint_serves_a_png(api_client: TestClient, metric_dem: Path) -> None:
    project = _create_project(api_client, metric_dem)
    body = _upload(api_client, project["id"], metric_dem).json()

    response = api_client.get(body["preview_url"])

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_preview_bounds_place_the_image_on_the_map(
    api_client: TestClient, metric_dem: Path
) -> None:
    project = _create_project(api_client, metric_dem)

    bounds = _upload(api_client, project["id"], metric_dem).json()["preview_bounds_wgs84"]

    assert -180.0 <= bounds["west"] < bounds["east"] <= 180.0
    assert -90.0 <= bounds["south"] < bounds["north"] <= 90.0
    assert -10.0 < bounds["west"] < 5.0
    assert 35.0 < bounds["south"] < 45.0


def test_geotiff_download_returns_the_analysis_surface(
    api_client: TestClient, metric_dem: Path
) -> None:
    project = _create_project(api_client, metric_dem)
    body = _upload(api_client, project["id"], metric_dem).json()

    response = api_client.get(f"{DATASETS}/{body['processed']['id']}/download.tif")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/tiff"


def test_datasets_are_listed_for_the_project(api_client: TestClient, metric_dem: Path) -> None:
    project = _create_project(api_client, metric_dem)
    _upload(api_client, project["id"], metric_dem)

    body = api_client.get(f"{PROJECTS}/{project['id']}/datasets").json()

    assert body["total"] == 2
    assert {item["role"] for item in body["items"]} == {"raw", "processed"}

    processed_only = api_client.get(
        f"{PROJECTS}/{project['id']}/datasets", params={"role": "processed"}
    ).json()
    assert processed_only["total"] == 1


def test_revalidating_a_stored_dataset_reports_coverage(
    api_client: TestClient, metric_dem: Path
) -> None:
    project = _create_project(api_client, metric_dem)
    body = _upload(api_client, project["id"], metric_dem).json()

    response = api_client.post(f"{DATASETS}/{body['raw']['id']}/validate")

    assert response.status_code == 200
    assert response.json()["ok"]
    assert response.json()["coverage_ratio"] > 0.99


def test_ungeoreferenced_upload_is_rejected(
    api_client: TestClient, metric_dem: Path, dem_without_crs: Path
) -> None:
    project = _create_project(api_client, metric_dem)

    response = _upload(api_client, project["id"], dem_without_crs)

    assert response.status_code == 422
    assert response.json()["error"]["details"]["code"] == "missing_crs"


def test_non_raster_upload_is_rejected(
    api_client: TestClient, metric_dem: Path, tmp_path: Path
) -> None:
    project = _create_project(api_client, metric_dem)
    text_file = tmp_path / "notes.txt"
    text_file.write_text("not a raster")

    with text_file.open("rb") as handle:
        response = api_client.post(
            f"{PROJECTS}/{project['id']}/datasets",
            files={"file": ("notes.txt", handle, "text/plain")},
        )

    assert response.status_code == 422
    assert "Unsupported file type" in response.json()["error"]["message"]


def test_upload_to_an_unknown_project_returns_404(api_client: TestClient, metric_dem: Path) -> None:
    response = _upload(api_client, "00000000-0000-0000-0000-000000000000", metric_dem)

    assert response.status_code == 404


def test_out_of_range_buffer_is_rejected(api_client: TestClient, metric_dem: Path) -> None:
    project = _create_project(api_client, metric_dem)

    response = _upload(api_client, project["id"], metric_dem, buffer_m=999_999.0)

    assert response.status_code == 422


def test_dataset_count_is_reported_on_the_project(api_client: TestClient, metric_dem: Path) -> None:
    project = _create_project(api_client, metric_dem)
    _upload(api_client, project["id"], metric_dem)

    assert api_client.get(f"{PROJECTS}/{project['id']}").json()["dataset_count"] == 2
