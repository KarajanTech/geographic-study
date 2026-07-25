"""Model to response-schema conversion.

Kept out of the route handlers so the HTTP layer stays a thin adapter.
"""

from __future__ import annotations

from typing import Any

from app.db.models import Dataset, Project
from app.geo.validation import ValidationReport
from app.schemas.dataset import DatasetResponse, ValidationIssueResponse, ValidationResponse
from app.schemas.geojson import BoundsMetric, BoundsWGS84, GeoJSONGeometry
from app.schemas.project import ProjectResponse
from app.services.projects import project_area_geojson


def serialize_project(project: Project, *, dataset_count: int | None = None) -> ProjectResponse:
    area = project_area_geojson(project)
    return ProjectResponse(
        id=project.id,
        name=project.name,
        description=project.description,
        area=GeoJSONGeometry(type=area["type"], coordinates=list(area["coordinates"])),
        analysis_crs=project.analysis_crs,
        area_km2=project.area_km2,
        centroid_lon=project.centroid_lon,
        centroid_lat=project.centroid_lat,
        dataset_count=dataset_count if dataset_count is not None else len(project.datasets),
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def _bounds_metric(dataset: Dataset) -> BoundsMetric | None:
    if dataset.bounds_left is None or dataset.crs is None:
        return None
    return BoundsMetric(
        left=dataset.bounds_left,
        bottom=dataset.bounds_bottom if dataset.bounds_bottom is not None else 0.0,
        right=dataset.bounds_right if dataset.bounds_right is not None else 0.0,
        top=dataset.bounds_top if dataset.bounds_top is not None else 0.0,
        crs=dataset.crs,
        units=dataset.units,
    )


def _bounds_wgs84(payload: dict[str, Any] | None) -> BoundsWGS84 | None:
    if not payload:
        return None
    try:
        return BoundsWGS84(
            west=payload["left"],
            south=payload["bottom"],
            east=payload["right"],
            north=payload["top"],
        )
    except (KeyError, TypeError, ValueError):  # pragma: no cover - defensive
        return None


def serialize_dataset(dataset: Dataset) -> DatasetResponse:
    return DatasetResponse(
        id=dataset.id,
        project_id=dataset.project_id,
        derived_from_id=dataset.derived_from_id,
        dataset_type=dataset.dataset_type,
        role=dataset.role,
        status=dataset.status,
        original_filename=dataset.original_filename,
        checksum_sha256=dataset.checksum_sha256,
        size_bytes=dataset.size_bytes,
        crs=dataset.crs,
        units=dataset.units,
        resolution_x=dataset.resolution_x,
        resolution_y=dataset.resolution_y,
        nodata=dataset.nodata,
        bounds=_bounds_metric(dataset),
        bounds_wgs84=_bounds_wgs84(dataset.metadata_json.get("bounds_wgs84")),
        metadata=dataset.metadata_json,
        processing_history=dataset.processing_history,
        error=dataset.error,
        created_at=dataset.created_at,
        updated_at=dataset.updated_at,
    )


def serialize_validation(report: ValidationReport) -> ValidationResponse:
    return ValidationResponse(
        ok=report.ok,
        errors=[ValidationIssueResponse(code=e.code, message=e.message) for e in report.errors],
        warnings=[ValidationIssueResponse(code=w.code, message=w.message) for w in report.warnings],
        coverage_ratio=report.coverage_ratio,
    )
