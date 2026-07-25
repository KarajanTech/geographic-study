"""Reprojection and clipping preserve CRS, units and geometry."""

from __future__ import annotations

from pathlib import Path

import pytest
import rasterio
from shapely.geometry import box

from app.core.errors import InvalidInputError
from app.geo.area import StudyArea, reproject_geometry
from app.geo.raster import describe_raster
from app.geo.warp import DEFAULT_NODATA, clip_raster, reproject_raster


def test_reprojection_produces_a_metric_grid(geographic_dem: Path, tmp_path: Path) -> None:
    out = tmp_path / "reprojected.tif"

    result = reproject_raster(geographic_dem, out, "EPSG:25830")

    with rasterio.open(out) as dataset:
        assert dataset.crs.to_epsg() == 25830
        assert not dataset.crs.is_geographic
    # Cell size is now metres, so it is orders of magnitude above a degree value.
    assert result.resolution_m[0] > 1.0
    assert result.crs.endswith("25830")


def test_reprojection_preserves_the_footprint(geographic_dem: Path, tmp_path: Path) -> None:
    """The extent must describe the same patch of ground, within a cell."""
    source = describe_raster(geographic_dem)
    out = tmp_path / "reprojected.tif"

    result = reproject_raster(geographic_dem, out, "EPSG:25830")

    expected = reproject_geometry(box(*source.bounds.as_tuple()), "EPSG:4326", "EPSG:25830")
    tolerance = result.resolution_m[0] * 2
    assert result.bounds.left == pytest.approx(expected.bounds[0], abs=tolerance)
    assert result.bounds.right == pytest.approx(expected.bounds[2], abs=tolerance)
    assert result.bounds.top == pytest.approx(expected.bounds[3], abs=tolerance)


def test_reprojection_keeps_elevation_values_plausible(
    geographic_dem: Path, tmp_path: Path
) -> None:
    with rasterio.open(geographic_dem) as source:
        source_data = source.read(1, masked=True)

    out = tmp_path / "reprojected.tif"
    reproject_raster(geographic_dem, out, "EPSG:25830")

    with rasterio.open(out) as dataset:
        data = dataset.read(1, masked=True)

    # Bilinear resampling never invents values outside the source range.
    assert data.min() >= source_data.min() - 1.0
    assert data.max() <= source_data.max() + 1.0


def test_target_resolution_is_honoured(geographic_dem: Path, tmp_path: Path) -> None:
    out = tmp_path / "reprojected_100m.tif"

    result = reproject_raster(geographic_dem, out, "EPSG:25830", target_resolution_m=100.0)

    assert result.resolution_m == pytest.approx((100.0, 100.0))


def test_reprojecting_to_a_geographic_crs_is_refused(metric_dem: Path, tmp_path: Path) -> None:
    with pytest.raises(InvalidInputError):
        reproject_raster(metric_dem, tmp_path / "bad.tif", "EPSG:4326")


def test_reprojecting_a_raster_without_crs_is_refused(
    dem_without_crs: Path, tmp_path: Path
) -> None:
    with pytest.raises(InvalidInputError):
        reproject_raster(dem_without_crs, tmp_path / "bad.tif", "EPSG:25830")


def test_clip_bounds_match_the_geometry(
    metric_dem: Path, study_area: StudyArea, tmp_path: Path
) -> None:
    out = tmp_path / "clipped.tif"
    geometry = study_area.buffered_projected(0.0)

    result = clip_raster(metric_dem, out, geometry, geometry_crs=study_area.analysis_crs)

    minx, miny, maxx, maxy = geometry.bounds
    with rasterio.open(metric_dem) as source:
        cell = source.res[0]
    # Clipping snaps to the source grid, so allow one cell of slack.
    assert result.bounds.left == pytest.approx(minx, abs=cell)
    assert result.bounds.right == pytest.approx(maxx, abs=cell)
    assert result.bounds.bottom == pytest.approx(miny, abs=cell)
    assert result.bounds.top == pytest.approx(maxy, abs=cell)
    assert result.width < 160  # smaller than the full DEM


def test_clip_with_a_buffer_grows_the_extent(
    metric_dem: Path, study_area: StudyArea, tmp_path: Path
) -> None:
    tight = clip_raster(
        metric_dem,
        tmp_path / "tight.tif",
        study_area.buffered_projected(0.0),
        geometry_crs=study_area.analysis_crs,
    )
    buffered = clip_raster(
        metric_dem,
        tmp_path / "buffered.tif",
        study_area.buffered_projected(1_000.0),
        geometry_crs=study_area.analysis_crs,
    )

    assert buffered.bounds.width > tight.bounds.width
    assert buffered.width > tight.width


def test_clip_preserves_crs_resolution_and_nodata(
    metric_dem: Path, study_area: StudyArea, tmp_path: Path
) -> None:
    out = tmp_path / "clipped.tif"

    result = clip_raster(
        metric_dem,
        out,
        study_area.buffered_projected(500.0),
        geometry_crs=study_area.analysis_crs,
    )

    source = describe_raster(metric_dem)
    clipped = describe_raster(out)
    assert clipped.crs == source.crs
    assert clipped.resolution_x == pytest.approx(source.resolution_x)
    assert clipped.nodata == pytest.approx(DEFAULT_NODATA)
    assert clipped.units == "m"
    assert result.valid_cell_count > 0


def test_clip_refuses_a_geometry_in_another_crs(
    metric_dem: Path, study_area: StudyArea, tmp_path: Path
) -> None:
    """A mismatched CRS must fail loudly rather than be silently reprojected."""
    with pytest.raises(InvalidInputError) as excinfo:
        clip_raster(metric_dem, tmp_path / "bad.tif", study_area.geometry, geometry_crs="EPSG:4326")

    assert excinfo.value.details["geometry_crs"] == "EPSG:4326"


def test_clip_outside_the_raster_is_refused(metric_dem: Path, tmp_path: Path) -> None:
    elsewhere = box(0.0, 0.0, 1_000.0, 1_000.0)

    with pytest.raises(InvalidInputError):
        clip_raster(metric_dem, tmp_path / "bad.tif", elsewhere, geometry_crs="EPSG:25830")
