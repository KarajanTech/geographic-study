"""Greedy coverage optimization as a persisted analysis run.

Unlike viewshed computation, this runs synchronously inside the request: it
operates on masks Phase 3 already computed, so it is set operations over
NumPy arrays rather than per-cell ray casting — seconds at most for the
"hundreds of candidates" scale ``ROADMAP.md`` asks Phase 4 to handle.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, cast

import numpy as np
import rasterio
from geoalchemy2.shape import to_shape
from numpy.typing import NDArray
from shapely.geometry import Point, mapping, shape
from shapely.geometry.base import BaseGeometry
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import InvalidInputError, ResourceNotFoundError
from app.db.models import (
    AnalysisRun,
    AnalysisRunKind,
    AnalysisRunStatus,
    CandidateSite,
    DatasetType,
    OptimizationSolution,
    Viewshed,
    ViewshedStatus,
)
from app.geo.area import reproject_geometry
from app.geo.crs import WGS84
from app.optimization.greedy import ALGORITHM_VERSION, GreedySolution, solve_greedy
from app.optimization.matrix import ViewshedMaskRef, build_candidate_cell_matrix
from app.optimization.weights import WeightPreset
from app.services.candidates import get_analysis_run
from app.services.datasets import dataset_file, get_dataset
from app.services.projects import get_project
from app.services.storage import from_relative_uri

SOLVER_NAME = "greedy"


def get_optimization_solution(session: Session, solution_id: uuid.UUID) -> OptimizationSolution:
    solution = session.get(OptimizationSolution, solution_id)
    if solution is None:
        msg = "Optimization solution not found"
        raise ResourceNotFoundError(msg, details={"optimization_solution_id": str(solution_id)})
    return solution


def list_optimization_solutions(
    session: Session, analysis_run_id: uuid.UUID
) -> list[OptimizationSolution]:
    statement = (
        select(OptimizationSolution)
        .where(OptimizationSolution.analysis_run_id == analysis_run_id)
        .order_by(OptimizationSolution.created_at)
    )
    return list(session.scalars(statement))


def run_greedy_optimization(
    session: Session,
    viewshed_run_id: uuid.UUID,
    *,
    settings: Settings,
    max_sites: int | None = None,
    target_coverage: float | None = None,
    priorities_dataset_id: uuid.UUID | None = None,
    preset: WeightPreset | None = None,
    priority_zones: list[dict[str, Any]] | None = None,
) -> tuple[AnalysisRun, OptimizationSolution]:
    """Select candidates that maximize covered (risk-weighted) surface.

    Args:
        viewshed_run_id: An ``AnalysisRun`` of kind ``viewshed``. Its
            completed viewsheds become the candidates for this optimization.
        max_sites: Stop once this many candidates are selected.
        target_coverage: Stop once weighted coverage reaches this fraction.
        priorities_dataset_id: A ``priorities``-type dataset of this project,
            already aligned to the analysis surface, used as the base cell
            weight. Mutually exclusive with ``preset``.
        preset: A named terrain-derived weight preset, used when no
            ``priorities_dataset_id`` is given.
        priority_zones: ``[{"geometry": <GeoJSON dict, EPSG:4326>, "weight":
            <float>}, ...]`` — zones whose weight is multiplied by their own
            factor, on top of the base weight.

    Raises:
        InvalidInputError: if the run is not a viewshed run, none of its
            viewsheds completed successfully yet, or the priorities dataset
            does not belong to this project or is not a priorities raster.
    """
    viewshed_run = get_analysis_run(session, viewshed_run_id)
    if viewshed_run.kind is not AnalysisRunKind.VIEWSHED:
        msg = "The referenced run did not compute viewsheds"
        raise InvalidInputError(msg, details={"analysis_run_id": str(viewshed_run_id)})
    if viewshed_run.surface_dataset_id is None:
        msg = "The viewshed run has no associated surface dataset"
        raise InvalidInputError(msg, details={"analysis_run_id": str(viewshed_run_id)})

    viewshed_ids = [uuid.UUID(v) for v in viewshed_run.metrics.get("viewshed_ids", [])]
    if not viewshed_ids:
        msg = "The viewshed run has no viewsheds to optimize over"
        raise InvalidInputError(msg, details={"analysis_run_id": str(viewshed_run_id)})

    completed = list(
        session.scalars(
            select(Viewshed).where(
                Viewshed.id.in_(viewshed_ids), Viewshed.status == ViewshedStatus.COMPLETED
            )
        )
    )
    if not completed:
        msg = "No viewsheds in this run have completed yet; wait for the worker to finish"
        raise InvalidInputError(msg, details={"analysis_run_id": str(viewshed_run_id)})

    surface = get_dataset(session, viewshed_run.surface_dataset_id)
    surface_path = dataset_file(surface, settings)

    refs = [
        ViewshedMaskRef(
            candidate_site_id=str(v.candidate_site_id),
            bitset_path=from_relative_uri(v.bitset_uri, settings),  # type: ignore[arg-type]
            bounds_left=v.bounds_left,  # type: ignore[arg-type]
            bounds_top=v.bounds_top,  # type: ignore[arg-type]
        )
        for v in completed
    ]

    priorities_array = None
    if priorities_dataset_id is not None:
        priorities_array = _read_priorities_array(
            session, viewshed_run.project_id, priorities_dataset_id, settings
        )

    zone_geometries: list[tuple[BaseGeometry, float]] = []
    if priority_zones:
        project = get_project(session, viewshed_run.project_id)
        for zone in priority_zones:
            geometry_wgs84 = shape(zone["geometry"])
            geometry_metric = reproject_geometry(geometry_wgs84, WGS84, project.analysis_crs)
            zone_geometries.append((geometry_metric, float(zone["weight"])))

    matrix = build_candidate_cell_matrix(
        surface_path,
        refs,
        priorities_array=priorities_array,
        preset=preset,
        priority_zone_geometries=zone_geometries or None,
    )

    solution = solve_greedy(
        matrix.candidate_masks,
        matrix.cell_weights,
        max_sites=max_sites,
        target_coverage=target_coverage,
    )

    weights_summary = dict(matrix.weights_summary)
    if priorities_dataset_id is not None:
        weights_summary["priorities_dataset_id"] = str(priorities_dataset_id)

    run = _persist(
        session,
        viewshed_run=viewshed_run,
        completed_viewsheds=completed,
        matrix_candidate_ids=matrix.candidate_ids,
        cell_area_km2=matrix.cell_area_km2,
        solution=solution,
        max_sites=max_sites,
        target_coverage=target_coverage,
        weights_summary=weights_summary,
    )
    stored = list_optimization_solutions(session, run.id)[0]
    return run, stored


def _read_priorities_array(
    session: Session, project_id: uuid.UUID, priorities_dataset_id: uuid.UUID, settings: Settings
) -> NDArray[np.float64]:
    dataset = get_dataset(session, priorities_dataset_id)
    if dataset.project_id != project_id:
        msg = "The priorities dataset does not belong to this project"
        raise InvalidInputError(
            msg,
            details={
                "priorities_dataset_id": str(priorities_dataset_id),
                "project_id": str(project_id),
            },
        )
    if dataset.dataset_type is not DatasetType.PRIORITIES:
        msg = "The referenced dataset is not a priorities raster"
        raise InvalidInputError(
            msg,
            details={
                "priorities_dataset_id": str(priorities_dataset_id),
                "dataset_type": str(dataset.dataset_type),
            },
        )
    path = dataset_file(dataset, settings)
    with rasterio.open(path) as raster:
        band = raster.read(1, masked=True)
        return np.ma.getdata(band).astype(np.float64)


def build_solution_geojson(session: Session, solution_id: uuid.UUID) -> dict[str, Any]:
    """The selected Sentinels as a GeoJSON FeatureCollection, in selection order.

    Every property comes straight from the persisted solution and its
    candidates — nothing here is recomputed, so the export always matches
    what the map and the table already show.
    """
    solution = get_optimization_solution(session, solution_id)
    candidates = _candidates_by_id(session, solution.selected_candidate_ids)

    features = []
    for entry in solution.iterations:
        candidate = candidates.get(entry["candidate_id"])
        if candidate is None:
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": mapping(to_shape(candidate.geometry)),
                "properties": {
                    "rank": entry["step"] + 1,
                    "candidate_site_id": entry["candidate_id"],
                    "elevation_m": candidate.elevation_m,
                    "marginal_gain_cells": entry["marginal_gain"],
                    "cumulative_coverage": entry["cumulative_coverage"],
                    "cumulative_weighted_coverage": entry["cumulative_weighted_coverage"],
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def build_solution_csv_rows(session: Session, solution_id: uuid.UUID) -> list[dict[str, Any]]:
    """The same export as :func:`build_solution_geojson`, one row per Sentinel."""
    solution = get_optimization_solution(session, solution_id)
    candidates = _candidates_by_id(session, solution.selected_candidate_ids)

    rows = []
    for entry in solution.iterations:
        candidate = candidates.get(entry["candidate_id"])
        point = cast(Point, to_shape(candidate.geometry)) if candidate is not None else None
        rows.append(
            {
                "rank": entry["step"] + 1,
                "candidate_site_id": entry["candidate_id"],
                "longitude": point.x if point is not None else "",
                "latitude": point.y if point is not None else "",
                "elevation_m": candidate.elevation_m if candidate is not None else "",
                "marginal_gain_cells": entry["marginal_gain"],
                "cumulative_coverage": entry["cumulative_coverage"],
                "cumulative_weighted_coverage": entry["cumulative_weighted_coverage"],
            }
        )
    return rows


def _candidates_by_id(session: Session, candidate_ids: list[str]) -> dict[str, CandidateSite]:
    ids = [uuid.UUID(candidate_id) for candidate_id in candidate_ids]
    rows = session.scalars(select(CandidateSite).where(CandidateSite.id.in_(ids)))
    return {str(row.id): row for row in rows}


def _persist(
    session: Session,
    *,
    viewshed_run: AnalysisRun,
    completed_viewsheds: list[Viewshed],
    matrix_candidate_ids: list[str],
    cell_area_km2: float,
    solution: GreedySolution,
    max_sites: int | None,
    target_coverage: float | None,
    weights_summary: dict[str, Any],
) -> AnalysisRun:
    viewshed_by_candidate = {str(v.candidate_site_id): v for v in completed_viewsheds}

    run = AnalysisRun(
        project_id=viewshed_run.project_id,
        surface_dataset_id=viewshed_run.surface_dataset_id,
        kind=AnalysisRunKind.OPTIMIZATION,
        status=AnalysisRunStatus.COMPLETED,
        algorithm_version=ALGORITHM_VERSION,
        parameters={
            "viewshed_run_id": str(viewshed_run.id),
            "solver": SOLVER_NAME,
            "max_sites": max_sites,
            "target_coverage": target_coverage,
            "candidate_count": len(matrix_candidate_ids),
            "weights_summary": weights_summary,
        },
        metrics={
            "stop_reason": str(solution.stop_reason),
            "selected_count": len(solution.selected_order),
            "candidate_count": len(matrix_candidate_ids),
            "final_coverage": solution.final_coverage,
            "final_weighted_coverage": solution.final_weighted_coverage,
        },
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
    )
    session.add(run)
    session.flush()

    total_valid_area_km2 = solution.total_cells * cell_area_km2
    visible_area_km2 = solution.final_coverage * total_valid_area_km2
    hidden_area_km2 = total_valid_area_km2 - visible_area_km2

    iterations = []
    for step, candidate_index in enumerate(solution.selected_order):
        candidate_id = matrix_candidate_ids[candidate_index]
        viewshed = viewshed_by_candidate.get(candidate_id)
        iterations.append(
            {
                "step": step,
                "candidate_id": candidate_id,
                "viewshed_id": str(viewshed.id) if viewshed is not None else None,
                "marginal_gain": solution.marginal_gains[step],
                "cumulative_coverage": solution.cumulative_coverage[step],
                "cumulative_weighted_coverage": solution.cumulative_weighted_coverage[step],
            }
        )

    solution_row = OptimizationSolution(
        analysis_run_id=run.id,
        solver=SOLVER_NAME,
        algorithm_version=ALGORITHM_VERSION,
        stop_reason=str(solution.stop_reason),
        selected_candidate_ids=[matrix_candidate_ids[i] for i in solution.selected_order],
        coverage_ratio=solution.final_coverage,
        weighted_coverage_ratio=solution.final_weighted_coverage,
        weights_summary=weights_summary,
        visible_area_km2=visible_area_km2,
        hidden_area_km2=hidden_area_km2,
        # The objective is (risk-)weighted coverage maximization; Phase 7
        # adds a cost penalty and Phase 8 a redundancy reward on top.
        objective_value=solution.final_weighted_coverage,
        total_cost=None,
        redundancy_metrics=None,
        iterations=iterations,
        runtime_seconds=solution.runtime_seconds,
    )
    session.add(solution_row)
    session.flush()
    return run
