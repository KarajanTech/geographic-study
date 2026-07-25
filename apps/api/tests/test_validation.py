"""DEM validation rules."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from app.core.errors import InvalidInputError
from app.geo.area import StudyArea, parse_study_area
from app.geo.raster import describe_raster
from app.geo.validation import validate_dem


def test_valid_dem_passes(metric_dem: Path, study_area: StudyArea) -> None:
    report = validate_dem(describe_raster(metric_dem), study_area)

    assert report.ok
    assert report.errors == []
    assert report.coverage_ratio is not None
    assert report.coverage_ratio > 0.99


def test_dem_without_crs_is_rejected(dem_without_crs: Path, study_area: StudyArea) -> None:
    report = validate_dem(describe_raster(dem_without_crs), study_area)

    assert not report.ok
    assert next(issue.code for issue in report.errors) == "missing_crs"

    with pytest.raises(InvalidInputError) as excinfo:
        report.raise_if_failed()
    assert excinfo.value.details["code"] == "missing_crs"


def test_geographic_dem_is_accepted_for_ingestion(geographic_dem: Path) -> None:
    """A DEM in degrees is valid input; it is reprojected before any measurement."""
    area = parse_study_area(
        {
            "type": "Polygon",
            "coordinates": [
                [
                    [-3.74, 40.36],
                    [-3.66, 40.36],
                    [-3.66, 40.44],
                    [-3.74, 40.44],
                    [-3.74, 40.36],
                ]
            ],
        }
    )

    report = validate_dem(describe_raster(geographic_dem), area)

    assert [issue.code for issue in report.errors] == []


def test_dem_elsewhere_in_the_world_is_rejected(metric_dem: Path) -> None:
    far_away = parse_study_area(
        {
            "type": "Polygon",
            "coordinates": [
                [
                    [-58.45, -34.65],
                    [-58.35, -34.65],
                    [-58.35, -34.55],
                    [-58.45, -34.55],
                    [-58.45, -34.65],
                ]
            ],
        }
    )

    report = validate_dem(describe_raster(metric_dem), far_away)

    assert not report.ok
    assert [issue.code for issue in report.errors] == ["no_intersection"]
    assert report.coverage_ratio == 0.0


def test_partial_coverage_is_a_warning_not_an_error(
    metric_dem: Path, study_area: StudyArea
) -> None:
    """A study area sticking out of the DEM still ingests, with a warning."""
    minx, miny, maxx, maxy = study_area.geometry.bounds
    shifted = {
        "type": "Polygon",
        "coordinates": [
            [
                [minx + (maxx - minx) * 0.6, miny],
                [maxx + (maxx - minx) * 0.6, miny],
                [maxx + (maxx - minx) * 0.6, maxy],
                [minx + (maxx - minx) * 0.6, maxy],
                [minx + (maxx - minx) * 0.6, miny],
            ]
        ],
    }
    report = validate_dem(describe_raster(metric_dem), parse_study_area(shifted))

    assert report.ok
    assert "partial_coverage" in [w.code for w in report.warnings]
    assert report.coverage_ratio is not None
    assert 0.5 <= report.coverage_ratio < 1.0


def test_missing_nodata_is_a_warning(tmp_path: Path, study_area: StudyArea) -> None:
    path = tmp_path / "no_nodata.tif"
    minx, _, _, maxy = study_area.projected().bounds
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=64,
        height=64,
        count=1,
        dtype="float32",
        crs="EPSG:25830",
        transform=from_origin(minx, maxy, 50.0, 50.0),
    ) as dataset:
        dataset.write(np.full((64, 64), 700.0, dtype=np.float32), 1)

    report = validate_dem(describe_raster(path), study_area)

    assert "missing_nodata" in [w.code for w in report.warnings]


def test_implausible_resolution_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "coarse.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=16,
        height=16,
        count=1,
        dtype="float32",
        crs="EPSG:25830",
        # 5 km cells: far too coarse to site a tower.
        transform=from_origin(400_000.0, 4_500_000.0, 5_000.0, 5_000.0),
        nodata=-9999.0,
    ) as dataset:
        dataset.write(np.full((16, 16), 700.0, dtype=np.float32), 1)

    report = validate_dem(describe_raster(path))

    assert not report.ok
    assert [issue.code for issue in report.errors] == ["implausible_resolution"]


def test_validation_without_a_study_area_checks_the_file_only(metric_dem: Path) -> None:
    report = validate_dem(describe_raster(metric_dem))

    assert report.ok
    assert report.coverage_ratio is None
