"""Model to response-schema conversion.

Kept out of the route handlers so the HTTP layer stays a thin adapter.
"""

from __future__ import annotations

import uuid
from typing import Any

from geoalchemy2.shape import to_shape
from shapely.geometry import mapping

from app.db.models import (
    AnalysisRun,
    CandidateSite,
    Dataset,
    OptimizationSolution,
    Project,
    Viewshed,
)
from app.geo.validation import ValidationReport
from app.schemas.candidate import AnalysisRunResponse, CandidateSiteResponse
from app.schemas.dataset import DatasetResponse, ValidationIssueResponse, ValidationResponse
from app.schemas.geojson import BoundsMetric, BoundsWGS84, GeoJSONGeometry, GeoJSONPoint
from app.schemas.optimization import OptimizationIteration, OptimizationSolutionResponse
from app.schemas.project import ProjectResponse
from app.schemas.viewshed import ViewshedResponse
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


def serialize_analysis_run(run: AnalysisRun) -> AnalysisRunResponse:
    return AnalysisRunResponse(
        id=run.id,
        project_id=run.project_id,
        surface_dataset_id=run.surface_dataset_id,
        kind=run.kind,
        status=run.status,
        algorithm_version=run.algorithm_version,
        parameters=run.parameters,
        random_seed=run.random_seed,
        metrics=run.metrics,
        error=run.error,
        started_at=run.started_at,
        finished_at=run.finished_at,
        created_at=run.created_at,
    )


def _viewshed_bounds(viewshed: Viewshed) -> BoundsMetric | None:
    if viewshed.bounds_left is None:
        return None
    return BoundsMetric(
        left=viewshed.bounds_left,
        bottom=viewshed.bounds_bottom or 0.0,
        right=viewshed.bounds_right or 0.0,
        top=viewshed.bounds_top or 0.0,
        crs=viewshed.crs or "",
        units="m",
    )


def _viewshed_bounds_wgs84(viewshed: Viewshed) -> BoundsWGS84 | None:
    if viewshed.bounds_wgs84_west is None:
        return None
    return BoundsWGS84(
        west=viewshed.bounds_wgs84_west,
        south=viewshed.bounds_wgs84_south or 0.0,
        east=viewshed.bounds_wgs84_east or 0.0,
        north=viewshed.bounds_wgs84_north or 0.0,
    )


def serialize_viewshed(viewshed: Viewshed) -> ViewshedResponse:
    coverage_ratio = None
    if viewshed.visible_cell_count is not None and viewshed.total_cell_count:
        coverage_ratio = viewshed.visible_cell_count / viewshed.total_cell_count
    return ViewshedResponse(
        id=viewshed.id,
        candidate_site_id=viewshed.candidate_site_id,
        surface_dataset_id=viewshed.surface_dataset_id,
        status=viewshed.status,
        algorithm_version=viewshed.algorithm_version,
        observer_height_m=viewshed.observer_height_m,
        target_height_m=viewshed.target_height_m,
        max_distance_m=viewshed.max_distance_m,
        use_earth_curvature=viewshed.use_earth_curvature,
        refraction_coefficient=viewshed.refraction_coefficient,
        bounds=_viewshed_bounds(viewshed),
        bounds_wgs84=_viewshed_bounds_wgs84(viewshed),
        preview_url=f"/api/v1/viewsheds/{viewshed.id}/preview.png"
        if viewshed.preview_uri
        else None,
        observer_elevation_m=viewshed.observer_elevation_m,
        visible_cell_count=viewshed.visible_cell_count,
        total_cell_count=viewshed.total_cell_count,
        coverage_ratio=coverage_ratio,
        weighted_visible_score=viewshed.weighted_visible_score,
        error=viewshed.error,
        started_at=viewshed.started_at,
        finished_at=viewshed.finished_at,
        created_at=viewshed.created_at,
    )


def serialize_candidate(site: CandidateSite) -> CandidateSiteResponse:
    location = dict(mapping(to_shape(site.geometry)))
    return CandidateSiteResponse(
        id=site.id,
        location=GeoJSONPoint(coordinates=list(location["coordinates"])),
        x_m=site.x_m,
        y_m=site.y_m,
        elevation_m=site.elevation_m,
        slope_deg=site.slope_deg,
        prominence_m=site.prominence_m,
        rank=site.rank,
        is_allowed=site.is_allowed,
        is_mandatory=site.is_mandatory,
        source=site.source,
        filter_reasons=site.filter_reasons,
    )


def serialize_optimization_solution(
    solution: OptimizationSolution,
) -> OptimizationSolutionResponse:
    return OptimizationSolutionResponse(
        id=solution.id,
        analysis_run_id=solution.analysis_run_id,
        solver=solution.solver,
        algorithm_version=solution.algorithm_version,
        stop_reason=solution.stop_reason,
        selected_candidate_ids=[uuid.UUID(cid) for cid in solution.selected_candidate_ids],
        coverage_ratio=solution.coverage_ratio,
        weighted_coverage_ratio=solution.weighted_coverage_ratio,
        weights_summary=solution.weights_summary,
        visible_area_km2=solution.visible_area_km2,
        hidden_area_km2=solution.hidden_area_km2,
        objective_value=solution.objective_value,
        total_cost=solution.total_cost,
        redundancy_metrics=solution.redundancy_metrics,
        iterations=[
            OptimizationIteration(
                step=entry["step"],
                candidate_id=uuid.UUID(entry["candidate_id"]),
                viewshed_id=uuid.UUID(entry["viewshed_id"]) if entry["viewshed_id"] else None,
                marginal_gain=entry["marginal_gain"],
                cumulative_coverage=entry["cumulative_coverage"],
                cumulative_weighted_coverage=entry["cumulative_weighted_coverage"],
            )
            for entry in solution.iterations
        ],
        runtime_seconds=solution.runtime_seconds,
        created_at=solution.created_at,
    )
