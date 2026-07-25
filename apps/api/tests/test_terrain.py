"""Hillshade and preview rendering."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import rasterio

from app.core.errors import InvalidInputError
from app.geo.preview import write_png_preview
from app.geo.terrain import HILLSHADE_NODATA, compute_hillshade, write_hillshade


def test_flat_terrain_shades_uniformly() -> None:
    flat = np.full((16, 16), 500.0, dtype=np.float32)

    shade = compute_hillshade(flat, resolution_x_m=25.0, resolution_y_m=25.0)

    assert shade.min() == shade.max()
    # cos(zenith) for a 45 degree sun, scaled to 1-255.
    assert shade[0, 0] == pytest.approx(round(np.cos(np.radians(45)) * 254 + 1), abs=1)


def test_a_slope_facing_the_sun_is_brighter_than_one_facing_away() -> None:
    """With the default sun in the north-west, west slopes are lit."""
    size = 32
    columns = np.arange(size, dtype=np.float32)
    west_facing = np.tile(columns * 10.0, (size, 1))  # rises to the east
    east_facing = np.tile(columns[::-1] * 10.0, (size, 1))  # rises to the west

    lit = compute_hillshade(west_facing, resolution_x_m=25.0, resolution_y_m=25.0)
    shadowed = compute_hillshade(east_facing, resolution_x_m=25.0, resolution_y_m=25.0)

    assert lit.mean() > shadowed.mean()


def test_steeper_terrain_produces_more_contrast() -> None:
    size = 32
    gentle = np.tile(np.arange(size, dtype=np.float32) * 1.0, (size, 1))
    steep = np.tile(np.arange(size, dtype=np.float32) * 50.0, (size, 1))

    gentle_shade = compute_hillshade(gentle, resolution_x_m=25.0, resolution_y_m=25.0)
    steep_shade = compute_hillshade(steep, resolution_x_m=25.0, resolution_y_m=25.0)

    assert abs(int(steep_shade.mean()) - 128) > abs(int(gentle_shade.mean()) - 128)


def test_cell_size_changes_the_result() -> None:
    """The same elevations over smaller cells mean steeper ground."""
    ramp = np.tile(np.arange(32, dtype=np.float32) * 10.0, (32, 1))

    coarse = compute_hillshade(ramp, resolution_x_m=100.0, resolution_y_m=100.0)
    fine = compute_hillshade(ramp, resolution_x_m=10.0, resolution_y_m=10.0)

    assert coarse.mean() != fine.mean()


def test_hillshade_is_deterministic(metric_dem: Path) -> None:
    with rasterio.open(metric_dem) as dataset:
        elevation = dataset.read(1)

    first = compute_hillshade(elevation, resolution_x_m=50.0, resolution_y_m=50.0)
    second = compute_hillshade(elevation, resolution_x_m=50.0, resolution_y_m=50.0)

    assert np.array_equal(first, second)


def test_zero_cell_size_is_rejected() -> None:
    with pytest.raises(InvalidInputError):
        compute_hillshade(
            np.zeros((4, 4), dtype=np.float32), resolution_x_m=0.0, resolution_y_m=25.0
        )


def test_written_hillshade_keeps_georeferencing(metric_dem: Path, tmp_path: Path) -> None:
    out = tmp_path / "hillshade.tif"

    write_hillshade(metric_dem, out)

    with rasterio.open(metric_dem) as source, rasterio.open(out) as shade:
        assert shade.crs == source.crs
        assert shade.transform == source.transform
        assert shade.width == source.width
        assert shade.height == source.height
        assert shade.dtypes[0] == "uint8"
        assert shade.nodata == HILLSHADE_NODATA
        assert shade.tags()["processing"] == "hillshade"


def test_hillshade_needs_a_metric_crs(geographic_dem: Path, tmp_path: Path) -> None:
    with pytest.raises(InvalidInputError):
        write_hillshade(geographic_dem, tmp_path / "bad.tif")


def test_preview_is_a_png_with_geographic_bounds(metric_dem: Path, tmp_path: Path) -> None:
    out = tmp_path / "preview.png"

    result = write_png_preview(metric_dem, out)

    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert result.width <= 1024
    assert result.height <= 1024
    assert -10.0 < result.bounds_wgs84.left < 5.0
    assert 35.0 < result.bounds_wgs84.bottom < 45.0
    assert result.source_crs.endswith("25830")


def test_preview_is_downsampled_but_keeps_the_aspect_ratio(
    metric_dem: Path, tmp_path: Path
) -> None:
    result = write_png_preview(metric_dem, tmp_path / "small.png", max_size_px=64)

    assert max(result.width, result.height) == 64
    assert result.width == result.height  # the fixture DEM is square


def test_preview_marks_nodata_as_transparent(
    metric_dem: Path, study_area: object, tmp_path: Path
) -> None:
    from app.geo.warp import clip_raster

    clipped = tmp_path / "clipped.tif"
    # A circular clip leaves nodata in the corners.
    geometry = study_area.projected().centroid.buffer(1_000.0)  # type: ignore[attr-defined]
    clip_raster(metric_dem, clipped, geometry, geometry_crs="EPSG:25830")

    result = write_png_preview(clipped, tmp_path / "preview.png")

    with rasterio.open(result.path) as png:
        alpha = png.read(2)
    assert alpha.min() == 0  # transparent corners
    assert alpha.max() == 255  # opaque data
