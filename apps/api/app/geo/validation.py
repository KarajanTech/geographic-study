"""DEM validation.

A dataset that reaches the pipeline unvalidated produces plausible, wrong
results. Everything checked here is a hard requirement of the roadmap:
georeferencing, nodata, resolution and intersection with the study area.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from shapely.geometry import box
from shapely.geometry.base import BaseGeometry

from app.core.errors import InvalidInputError
from app.geo.area import StudyArea, reproject_geometry
from app.geo.crs import WGS84
from app.geo.raster import RasterMetadata

# A DEM coarser than this cannot support tower siting; finer than this in
# degrees means the file is almost certainly mislabelled.
MAX_RESOLUTION_M = 500.0
MIN_RESOLUTION_M = 0.1
MAX_RESOLUTION_DEG = 0.05
MIN_RESOLUTION_DEG = 1e-6

# Minimum share of the study area that must be covered by the DEM.
MIN_COVERAGE_RATIO = 0.5


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Outcome of validating a dataset against a study area."""

    ok: bool
    errors: list[ValidationIssue] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)
    coverage_ratio: float | None = None

    def raise_if_failed(self) -> None:
        if self.ok:
            return
        first = self.errors[0]
        raise InvalidInputError(
            first.message,
            details={
                "code": first.code,
                "errors": [{"code": e.code, "message": e.message} for e in self.errors],
                "warnings": [{"code": w.code, "message": w.message} for w in self.warnings],
            },
        )


def raster_footprint_wgs84(metadata: RasterMetadata) -> BaseGeometry | None:
    """The raster extent as a polygon in EPSG:4326, or None without a CRS."""
    if metadata.crs is None:
        return None
    footprint = box(*metadata.bounds.as_tuple())
    return reproject_geometry(footprint, metadata.crs, WGS84)


def validate_dem(metadata: RasterMetadata, study_area: StudyArea | None = None) -> ValidationReport:
    """Validate a DEM, optionally against the study area it must cover."""
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []
    coverage_ratio: float | None = None

    if metadata.crs is None:
        errors.append(
            ValidationIssue(
                code="missing_crs",
                message="The GeoTIFF has no CRS: it is not georeferenced and cannot be used.",
            )
        )
    if metadata.band_count < 1:
        errors.append(ValidationIssue(code="no_bands", message="The raster has no bands."))
    elif metadata.band_count > 1:
        warnings.append(
            ValidationIssue(
                code="multiband",
                message=(
                    f"The raster has {metadata.band_count} bands; "
                    "band 1 is used as the elevation surface."
                ),
            )
        )

    errors.extend(_resolution_issues(metadata))

    if metadata.nodata is None:
        warnings.append(
            ValidationIssue(
                code="missing_nodata",
                message=(
                    "No nodata value is declared. Cells with no data cannot be told apart "
                    "from real elevations; declare one in the source file."
                ),
            )
        )

    if metadata.width <= 1 or metadata.height <= 1:
        errors.append(
            ValidationIssue(
                code="degenerate_grid",
                message=f"The raster grid is degenerate: {metadata.width}x{metadata.height}.",
            )
        )

    if study_area is not None and metadata.crs is not None:
        coverage_ratio, intersection_issues = _intersection_issues(metadata, study_area)
        errors.extend(intersection_issues)
        if not intersection_issues and coverage_ratio is not None and coverage_ratio < 1.0:
            warnings.append(
                ValidationIssue(
                    code="partial_coverage",
                    message=(
                        f"The DEM covers {coverage_ratio:.0%} of the study area; "
                        "the uncovered part will have no elevation data."
                    ),
                )
            )

    return ValidationReport(
        ok=not errors, errors=errors, warnings=warnings, coverage_ratio=coverage_ratio
    )


def _resolution_issues(metadata: RasterMetadata) -> list[ValidationIssue]:
    """Check resolution against the raster's own units. Units are never assumed."""
    resolutions = (metadata.resolution_x, metadata.resolution_y)
    if any(value <= 0 for value in resolutions):
        return [
            ValidationIssue(
                code="invalid_resolution",
                message=f"Resolution must be positive, got {resolutions}.",
            )
        ]

    if metadata.units == "degree":
        low, high, unit = MIN_RESOLUTION_DEG, MAX_RESOLUTION_DEG, "degrees"
    elif metadata.units == "m":
        low, high, unit = MIN_RESOLUTION_M, MAX_RESOLUTION_M, "metres"
    else:
        return [
            ValidationIssue(
                code="unknown_units",
                message=(
                    f"The CRS uses units {metadata.units!r}; resolution cannot be interpreted. "
                    "Reproject the DEM to a metre based CRS."
                ),
            )
        ]

    if not all(low <= value <= high for value in resolutions):
        return [
            ValidationIssue(
                code="implausible_resolution",
                message=(
                    f"Resolution {resolutions} {unit} is outside the accepted range "
                    f"[{low}, {high}] {unit}."
                ),
            )
        ]
    return []


def _intersection_issues(
    metadata: RasterMetadata, study_area: StudyArea
) -> tuple[float | None, list[ValidationIssue]]:
    footprint = raster_footprint_wgs84(metadata)
    if footprint is None:  # pragma: no cover - guarded by the missing_crs check
        return None, []

    area_geometry = study_area.geometry
    if not footprint.intersects(area_geometry):
        return 0.0, [
            ValidationIssue(
                code="no_intersection",
                message=(
                    "The DEM does not overlap the study area. Check that both use the "
                    "coordinates you expect."
                ),
            )
        ]

    # Ratios are computed on the WGS84 geometries: an unprojected ratio of two
    # areas of the same small region is stable enough for a coverage check, and
    # no distance is derived from it.
    ratio = footprint.intersection(area_geometry).area / area_geometry.area
    if ratio < MIN_COVERAGE_RATIO:
        return ratio, [
            ValidationIssue(
                code="insufficient_coverage",
                message=(
                    f"The DEM covers only {ratio:.0%} of the study area "
                    f"(minimum {MIN_COVERAGE_RATIO:.0%})."
                ),
            )
        ]
    return ratio, []
