"""DEM ingestion pipeline.

The pipeline is a pure function of (raw file, study area, parameters): it takes
paths, returns paths and metadata, and knows nothing about HTTP or the
database. That is what lets Phase 3 move it into a worker without rewriting it.

    raw GeoTIFF
        -> describe + validate
        -> reproject to the analysis CRS
        -> clip to the study area plus a sight-range buffer
        -> hillshade
        -> PNG preview
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.geo.area import StudyArea
from app.geo.crs import require_metric_crs
from app.geo.preview import PreviewResult, write_png_preview
from app.geo.raster import RasterMetadata, describe_raster
from app.geo.terrain import write_hillshade
from app.geo.validation import ValidationReport, validate_dem
from app.geo.warp import WarpResult, clip_raster, reproject_raster

_log = get_logger(__name__)

# Default sight range used to buffer the clip. A Sentinel sees terrain well
# beyond the study area, so the surface model must extend past its edge.
DEFAULT_BUFFER_M = 15_000.0
MAX_BUFFER_M = 50_000.0

ANALYSIS_DEM_NAME = "dem_analysis.tif"
HILLSHADE_NAME = "hillshade.tif"
PREVIEW_NAME = "preview.png"
HILLSHADE_PREVIEW_NAME = "hillshade_preview.png"


@dataclass(frozen=True, slots=True)
class IngestionParameters:
    """Everything that determines the output, stored with the result."""

    buffer_m: float = DEFAULT_BUFFER_M
    target_resolution_m: float | None = None

    def validated(self) -> IngestionParameters:
        from app.core.errors import InvalidInputError

        if not 0.0 <= self.buffer_m <= MAX_BUFFER_M:
            msg = f"Clip buffer must be between 0 and {MAX_BUFFER_M:.0f} m"
            raise InvalidInputError(msg, details={"buffer_m": self.buffer_m})
        if self.target_resolution_m is not None and not 0.1 <= self.target_resolution_m <= 500.0:
            msg = "Target resolution must be between 0.1 and 500 m"
            raise InvalidInputError(msg, details={"target_resolution_m": self.target_resolution_m})
        return self

    def as_dict(self) -> dict[str, Any]:
        return {"buffer_m": self.buffer_m, "target_resolution_m": self.target_resolution_m}


@dataclass(frozen=True, slots=True)
class IngestionResult:
    """Products of a successful ingestion, with full provenance."""

    source_metadata: RasterMetadata
    validation: ValidationReport
    analysis_dem: WarpResult
    analysis_metadata: RasterMetadata
    hillshade_path: Path
    preview: PreviewResult
    hillshade_preview: PreviewResult
    parameters: IngestionParameters
    processing_history: list[dict[str, Any]] = field(default_factory=list)
    runtime_seconds: float = 0.0


def ingest_dem(
    raw_path: Path,
    output_dir: Path,
    study_area: StudyArea,
    parameters: IngestionParameters | None = None,
) -> IngestionResult:
    """Turn an uploaded DEM into the analysis-ready surface for a study area.

    Args:
        raw_path: The immutable upload. Only ever read.
        output_dir: Directory for derived products.
        study_area: Validated study area; supplies the analysis CRS.
        parameters: Buffer and target resolution.

    Raises:
        InvalidInputError: when the DEM fails validation or a step cannot run.
    """
    params = (parameters or IngestionParameters()).validated()
    started = time.perf_counter()
    history: list[dict[str, Any]] = []

    source_metadata = describe_raster(raw_path)
    report = validate_dem(source_metadata, study_area)
    report.raise_if_failed()
    history.append(
        {
            "step": "validate",
            "source_crs": source_metadata.crs,
            "source_units": source_metadata.units,
            "source_resolution": [source_metadata.resolution_x, source_metadata.resolution_y],
            "coverage_ratio": report.coverage_ratio,
            "warnings": [w.code for w in report.warnings],
        }
    )

    analysis_crs = study_area.analysis_crs
    require_metric_crs(analysis_crs)
    output_dir.mkdir(parents=True, exist_ok=True)

    reprojected_path = output_dir / f"reprojected_{ANALYSIS_DEM_NAME}"
    reprojected = reproject_raster(
        raw_path,
        reprojected_path,
        analysis_crs,
        target_resolution_m=params.target_resolution_m,
    )
    history.append(
        {
            "step": "reproject",
            "from_crs": source_metadata.crs,
            "to_crs": analysis_crs,
            "resolution_m": list(reprojected.resolution_m),
            "resampling": "bilinear",
        }
    )

    clip_geometry = study_area.buffered_projected(params.buffer_m)
    analysis_path = output_dir / ANALYSIS_DEM_NAME
    clipped = clip_raster(reprojected_path, analysis_path, clip_geometry, geometry_crs=analysis_crs)
    history.append(
        {
            "step": "clip",
            "buffer_m": params.buffer_m,
            "bounds_m": list(clipped.bounds.as_tuple()),
            "size": [clipped.width, clipped.height],
            "valid_ratio": round(clipped.valid_ratio, 6),
        }
    )
    # The intermediate reprojection is not a product; only the clipped surface is.
    reprojected_path.unlink(missing_ok=True)

    hillshade = write_hillshade(analysis_path, output_dir / HILLSHADE_NAME)
    history.append(
        {
            "step": "hillshade",
            "azimuth_deg": hillshade.azimuth_deg,
            "altitude_deg": hillshade.altitude_deg,
        }
    )

    preview = write_png_preview(analysis_path, output_dir / PREVIEW_NAME)
    hillshade_preview = write_png_preview(hillshade.path, output_dir / HILLSHADE_PREVIEW_NAME)
    history.append({"step": "preview", "size_px": [preview.width, preview.height]})

    runtime = time.perf_counter() - started
    _log.info(
        "dem_ingested",
        analysis_crs=analysis_crs,
        buffer_m=params.buffer_m,
        output_size=[clipped.width, clipped.height],
        resolution_m=clipped.resolution_m,
        valid_ratio=round(clipped.valid_ratio, 4),
        runtime_seconds=round(runtime, 3),
    )

    return IngestionResult(
        source_metadata=source_metadata,
        validation=report,
        analysis_dem=clipped,
        analysis_metadata=describe_raster(analysis_path),
        hillshade_path=hillshade.path,
        preview=preview,
        hillshade_preview=hillshade_preview,
        parameters=params,
        processing_history=history,
        runtime_seconds=runtime,
    )
