"""The sample DEM is metric, reproducible and correctly georeferenced."""

from __future__ import annotations

from pathlib import Path

import pytest
import rasterio
from rasterio.crs import CRS

from app.core.checksum import sha256_file
from app.core.errors import InvalidInputError
from app.geo.sample_dem import NODATA_VALUE, SyntheticDemSpec, write_synthetic_dem

SMALL = SyntheticDemSpec(width=64, height=48, resolution_m=25.0)


def test_written_crs_is_projected_and_metric(tmp_path: Path) -> None:
    result = write_synthetic_dem(tmp_path / "dem.tif", SMALL)

    with rasterio.open(result.path) as dataset:
        assert dataset.crs is not None
        assert not dataset.crs.is_geographic
        assert dataset.crs.linear_units.lower() in {"metre", "meter", "m"}


def test_geotransform_matches_the_requested_grid(tmp_path: Path) -> None:
    result = write_synthetic_dem(tmp_path / "dem.tif", SMALL)

    with rasterio.open(result.path) as dataset:
        assert dataset.width == SMALL.width
        assert dataset.height == SMALL.height
        assert dataset.res == pytest.approx((SMALL.resolution_m, SMALL.resolution_m))
        # Bounds follow from origin, size and resolution, in metres.
        assert dataset.bounds.left == pytest.approx(SMALL.origin_x_m)
        assert dataset.bounds.top == pytest.approx(SMALL.origin_y_m)
        assert dataset.bounds.right == pytest.approx(
            SMALL.origin_x_m + SMALL.width * SMALL.resolution_m
        )
        assert dataset.bounds.bottom == pytest.approx(
            SMALL.origin_y_m - SMALL.height * SMALL.resolution_m
        )


def test_pixel_centre_round_trips_through_the_transform(tmp_path: Path) -> None:
    """Row/col to map coordinates and back must be stable."""
    result = write_synthetic_dem(tmp_path / "dem.tif", SMALL)

    with rasterio.open(result.path) as dataset:
        x, y = dataset.xy(10, 20)  # centre of row 10, column 20
        row, col = dataset.index(x, y)

    assert (row, col) == (10, 20)
    assert x == pytest.approx(SMALL.origin_x_m + (20 + 0.5) * SMALL.resolution_m)
    assert y == pytest.approx(SMALL.origin_y_m - (10 + 0.5) * SMALL.resolution_m)


def test_nodata_and_units_are_declared(tmp_path: Path) -> None:
    result = write_synthetic_dem(tmp_path / "dem.tif", SMALL)

    with rasterio.open(result.path) as dataset:
        assert dataset.nodata == NODATA_VALUE
        tags = dataset.tags()

    assert tags["units"] == "m"
    assert tags["source"] == "synthetic"
    assert result.units == "m"


def test_generation_is_deterministic_for_a_seed(tmp_path: Path) -> None:
    first = write_synthetic_dem(tmp_path / "a.tif", SMALL)
    second = write_synthetic_dem(tmp_path / "b.tif", SMALL)

    assert first.checksum_sha256 == second.checksum_sha256
    assert first.checksum_sha256 == sha256_file(first.path)


def test_a_different_seed_changes_the_terrain(tmp_path: Path) -> None:
    other = SMALL.model_copy(update={"seed": SMALL.seed + 1})

    first = write_synthetic_dem(tmp_path / "a.tif", SMALL)
    second = write_synthetic_dem(tmp_path / "b.tif", other)

    assert first.checksum_sha256 != second.checksum_sha256


def test_elevation_values_stay_in_a_plausible_range(tmp_path: Path) -> None:
    result = write_synthetic_dem(tmp_path / "dem.tif", SMALL)

    assert result.min_elevation_m > -100.0
    assert result.max_elevation_m < 4000.0
    assert result.max_elevation_m > result.min_elevation_m


def test_geographic_crs_is_rejected(tmp_path: Path) -> None:
    spec = SMALL.model_copy(update={"crs": "EPSG:4326"})

    with pytest.raises(InvalidInputError) as excinfo:
        write_synthetic_dem(tmp_path / "dem.tif", spec)

    assert excinfo.value.details["crs"] == "EPSG:4326"


def test_non_metre_projected_crs_is_rejected(tmp_path: Path) -> None:
    # NAD83 / Texas Central (ftUS): projected, but the linear unit is feet.
    spec = SMALL.model_copy(update={"crs": "EPSG:2277"})
    assert not CRS.from_user_input("EPSG:2277").is_geographic

    with pytest.raises(InvalidInputError):
        write_synthetic_dem(tmp_path / "dem.tif", spec)
