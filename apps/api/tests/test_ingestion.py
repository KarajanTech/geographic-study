"""The DEM ingestion pipeline, exercised without HTTP or a database."""

from __future__ import annotations

from pathlib import Path

import pytest
import rasterio

from app.core.errors import InvalidInputError
from app.geo.area import StudyArea
from app.services.ingestion import IngestionParameters, ingest_dem


def test_pipeline_produces_an_analysis_surface(
    metric_dem: Path, study_area: StudyArea, tmp_path: Path
) -> None:
    result = ingest_dem(metric_dem, tmp_path / "out", study_area)

    assert result.analysis_dem.path.is_file()
    assert result.hillshade_path.is_file()
    assert result.preview.path.is_file()
    assert result.hillshade_preview.path.is_file()
    assert result.validation.ok


def test_output_is_in_the_analysis_crs_with_metric_units(
    geographic_dem: Path, tmp_path: Path
) -> None:
    """A DEM uploaded in degrees comes out projected in metres."""
    from app.geo.area import parse_study_area

    area = parse_study_area(
        {
            "type": "Polygon",
            "coordinates": [
                [
                    [-3.74, 40.37],
                    [-3.68, 40.37],
                    [-3.68, 40.43],
                    [-3.74, 40.43],
                    [-3.74, 40.37],
                ]
            ],
        }
    )

    result = ingest_dem(geographic_dem, tmp_path / "out", area, IngestionParameters(buffer_m=500.0))

    assert result.source_metadata.units == "degree"
    assert result.analysis_metadata.units == "m"
    assert result.analysis_metadata.crs is not None
    assert result.analysis_metadata.crs.endswith(area.analysis_crs.split(":")[-1])


def test_clip_extends_past_the_study_area_by_the_buffer(
    metric_dem: Path, study_area: StudyArea, tmp_path: Path
) -> None:
    tight = ingest_dem(
        metric_dem, tmp_path / "tight", study_area, IngestionParameters(buffer_m=0.0)
    )
    wide = ingest_dem(
        metric_dem, tmp_path / "wide", study_area, IngestionParameters(buffer_m=1_000.0)
    )

    assert wide.analysis_dem.bounds.width > tight.analysis_dem.bounds.width
    # And never beyond the source DEM: there is no elevation data out there.
    with rasterio.open(metric_dem) as source:
        assert wide.analysis_dem.bounds.left >= source.bounds.left - 1.0
        assert wide.analysis_dem.bounds.right <= source.bounds.right + 1.0


def test_target_resolution_resamples_the_output(
    metric_dem: Path, study_area: StudyArea, tmp_path: Path
) -> None:
    result = ingest_dem(
        metric_dem,
        tmp_path / "out",
        study_area,
        IngestionParameters(buffer_m=0.0, target_resolution_m=100.0),
    )

    assert result.analysis_dem.resolution_m == pytest.approx((100.0, 100.0))


def test_processing_history_records_every_step(
    metric_dem: Path, study_area: StudyArea, tmp_path: Path
) -> None:
    result = ingest_dem(metric_dem, tmp_path / "out", study_area)

    steps = [entry["step"] for entry in result.processing_history]
    assert steps == ["validate", "reproject", "clip", "hillshade", "preview"]
    clip_step = next(e for e in result.processing_history if e["step"] == "clip")
    assert clip_step["buffer_m"] == pytest.approx(15_000.0)
    reproject_step = next(e for e in result.processing_history if e["step"] == "reproject")
    assert reproject_step["to_crs"] == study_area.analysis_crs


def test_the_raw_file_is_never_modified(
    metric_dem: Path, study_area: StudyArea, tmp_path: Path
) -> None:
    from app.core.checksum import sha256_file

    before = sha256_file(metric_dem)
    ingest_dem(metric_dem, tmp_path / "out", study_area)

    assert sha256_file(metric_dem) == before


def test_pipeline_is_reproducible(metric_dem: Path, study_area: StudyArea, tmp_path: Path) -> None:
    from app.core.checksum import sha256_file

    first = ingest_dem(metric_dem, tmp_path / "a", study_area)
    second = ingest_dem(metric_dem, tmp_path / "b", study_area)

    assert sha256_file(first.analysis_dem.path) == sha256_file(second.analysis_dem.path)
    assert first.analysis_dem.bounds == second.analysis_dem.bounds


def test_intermediate_reprojection_is_cleaned_up(
    metric_dem: Path, study_area: StudyArea, tmp_path: Path
) -> None:
    output = tmp_path / "out"
    ingest_dem(metric_dem, output, study_area)

    assert not list(output.glob("reprojected_*"))


def test_ungeoreferenced_dem_is_rejected(
    dem_without_crs: Path, study_area: StudyArea, tmp_path: Path
) -> None:
    with pytest.raises(InvalidInputError) as excinfo:
        ingest_dem(dem_without_crs, tmp_path / "out", study_area)

    assert excinfo.value.details["code"] == "missing_crs"


def test_dem_that_does_not_overlap_is_rejected(metric_dem: Path, tmp_path: Path) -> None:
    from app.geo.area import parse_study_area

    elsewhere = parse_study_area(
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

    with pytest.raises(InvalidInputError) as excinfo:
        ingest_dem(metric_dem, tmp_path / "out", elsewhere)

    assert excinfo.value.details["code"] == "no_intersection"


@pytest.mark.parametrize("buffer_m", [-1.0, 100_000.0])
def test_out_of_range_buffer_is_rejected(
    metric_dem: Path, study_area: StudyArea, tmp_path: Path, buffer_m: float
) -> None:
    with pytest.raises(InvalidInputError):
        ingest_dem(metric_dem, tmp_path / "out", study_area, IngestionParameters(buffer_m=buffer_m))


def test_out_of_range_resolution_is_rejected(
    metric_dem: Path, study_area: StudyArea, tmp_path: Path
) -> None:
    with pytest.raises(InvalidInputError):
        ingest_dem(
            metric_dem,
            tmp_path / "out",
            study_area,
            IngestionParameters(target_resolution_m=5_000.0),
        )
