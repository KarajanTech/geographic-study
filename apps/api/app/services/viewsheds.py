"""Viewshed computation as a persisted, queued analysis run.

PostgreSQL is the job queue: enqueuing writes ``AnalysisRun`` and ``Viewshed``
rows at ``pending`` and returns immediately — no viewshed is computed inside
the HTTP request. A worker (``app.workers.viewshed_worker``, or a direct call
to :func:`process_pending_viewshed_runs` in tests) polls for pending rows and
computes them, one candidate at a time, so a failure on any single candidate
never aborts the run.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from shapely.geometry import box
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import InvalidInputError, ResourceNotFoundError
from app.core.logging import get_logger
from app.db.models import (
    AnalysisRun,
    AnalysisRunKind,
    AnalysisRunStatus,
    CandidateSite,
    Dataset,
    Viewshed,
    ViewshedStatus,
)
from app.geo.area import reproject_geometry
from app.geo.crs import WGS84
from app.geo.viewshed import (
    DEFAULT_MAX_DISTANCE_M,
    DEFAULT_OBSERVER_HEIGHT_M,
    DEFAULT_REFRACTION_COEFFICIENT,
    DEFAULT_TARGET_HEIGHT_M,
    LineOfSightViewshedEngine,
    ViewshedEngine,
    compute_cache_key,
    write_mask_geotiff,
    write_packed_bitset,
    write_visibility_preview_png,
)
from app.services.candidates import get_analysis_run
from app.services.datasets import dataset_file, get_dataset
from app.services.storage import to_relative_uri, viewshed_dir

_log = get_logger(__name__)

_DEFAULT_ENGINE: ViewshedEngine = LineOfSightViewshedEngine()

RASTER_NAME = "mask.tif"
BITSET_NAME = "mask.npz"
PREVIEW_NAME = "preview.png"


def get_viewshed(session: Session, viewshed_id: uuid.UUID) -> Viewshed:
    viewshed = session.get(Viewshed, viewshed_id)
    if viewshed is None:
        msg = "Viewshed not found"
        raise ResourceNotFoundError(msg, details={"viewshed_id": str(viewshed_id)})
    return viewshed


def list_viewsheds_for_run(session: Session, analysis_run_id: uuid.UUID) -> list[Viewshed]:
    """Viewsheds belonging to a ``kind=viewshed`` run, in candidate rank order.

    The run's ``metrics.viewshed_ids`` records which rows belong to it — some
    may be shared with an earlier run via the cache.
    """
    run = get_analysis_run(session, analysis_run_id)
    ids = [uuid.UUID(value) for value in run.metrics.get("viewshed_ids", [])]
    if not ids:
        return []
    rows = {row.id: row for row in session.scalars(select(Viewshed).where(Viewshed.id.in_(ids)))}
    return [rows[i] for i in ids if i in rows]


def enqueue_viewshed_run(
    session: Session,
    candidates_run_id: uuid.UUID,
    *,
    observer_height_m: float = DEFAULT_OBSERVER_HEIGHT_M,
    target_height_m: float = DEFAULT_TARGET_HEIGHT_M,
    max_distance_m: float = DEFAULT_MAX_DISTANCE_M,
    use_earth_curvature: bool = True,
    refraction_coefficient: float = DEFAULT_REFRACTION_COEFFICIENT,
    candidate_site_ids: list[uuid.UUID] | None = None,
) -> AnalysisRun:
    """Queue a viewshed computation for a candidate-generation run's sites.

    Creates the batch ``AnalysisRun`` (kind=viewshed, status=pending) and one
    ``Viewshed`` row per candidate — reusing an existing row when its cache key
    already exists — then returns immediately. Nothing is computed here.
    """
    candidates_run = get_analysis_run(session, candidates_run_id)
    if candidates_run.kind is not AnalysisRunKind.CANDIDATES:
        msg = "The referenced run did not generate candidates"
        raise InvalidInputError(msg, details={"analysis_run_id": str(candidates_run_id)})
    if candidates_run.surface_dataset_id is None:
        msg = "The candidates run has no associated surface dataset"
        raise InvalidInputError(msg, details={"analysis_run_id": str(candidates_run_id)})

    statement = select(CandidateSite).where(
        CandidateSite.analysis_run_id == candidates_run_id, CandidateSite.is_allowed.is_(True)
    )
    if candidate_site_ids is not None:
        statement = statement.where(CandidateSite.id.in_(candidate_site_ids))
    sites = list(session.scalars(statement.order_by(CandidateSite.rank)))
    if not sites:
        msg = "No matching candidate sites found for this run"
        raise InvalidInputError(msg, details={"analysis_run_id": str(candidates_run_id)})

    surface_dataset_id = candidates_run.surface_dataset_id
    surface_checksum = _surface_checksum(session, surface_dataset_id)

    viewshed_run = AnalysisRun(
        project_id=candidates_run.project_id,
        surface_dataset_id=surface_dataset_id,
        kind=AnalysisRunKind.VIEWSHED,
        status=AnalysisRunStatus.PENDING,
        algorithm_version=_DEFAULT_ENGINE.algorithm_version,
        parameters={
            "candidates_run_id": str(candidates_run_id),
            "candidate_site_ids": [str(s.id) for s in sites],
            "observer_height_m": observer_height_m,
            "target_height_m": target_height_m,
            "max_distance_m": max_distance_m,
            "use_earth_curvature": use_earth_curvature,
            "refraction_coefficient": refraction_coefficient,
        },
        metrics={"total": len(sites), "pending": len(sites), "completed": 0, "failed": 0},
    )
    session.add(viewshed_run)
    session.flush()

    viewshed_ids: list[str] = []
    cache_hits = 0
    for site in sites:
        cache_key = compute_cache_key(
            surface_checksum=surface_checksum,
            observer_x=site.x_m,
            observer_y=site.y_m,
            observer_height_m=observer_height_m,
            target_height_m=target_height_m,
            max_distance_m=max_distance_m,
            use_earth_curvature=use_earth_curvature,
            refraction_coefficient=refraction_coefficient,
            algorithm_version=_DEFAULT_ENGINE.algorithm_version,
        )
        existing = session.scalar(select(Viewshed).where(Viewshed.cache_key == cache_key))
        if existing is not None:
            viewshed_ids.append(str(existing.id))
            cache_hits += 1
            continue

        viewshed = Viewshed(
            candidate_site_id=site.id,
            surface_dataset_id=surface_dataset_id,
            cache_key=cache_key,
            status=ViewshedStatus.PENDING,
            algorithm_version=_DEFAULT_ENGINE.algorithm_version,
            observer_height_m=observer_height_m,
            target_height_m=target_height_m,
            max_distance_m=max_distance_m,
            use_earth_curvature=use_earth_curvature,
            refraction_coefficient=refraction_coefficient,
        )
        session.add(viewshed)
        session.flush()
        viewshed_ids.append(str(viewshed.id))

    viewshed_run.metrics = {
        **viewshed_run.metrics,
        "viewshed_ids": viewshed_ids,
        "cache_hits": cache_hits,
        # A cache hit is already completed; only genuinely new rows are pending.
        "pending": len(sites) - cache_hits,
        "completed": cache_hits,
    }
    if cache_hits == len(sites):
        viewshed_run.status = AnalysisRunStatus.COMPLETED
        viewshed_run.finished_at = datetime.now(UTC)
    session.flush()

    _log.info(
        "viewshed_run_enqueued",
        analysis_run_id=str(viewshed_run.id),
        candidate_count=len(sites),
        cache_hits=cache_hits,
    )
    return viewshed_run


def _surface_checksum(session: Session, surface_dataset_id: uuid.UUID) -> str:
    dataset = session.get(Dataset, surface_dataset_id)
    if dataset is None:
        msg = "Surface dataset not found"
        raise ResourceNotFoundError(msg, details={"dataset_id": str(surface_dataset_id)})
    return dataset.checksum_sha256


def process_pending_viewshed_runs(
    session: Session,
    settings: Settings,
    *,
    limit: int | None = None,
    engine: ViewshedEngine | None = None,
) -> list[AnalysisRun]:
    """Compute every pending ``Viewshed`` row, grouped by its batch run.

    This is the worker's core loop — called in a polling loop by
    ``app.workers.viewshed_worker`` in production, and called directly in
    tests. A failure on one candidate is caught and recorded on that row only;
    the batch continues and finishes as ``completed`` with the failure noted
    in its metrics, matching the roadmap's "un fallo en un candidato no
    destruye toda la ejecución".
    """
    active_engine = engine or _DEFAULT_ENGINE

    statement = select(AnalysisRun).where(
        AnalysisRun.kind == AnalysisRunKind.VIEWSHED,
        AnalysisRun.status.in_([AnalysisRunStatus.PENDING, AnalysisRunStatus.RUNNING]),
    )
    if limit is not None:
        statement = statement.limit(limit)
    runs = list(session.scalars(statement.order_by(AnalysisRun.created_at)))

    processed: list[AnalysisRun] = []
    for run in runs:
        _process_run(session, run, settings, active_engine)
        processed.append(run)
    return processed


def _process_run(
    session: Session, run: AnalysisRun, settings: Settings, engine: ViewshedEngine
) -> None:
    if run.started_at is None:
        run.started_at = datetime.now(UTC)
    run.status = AnalysisRunStatus.RUNNING
    session.flush()

    viewshed_ids = [uuid.UUID(v) for v in run.metrics.get("viewshed_ids", [])]
    pending = list(
        session.scalars(
            select(Viewshed).where(
                Viewshed.id.in_(viewshed_ids), Viewshed.status == ViewshedStatus.PENDING
            )
        )
    )

    completed = run.metrics.get("completed", 0)
    failed = run.metrics.get("failed", 0)

    for viewshed in pending:
        try:
            _compute_one(session, viewshed, settings, engine)
            completed += 1
        except Exception as error:  # noqa: BLE001 - isolate one candidate's failure
            message = getattr(error, "message", str(error))
            viewshed.status = ViewshedStatus.FAILED
            viewshed.error = message
            viewshed.finished_at = datetime.now(UTC)
            failed += 1
            _log.warning(
                "viewshed_failed",
                viewshed_id=str(viewshed.id),
                candidate_site_id=str(viewshed.candidate_site_id),
                error=message,
            )
        session.flush()

    run.metrics = {
        **run.metrics,
        "completed": completed,
        "failed": failed,
        "pending": max(0, run.metrics.get("total", len(viewshed_ids)) - completed - failed),
    }
    run.status = AnalysisRunStatus.COMPLETED
    run.finished_at = datetime.now(UTC)
    session.flush()

    _log.info(
        "viewshed_run_processed",
        analysis_run_id=str(run.id),
        completed=completed,
        failed=failed,
    )


def _compute_one(
    session: Session, viewshed: Viewshed, settings: Settings, engine: ViewshedEngine
) -> None:
    viewshed.status = ViewshedStatus.RUNNING
    viewshed.started_at = datetime.now(UTC)
    session.flush()

    candidate = session.get(CandidateSite, viewshed.candidate_site_id)
    if candidate is None:
        msg = "Candidate site no longer exists"
        raise InvalidInputError(msg, details={"candidate_site_id": str(viewshed.candidate_site_id)})

    surface = get_dataset(session, viewshed.surface_dataset_id)
    surface_path: Path = dataset_file(surface, settings)

    result = engine.compute(
        surface_path,
        candidate.x_m,
        candidate.y_m,
        viewshed.observer_height_m,
        viewshed.target_height_m,
        viewshed.max_distance_m,
        use_earth_curvature=viewshed.use_earth_curvature,
        refraction_coefficient=viewshed.refraction_coefficient,
    )

    output_dir = viewshed_dir(surface.project_id, viewshed.id, settings)
    output_dir.mkdir(parents=True, exist_ok=True)

    raster_path = output_dir / RASTER_NAME
    write_mask_geotiff(raster_path, result.visible, result.crs, result.transform)

    bitset_path = output_dir / BITSET_NAME
    write_packed_bitset(bitset_path, result.visible)

    preview_path = output_dir / PREVIEW_NAME
    write_visibility_preview_png(preview_path, result.visible)

    cell_area_m2 = result.resolution_m[0] * result.resolution_m[1]

    viewshed.raster_uri = to_relative_uri(raster_path, settings)
    viewshed.bitset_uri = to_relative_uri(bitset_path, settings)
    viewshed.preview_uri = to_relative_uri(preview_path, settings)
    viewshed.crs = result.crs
    viewshed.bounds_left, viewshed.bounds_bottom, viewshed.bounds_right, viewshed.bounds_top = (
        result.bounds
    )
    wgs84_bounds = reproject_geometry(box(*result.bounds), result.crs, WGS84).bounds
    (
        viewshed.bounds_wgs84_west,
        viewshed.bounds_wgs84_south,
        viewshed.bounds_wgs84_east,
        viewshed.bounds_wgs84_north,
    ) = wgs84_bounds
    viewshed.resolution_x, viewshed.resolution_y = result.resolution_m
    viewshed.observer_elevation_m = result.observer_elevation_m
    viewshed.visible_cell_count = result.visible_cell_count
    viewshed.total_cell_count = result.total_cell_count
    # Uniform weighting for now: visible surface in square metres. Phase 6
    # replaces this with a true risk-weighted score once cell weights exist.
    viewshed.weighted_visible_score = float(result.visible_cell_count) * cell_area_m2
    viewshed.status = ViewshedStatus.COMPLETED
    viewshed.finished_at = datetime.now(UTC)
    session.flush()


__all__ = [
    "enqueue_viewshed_run",
    "get_viewshed",
    "list_viewsheds_for_run",
    "process_pending_viewshed_runs",
]
