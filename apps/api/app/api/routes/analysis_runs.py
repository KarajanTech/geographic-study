"""Candidate generation and viewshed endpoints."""

from __future__ import annotations

import csv
import io
import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status
from fastapi.responses import FileResponse, JSONResponse, Response

from app.api.deps import SessionDep, SettingsDep
from app.api.serializers import (
    serialize_analysis_run,
    serialize_candidate,
    serialize_optimization_solution,
    serialize_viewshed,
)
from app.core.errors import ResourceNotFoundError
from app.db.models import AnalysisRunKind
from app.geo.candidates import CandidateParameters
from app.schemas.candidate import (
    AnalysisRunListResponse,
    AnalysisRunResponse,
    CandidateGenerationRequest,
    CandidateListResponse,
)
from app.schemas.optimization import (
    OptimizationRunRequest,
    OptimizationSolutionListResponse,
    OptimizationSolutionResponse,
)
from app.schemas.viewshed import ViewshedListResponse, ViewshedResponse, ViewshedRunRequest
from app.services import candidates as candidate_service
from app.services import optimization as optimization_service
from app.services import projects as project_service
from app.services import viewsheds as viewshed_service
from app.services.storage import from_relative_uri

router = APIRouter(tags=["analysis-runs"])


@router.post(
    "/projects/{project_id}/candidates",
    response_model=AnalysisRunResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate candidate Sentinel positions",
)
def generate_candidates(
    project_id: uuid.UUID,
    payload: CandidateGenerationRequest,
    session: SessionDep,
    settings: SettingsDep,
) -> AnalysisRunResponse:
    """Grid the study area, filter by terrain, thin by separation, and persist.

    Runs against the project's most recent processed DEM. Fails with a clear
    message if no DEM has been ingested yet.
    """
    project = project_service.get_project(session, project_id)

    parameters = CandidateParameters(
        spacing_m=payload.spacing_m,
        max_slope_deg=payload.max_slope_deg,
        min_separation_m=payload.min_separation_m,
        prominence_radius_m=payload.prominence_radius_m,
        min_elevation_m=payload.min_elevation_m,
        max_elevation_m=payload.max_elevation_m,
        max_candidates=payload.max_candidates,
        jitter_m=payload.jitter_m,
        seed=payload.seed,
    )

    run = candidate_service.run_candidate_generation(
        session,
        project,
        settings=settings,
        parameters=parameters,
        exclusion_zones=[zone.to_dict() for zone in payload.exclusion_zones],
        required_sites=[(site.lon, site.lat) for site in payload.required_sites],
        blocked_sites=[(site.lon, site.lat) for site in payload.blocked_sites],
    )
    return serialize_analysis_run(run)


@router.get(
    "/projects/{project_id}/analysis-runs",
    response_model=AnalysisRunListResponse,
    summary="List a project's analysis runs",
)
def list_analysis_runs(
    project_id: uuid.UUID,
    session: SessionDep,
    kind: AnalysisRunKind | None = None,
) -> AnalysisRunListResponse:
    project_service.get_project(session, project_id)
    runs = candidate_service.list_analysis_runs(session, project_id, kind=kind)
    return AnalysisRunListResponse(items=[serialize_analysis_run(r) for r in runs], total=len(runs))


@router.get(
    "/analysis-runs/{run_id}",
    response_model=AnalysisRunResponse,
    summary="Get an analysis run",
)
def get_analysis_run(run_id: uuid.UUID, session: SessionDep) -> AnalysisRunResponse:
    return serialize_analysis_run(candidate_service.get_analysis_run(session, run_id))


@router.get(
    "/analysis-runs/{run_id}/candidates",
    response_model=CandidateListResponse,
    summary="List the candidate sites of a run",
)
def list_candidates(
    run_id: uuid.UUID,
    session: SessionDep,
    allowed_only: bool = True,
    limit: Annotated[int | None, Query(ge=1, le=10_000)] = None,
) -> CandidateListResponse:
    candidate_service.get_analysis_run(session, run_id)
    sites = candidate_service.list_candidates(
        session, run_id, allowed_only=allowed_only, limit=limit
    )
    total = candidate_service.count_candidates(session, run_id)
    return CandidateListResponse(items=[serialize_candidate(s) for s in sites], total=total)


@router.post(
    "/analysis-runs/{candidates_run_id}/viewsheds",
    response_model=AnalysisRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue viewshed computation for a candidate run's sites",
)
def enqueue_viewsheds(
    candidates_run_id: uuid.UUID, payload: ViewshedRunRequest, session: SessionDep
) -> AnalysisRunResponse:
    """Queue viewsheds for every accepted candidate of a run (or a subset).

    Returns immediately with status ``pending`` or ``completed`` (if every
    requested viewshed was already cached) — nothing is computed inside this
    request. A worker process picks up pending work; see
    ``app.workers.viewshed_worker``.
    """
    run = viewshed_service.enqueue_viewshed_run(
        session,
        candidates_run_id,
        observer_height_m=payload.observer_height_m,
        target_height_m=payload.target_height_m,
        max_distance_m=payload.max_distance_m,
        use_earth_curvature=payload.use_earth_curvature,
        refraction_coefficient=payload.refraction_coefficient,
        candidate_site_ids=payload.candidate_site_ids,
    )
    return serialize_analysis_run(run)


@router.get(
    "/analysis-runs/{run_id}/viewsheds",
    response_model=ViewshedListResponse,
    summary="List the viewsheds of a batch run, with progress",
)
def list_viewsheds(run_id: uuid.UUID, session: SessionDep) -> ViewshedListResponse:
    items = viewshed_service.list_viewsheds_for_run(session, run_id)
    return ViewshedListResponse(items=[serialize_viewshed(v) for v in items], total=len(items))


@router.get(
    "/viewsheds/{viewshed_id}",
    response_model=ViewshedResponse,
    summary="Get a single viewshed",
)
def get_viewshed(viewshed_id: uuid.UUID, session: SessionDep) -> ViewshedResponse:
    return serialize_viewshed(viewshed_service.get_viewshed(session, viewshed_id))


@router.get(
    "/viewsheds/{viewshed_id}/mask.tif",
    response_class=FileResponse,
    summary="Download the viewshed mask GeoTIFF",
    responses={200: {"content": {"image/tiff": {}}}},
)
def download_viewshed_mask(
    viewshed_id: uuid.UUID, session: SessionDep, settings: SettingsDep
) -> FileResponse:
    viewshed = viewshed_service.get_viewshed(session, viewshed_id)
    if not viewshed.raster_uri:
        msg = "Viewshed has not been computed yet"
        raise ResourceNotFoundError(msg, details={"viewshed_id": str(viewshed_id)})
    path = from_relative_uri(viewshed.raster_uri, settings)
    return FileResponse(path, media_type="image/tiff", filename=f"{viewshed_id}_mask.tif")


@router.get(
    "/viewsheds/{viewshed_id}/preview.png",
    response_class=FileResponse,
    summary="Download a map-overlay preview of the viewshed",
    responses={200: {"content": {"image/png": {}}}},
)
def download_viewshed_preview(
    viewshed_id: uuid.UUID, session: SessionDep, settings: SettingsDep
) -> FileResponse:
    viewshed = viewshed_service.get_viewshed(session, viewshed_id)
    if not viewshed.preview_uri:
        msg = "Viewshed has not been computed yet"
        raise ResourceNotFoundError(msg, details={"viewshed_id": str(viewshed_id)})
    path = from_relative_uri(viewshed.preview_uri, settings)
    return FileResponse(path, media_type="image/png", filename=f"{viewshed_id}_preview.png")


@router.post(
    "/analysis-runs/{viewshed_run_id}/optimize",
    response_model=OptimizationSolutionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Select the Sentinel positions that maximize covered surface",
)
def optimize_coverage(
    viewshed_run_id: uuid.UUID,
    payload: OptimizationRunRequest,
    session: SessionDep,
    settings: SettingsDep,
) -> OptimizationSolutionResponse:
    """Greedily choose candidates from a completed (or partial) viewshed run.

    Runs synchronously: this operates on masks Phase 3 already computed —
    array operations, not ray casting — so it finishes in seconds even for
    hundreds of candidates.
    """
    _run, solution = optimization_service.run_greedy_optimization(
        session,
        viewshed_run_id,
        settings=settings,
        max_sites=payload.max_sites,
        target_coverage=payload.target_coverage,
        priorities_dataset_id=payload.priorities_dataset_id,
        preset=payload.preset,
        priority_zones=[
            {"geometry": zone.geometry.to_dict(), "weight": zone.weight}
            for zone in payload.priority_zones
        ],
    )
    return serialize_optimization_solution(solution)


@router.get(
    "/analysis-runs/{run_id}/optimization-solutions",
    response_model=OptimizationSolutionListResponse,
    summary="List the optimization solutions of a run",
)
def list_optimization_solutions(
    run_id: uuid.UUID, session: SessionDep
) -> OptimizationSolutionListResponse:
    items = optimization_service.list_optimization_solutions(session, run_id)
    return OptimizationSolutionListResponse(
        items=[serialize_optimization_solution(s) for s in items], total=len(items)
    )


@router.get(
    "/optimization-solutions/{solution_id}",
    response_model=OptimizationSolutionResponse,
    summary="Get a single optimization solution",
)
def get_optimization_solution(
    solution_id: uuid.UUID, session: SessionDep
) -> OptimizationSolutionResponse:
    solution = optimization_service.get_optimization_solution(session, solution_id)
    return serialize_optimization_solution(solution)


@router.get(
    "/optimization-solutions/{solution_id}/export.geojson",
    summary="Export the selected Sentinel positions as GeoJSON",
    responses={200: {"content": {"application/geo+json": {}}}},
)
def export_solution_geojson(solution_id: uuid.UUID, session: SessionDep) -> JSONResponse:
    feature_collection = optimization_service.build_solution_geojson(session, solution_id)
    return JSONResponse(
        content=feature_collection,
        media_type="application/geo+json",
        headers={"Content-Disposition": f'attachment; filename="{solution_id}.geojson"'},
    )


@router.get(
    "/optimization-solutions/{solution_id}/export.csv",
    summary="Export the selected Sentinel positions as CSV",
    responses={200: {"content": {"text/csv": {}}}},
)
def export_solution_csv(solution_id: uuid.UUID, session: SessionDep) -> Response:
    rows = optimization_service.build_solution_csv_rows(session, solution_id)
    buffer = io.StringIO()
    fieldnames = [
        "rank",
        "candidate_site_id",
        "longitude",
        "latitude",
        "elevation_m",
        "marginal_gain_cells",
        "cumulative_coverage",
        "cumulative_weighted_coverage",
    ]
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{solution_id}.csv"'},
    )
