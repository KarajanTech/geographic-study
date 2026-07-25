"""Raster description records everything the roadmap requires."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.checksum import sha256_file
from app.core.errors import InvalidInputError
from app.geo.raster import describe_raster, metadata_to_storage_dict


def test_metric_raster_is_fully_described(metric_dem: Path) -> None:
    metadata = describe_raster(metric_dem)

    assert metadata.crs is not None
    assert "25830" in metadata.crs
    assert metadata.is_projected
    assert metadata.is_metric
    assert metadata.units == "m"
    assert metadata.resolution_x == pytest.approx(50.0)
    assert metadata.resolution_y == pytest.approx(50.0)
    assert metadata.nodata == pytest.approx(-9999.0)
    assert metadata.band_count == 1
    assert metadata.dtype == "float32"
    assert metadata.checksum_sha256 == sha256_file(metric_dem)
    assert metadata.size_bytes > 0


def test_bounds_are_reported_in_the_native_crs(metric_dem: Path) -> None:
    metadata = describe_raster(metric_dem)

    # 160 cells x 50 m = 8 km, in metres, not degrees.
    assert metadata.bounds.width == pytest.approx(8_000.0)
    assert metadata.bounds.height == pytest.approx(8_000.0)
    assert metadata.bounds.left == pytest.approx(400_000.0)


def test_wgs84_bounds_are_added_for_display(metric_dem: Path) -> None:
    metadata = describe_raster(metric_dem)

    assert metadata.bounds_wgs84 is not None
    assert -10.0 < metadata.bounds_wgs84.left < 5.0
    assert 35.0 < metadata.bounds_wgs84.bottom < 45.0


def test_geographic_raster_is_described_as_degrees(geographic_dem: Path) -> None:
    metadata = describe_raster(geographic_dem)

    assert metadata.units == "degree"
    assert not metadata.is_metric
    assert metadata.resolution_x == pytest.approx(0.001)


def test_raster_without_crs_reports_no_crs(dem_without_crs: Path) -> None:
    metadata = describe_raster(dem_without_crs)

    assert metadata.crs is None
    assert metadata.units == "unknown"
    assert metadata.bounds_wgs84 is None


def test_non_raster_file_is_rejected(tmp_path: Path) -> None:
    fake = tmp_path / "notes.tif"
    fake.write_text("this is not a GeoTIFF")

    with pytest.raises(InvalidInputError):
        describe_raster(fake)


def test_storage_dict_is_json_serialisable(metric_dem: Path) -> None:
    import json

    payload = metadata_to_storage_dict(describe_raster(metric_dem))

    assert json.loads(json.dumps(payload))["dtype"] == "float32"
