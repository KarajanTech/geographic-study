"""Candidate generation as a persisted analysis run.

The geospatial work lives in :mod:`app.geo.candidates`. Here we choose the
surface to run against, record the run with its parameters and seed, and store
the resulting sites.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import ALGORITHM_VERSION
from app.core.config import Settings
from app.core.errors import InvalidInputError, ResourceNotFoundError
from app.core.logging import get_logger
from app.db.models import (
    STORAGE_SRID,
    AnalysisRun,
    AnalysisRunKind,
    AnalysisRunStatus,
    CandidateSite,
    Dataset,
    DatasetRole,
    DatasetStatus,
    DatasetType,
    Project,
)
from app.geo.area import reproject_geometry
from app.geo.candidates import (
    CandidateGenerationResult,
    CandidateParameters,
    generate_candidates,
)
from app.geo.crs import WGS84
from app.services.datasets import dataset_file
from app.services.projects import project_study_area

_log = get_logger(__name__)


def latest_surface(session: Session, project_id: uuid.UUID) -> Dataset:
    """The most recent analysis-ready DEM of a project.

    Candidate generation needs a metric surface; without one there is nothing
    to sample.
    """
    statement = (
        select(Dataset)
        .where(
            Dataset.project_id == project_id,
            Dataset.role == DatasetRole.PROCESSED,
            Dataset.dataset_type == DatasetType.DEM,
            Dataset.status == DatasetStatus.READY,
        )
        .order_by(Dataset.created_at.desc())
        .limit(1)
    )
    dataset = session.scalars(statement).first()
    if dataset is None:
        msg = "The project has no processed DEM; upload one before generating candidates"
        raise InvalidInputError(msg, details={"project_id": str(project_id)})
    return dataset


def get_analysis_run(session: Session, run_id: uuid.UUID) -> AnalysisRun:
    run = session.get(AnalysisRun, run_id)
    if run is None:
        msg = "Analysis run not found"
        raise ResourceNotFoundError(msg, details={"analysis_run_id": str(run_id)})
    return run


def list_analysis_runs(
    session: Session, project_id: uuid.UUID, *, kind: AnalysisRunKind | None = None
) -> list[AnalysisRun]:
    statement = select(AnalysisRun).where(AnalysisRun.project_id == project_id)
    if kind is not None:
        statement = statement.where(AnalysisRun.kind == kind)
    return list(session.scalars(statement.order_by(AnalysisRun.created_at.desc())))


def list_candidates(
    session: Session, run_id: uuid.UUID, *, allowed_only: bool = False, limit: int | None = None
) -> list[CandidateSite]:
    statement = select(CandidateSite).where(CandidateSite.analysis_run_id == run_id)
    if allowed_only:
        statement = statement.where(CandidateSite.is_allowed.is_(True))
    statement = statement.order_by(CandidateSite.rank)
    if limit is not None:
        statement = statement.limit(limit)
    return list(session.scalars(statement))


def count_candidates(session: Session, run_id: uuid.UUID) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(CandidateSite)
            .where(CandidateSite.analysis_run_id == run_id)
        )
        or 0
    )


def _projected_geometries(
    geojson_geometries: list[dict[str, Any]], analysis_crs: str
) -> list[BaseGeometry]:
    """Project GeoJSON exclusion zones from EPSG:4326 into the analysis CRS."""
    from shapely.geometry import shape

    projected: list[BaseGeometry] = []
    for payload in geojson_geometries:
        try:
            geometry = shape(payload)
        except Exception as error:  # noqa: BLE001 - shapely raises several types
            msg = "Exclusion zone is not a valid GeoJSON geometry"
            raise InvalidInputError(msg, details={"reason": str(error)}) from error
        if geometry.is_empty:
            msg = "Exclusion zone geometry is empty"
            raise InvalidInputError(msg)
        projected.append(reproject_geometry(geometry, WGS84, analysis_crs))
    return projected


def _projected_points(
    points_lonlat: list[tuple[float, float]], analysis_crs: str
) -> list[tuple[float, float]]:
    """Project [lon, lat] pairs into the analysis CRS, in metres."""
    projected: list[tuple[float, float]] = []
    for lon, lat in points_lonlat:
        if not -180.0 <= lon <= 180.0 or not -90.0 <= lat <= 90.0:
            msg = "Site coordinates must be [longitude, latitude] in EPSG:4326"
            raise InvalidInputError(msg, details={"lon": lon, "lat": lat})
        point = reproject_geometry(Point(lon, lat), WGS84, analysis_crs)
        projected.append((float(point.x), float(point.y)))
    return projected


def run_candidate_generation(
    session: Session,
    project: Project,
    *,
    settings: Settings,
    parameters: CandidateParameters | None = None,
    exclusion_zones: list[dict[str, Any]] | None = None,
    required_sites: list[tuple[float, float]] | None = None,
    blocked_sites: list[tuple[float, float]] | None = None,
) -> AnalysisRun:
    """Generate and persist candidate sites for a project.

    Inputs arrive in EPSG:4326 and are projected into the project's analysis
    CRS before anything is measured. The run row carries the parameters, the
    seed and the algorithm version, so the result can be reproduced.

    Synchronous in Phase 2: a candidate grid is seconds of work. Viewsheds are
    what will need the worker queue.
    """
    params = (parameters or CandidateParameters()).validated()
    surface = latest_surface(session, project.id)
    surface_path = dataset_file(surface, settings)
    study_area = project_study_area(project)

    run = AnalysisRun(
        project_id=project.id,
        surface_dataset_id=surface.id,
        kind=AnalysisRunKind.CANDIDATES,
        status=AnalysisRunStatus.RUNNING,
        algorithm_version=ALGORITHM_VERSION,
        parameters={
            **params.model_dump(),
            "exclusion_zone_count": len(exclusion_zones or []),
            "required_site_count": len(required_sites or []),
            "blocked_site_count": len(blocked_sites or []),
        },
        random_seed=params.seed,
        metrics={},
        started_at=datetime.now(UTC),
    )
    session.add(run)
    session.flush()

    try:
        result = generate_candidates(
            surface_path,
            study_area.projected(),
            params,
            exclusion_zones=_projected_geometries(exclusion_zones or [], project.analysis_crs),
            required_sites=_projected_points(required_sites or [], project.analysis_crs),
            blocked_sites=_projected_points(blocked_sites or [], project.analysis_crs),
        )
    except Exception as error:
        message = getattr(error, "message", str(error))
        run.status = AnalysisRunStatus.FAILED
        run.error = message
        run.finished_at = datetime.now(UTC)
        session.flush()
        _log.warning(
            "candidate_generation_failed",
            project_id=str(project.id),
            analysis_run_id=str(run.id),
            error=message,
        )
        raise

    _persist_candidates(session, run, result, analysis_crs=project.analysis_crs)

    run.status = AnalysisRunStatus.COMPLETED
    run.finished_at = datetime.now(UTC)
    run.metrics = {
        **result.metrics(),
        "analysis_crs": project.analysis_crs,
        "surface_dataset_id": str(surface.id),
    }
    session.flush()
    return run


def _persist_candidates(
    session: Session,
    run: AnalysisRun,
    result: CandidateGenerationResult,
    *,
    analysis_crs: str,
) -> None:
    """Store accepted candidates, and blocked ones with their reason.

    Rejected grid points are counted in the run metrics rather than stored: a
    coarse grid over a large area produces far more rejections than sites, and
    the counts are what an operator actually reads.
    """
    rows: list[CandidateSite] = []

    for rank, candidate in enumerate(result.candidates):
        point_wgs84 = reproject_geometry(Point(candidate.x_m, candidate.y_m), analysis_crs, WGS84)
        rows.append(
            CandidateSite(
                analysis_run_id=run.id,
                geometry=from_shape(point_wgs84, srid=STORAGE_SRID),
                x_m=candidate.x_m,
                y_m=candidate.y_m,
                elevation_m=candidate.elevation_m,
                slope_deg=candidate.slope_deg,
                prominence_m=candidate.prominence_m,
                rank=rank,
                is_allowed=True,
                is_mandatory=candidate.is_mandatory,
                source=candidate.source,
                filter_reasons=[],
            )
        )

    for offset, blocked in enumerate(result.blocked):
        point_wgs84 = reproject_geometry(Point(blocked.x_m, blocked.y_m), analysis_crs, WGS84)
        rows.append(
            CandidateSite(
                analysis_run_id=run.id,
                geometry=from_shape(point_wgs84, srid=STORAGE_SRID),
                x_m=blocked.x_m,
                y_m=blocked.y_m,
                elevation_m=0.0,
                slope_deg=0.0,
                prominence_m=0.0,
                rank=len(result.candidates) + offset,
                is_allowed=False,
                is_mandatory=False,
                source="blocked_site",
                filter_reasons=[str(blocked.reason)],
            )
        )

    session.add_all(rows)
    session.flush()
