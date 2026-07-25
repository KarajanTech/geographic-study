"""Candidate site generation.

Where could a Sentinel physically go? This module answers that from terrain
alone: a regular grid over the study area, sampled against the analysis
surface, filtered by hard constraints, then thinned so no two candidates sit on
top of each other.

Everything happens in the project's analysis CRS, in metres. The result is a
pure function of (surface, study area, parameters, seed): the same inputs
always produce the same candidates, in the same order.

Visibility is not considered here at all — that is Phase 3.
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

import numpy as np
import rasterio
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry
from shapely.prepared import prep

from app.core.errors import InvalidInputError
from app.core.logging import get_logger
from app.geo.crs import require_metric_crs
from app.geo.terrain import compute_local_prominence, compute_slope_degrees

_log = get_logger(__name__)

# Refuse to build a grid that would exhaust memory before it is thinned.
MAX_GRID_POINTS = 2_000_000


class RejectionReason(StrEnum):
    """Why a grid point cannot hold a Sentinel."""

    OUTSIDE_AREA = "outside_area"
    NODATA = "nodata"
    SLOPE_TOO_STEEP = "slope_too_steep"
    ELEVATION_OUT_OF_RANGE = "elevation_out_of_range"
    EXCLUDED_ZONE = "excluded_zone"
    BLOCKED_SITE = "blocked_site"
    TOO_CLOSE = "too_close_to_selected"
    MAX_CANDIDATES = "max_candidates_reached"


class CandidateParameters(BaseModel):
    """Everything that determines the candidate set.

    Stored with the run: the same parameters and seed must reproduce the same
    candidates exactly.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    spacing_m: Annotated[float, Field(gt=0, le=20_000, description="Grid spacing in metres.")] = (
        500.0
    )
    max_slope_deg: Annotated[
        float, Field(ge=0, le=90, description="Reject terrain steeper than this.")
    ] = 25.0
    min_separation_m: Annotated[
        float, Field(ge=0, le=50_000, description="Minimum distance between two candidates.")
    ] = 0.0
    prominence_radius_m: Annotated[
        float,
        Field(gt=0, le=50_000, description="Neighbourhood radius for local prominence, metres."),
    ] = 1_000.0
    min_elevation_m: float | None = Field(
        default=None, description="Reject sites below this elevation, metres."
    )
    max_elevation_m: float | None = Field(
        default=None, description="Reject sites above this elevation, metres."
    )
    max_candidates: Annotated[int | None, Field(ge=1, le=100_000)] = Field(
        default=None, description="Keep at most this many, best first."
    )
    jitter_m: Annotated[float, Field(ge=0, le=10_000)] = Field(
        default=0.0,
        description=(
            "Random offset applied to each grid point, metres. Zero keeps the "
            "grid strictly regular; any other value uses the seed."
        ),
    )
    seed: int = Field(default=20240101, description="Seed for the jitter. Always recorded.")

    def validated(self) -> CandidateParameters:
        if (
            self.min_elevation_m is not None
            and self.max_elevation_m is not None
            and self.min_elevation_m > self.max_elevation_m
        ):
            msg = "min_elevation_m cannot be greater than max_elevation_m"
            raise InvalidInputError(
                msg,
                details={
                    "min_elevation_m": self.min_elevation_m,
                    "max_elevation_m": self.max_elevation_m,
                },
            )
        if self.jitter_m >= self.spacing_m / 2.0 and self.jitter_m > 0:
            msg = "jitter_m must be smaller than half the grid spacing"
            raise InvalidInputError(
                msg, details={"jitter_m": self.jitter_m, "spacing_m": self.spacing_m}
            )
        return self


@dataclass(frozen=True, slots=True)
class Candidate:
    """One potential Sentinel location, in the analysis CRS."""

    x_m: float
    y_m: float
    elevation_m: float
    slope_deg: float
    prominence_m: float
    is_mandatory: bool = False
    source: str = "grid"

    @property
    def score(self) -> float:
        """Ranking used by the separation filter: higher ground wins."""
        return self.prominence_m


@dataclass(frozen=True, slots=True)
class RejectedCandidate:
    x_m: float
    y_m: float
    reason: RejectionReason


@dataclass(frozen=True, slots=True)
class CandidateGenerationResult:
    """Accepted candidates plus a full account of what was discarded."""

    candidates: list[Candidate]
    crs: str
    parameters: CandidateParameters
    grid_point_count: int
    rejection_counts: dict[str, int]
    blocked: list[RejectedCandidate] = field(default_factory=list)
    runtime_seconds: float = 0.0

    def metrics(self) -> dict[str, Any]:
        elevations = [c.elevation_m for c in self.candidates]
        slopes = [c.slope_deg for c in self.candidates]
        return {
            "grid_point_count": self.grid_point_count,
            "candidate_count": len(self.candidates),
            "mandatory_count": sum(1 for c in self.candidates if c.is_mandatory),
            "rejection_counts": self.rejection_counts,
            "elevation_m": {
                "min": min(elevations) if elevations else None,
                "max": max(elevations) if elevations else None,
                "mean": float(np.mean(elevations)) if elevations else None,
            },
            "slope_deg": {
                "min": min(slopes) if slopes else None,
                "max": max(slopes) if slopes else None,
                "mean": float(np.mean(slopes)) if slopes else None,
            },
            "runtime_seconds": self.runtime_seconds,
        }


def build_grid(
    geometry: BaseGeometry,
    spacing_m: float,
    *,
    jitter_m: float = 0.0,
    seed: int = 0,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Regular grid of points covering a geometry's bounding box, in metres.

    Points are generated from the bounding box origin outwards, so the grid is
    anchored to the study area and not to the raster: two runs with the same
    area and spacing produce the same coordinates.

    Any jitter is drawn from a seeded generator, so it is reproducible too.
    """
    if spacing_m <= 0:
        msg = "Grid spacing must be positive, in metres"
        raise InvalidInputError(msg, details={"spacing_m": spacing_m})

    minx, miny, maxx, maxy = geometry.bounds
    # Half a cell of inset centres the grid inside the bounding box instead of
    # hugging its edges.
    xs = np.arange(minx + spacing_m / 2.0, maxx, spacing_m)
    ys = np.arange(miny + spacing_m / 2.0, maxy, spacing_m)
    if xs.size == 0 or ys.size == 0:
        return np.empty(0, dtype=np.float64), np.empty(0, dtype=np.float64)

    total = xs.size * ys.size
    if total > MAX_GRID_POINTS:
        msg = (
            f"Grid of {total:,} points is too large; increase spacing_m (limit {MAX_GRID_POINTS:,})"
        )
        raise InvalidInputError(msg, details={"grid_points": int(total), "spacing_m": spacing_m})

    grid_x, grid_y = np.meshgrid(xs, ys, indexing="xy")
    flat_x = grid_x.ravel()
    flat_y = grid_y.ravel()

    if jitter_m > 0:
        rng = np.random.default_rng(seed)
        flat_x = flat_x + rng.uniform(-jitter_m, jitter_m, size=flat_x.size)
        flat_y = flat_y + rng.uniform(-jitter_m, jitter_m, size=flat_y.size)

    return flat_x, flat_y


def _sample_at(
    array: NDArray[np.floating[Any]],
    rows: NDArray[np.intp],
    cols: NDArray[np.intp],
) -> NDArray[np.float64]:
    return array[rows, cols].astype(np.float64)


def _thin_by_separation(
    candidates: list[Candidate], min_separation_m: float
) -> tuple[list[Candidate], int]:
    """Greedy thinning: keep the best site, drop everything within its radius.

    Deterministic by construction. Candidates are ordered by score descending
    with coordinates as the tie-break, and a uniform spatial hash keeps the
    neighbour search local instead of quadratic.
    """
    if min_separation_m <= 0:
        return candidates, 0

    ordered = sorted(
        candidates,
        key=lambda c: (not c.is_mandatory, -c.score, c.x_m, c.y_m),
    )

    cell = min_separation_m
    buckets: dict[tuple[int, int], list[Candidate]] = {}
    kept: list[Candidate] = []
    dropped = 0

    for candidate in ordered:
        bucket_x = int(candidate.x_m // cell)
        bucket_y = int(candidate.y_m // cell)

        too_close = False
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for other in buckets.get((bucket_x + dx, bucket_y + dy), ()):
                    if (candidate.x_m - other.x_m) ** 2 + (
                        candidate.y_m - other.y_m
                    ) ** 2 < min_separation_m**2:
                        too_close = True
                        break
                if too_close:
                    break
            if too_close:
                break

        if too_close:
            # A mandatory site is never dropped: two of them closer than the
            # separation is the operator's decision, not ours to override.
            if candidate.is_mandatory:
                kept.append(candidate)
                buckets.setdefault((bucket_x, bucket_y), []).append(candidate)
                continue
            dropped += 1
            continue

        kept.append(candidate)
        buckets.setdefault((bucket_x, bucket_y), []).append(candidate)

    return kept, dropped


def generate_candidates(
    surface_path: Path,
    study_area_projected: BaseGeometry,
    parameters: CandidateParameters | None = None,
    *,
    exclusion_zones: list[BaseGeometry] | None = None,
    required_sites: list[tuple[float, float]] | None = None,
    blocked_sites: list[tuple[float, float]] | None = None,
) -> CandidateGenerationResult:
    """Generate candidate Sentinel positions over a study area.

    Args:
        surface_path: Analysis DEM, in the project's metric CRS.
        study_area_projected: Study area in that same CRS. Candidates never
            fall outside it, whatever the surface covers.
        parameters: Grid and filter settings.
        exclusion_zones: Geometries, same CRS, where no Sentinel may go.
        required_sites: Coordinates that must appear in the result (existing
            towers, buildings). They bypass every terrain filter.
        blocked_sites: Coordinates the operator has ruled out.

    Raises:
        InvalidInputError: on a non-metric surface, a bad parameter, or a
            surface that does not cover the study area.
    """
    params = (parameters or CandidateParameters()).validated()
    started = time.perf_counter()
    rejections: Counter[str] = Counter()

    with rasterio.open(surface_path) as surface:
        if surface.crs is None:
            msg = "Candidate generation needs a georeferenced surface"
            raise InvalidInputError(msg, details={"path": surface_path.name})
        crs = surface.crs.to_string()
        require_metric_crs(crs)

        resolution_x, resolution_y = float(surface.res[0]), float(surface.res[1])
        elevation = surface.read(1, masked=True)
        transform = surface.transform
        height, width = elevation.shape

        filled = elevation.filled(np.nan).astype(np.float64)
        valid_mask = ~np.isnan(filled)
        if not valid_mask.any():
            msg = "The analysis surface contains no valid elevation values"
            raise InvalidInputError(msg, details={"path": surface_path.name})

        # Derivatives are computed once over the whole surface and then sampled,
        # rather than per point: vectorised NumPy instead of a Python loop.
        neutral = np.where(valid_mask, filled, float(np.nanmean(filled)))
        slope = compute_slope_degrees(
            neutral, resolution_x_m=resolution_x, resolution_y_m=resolution_y
        )
        prominence = compute_local_prominence(
            neutral,
            resolution_x_m=resolution_x,
            resolution_y_m=resolution_y,
            radius_m=params.prominence_radius_m,
        )

    grid_x, grid_y = build_grid(
        study_area_projected, params.spacing_m, jitter_m=params.jitter_m, seed=params.seed
    )
    grid_point_count = int(grid_x.size)

    prepared_area = prep(study_area_projected)
    prepared_exclusions = [prep(zone) for zone in (exclusion_zones or [])]
    blocked_points = list(blocked_sites or [])

    accepted: list[Candidate] = []
    blocked_records: list[RejectedCandidate] = []

    # Map every grid point to a raster cell in one vectorised step.
    inverse = ~transform
    cols_f, rows_f = inverse * (grid_x, grid_y)
    cols = np.floor(cols_f).astype(np.intp)
    rows = np.floor(rows_f).astype(np.intp)
    inside_raster = (rows >= 0) & (rows < height) & (cols >= 0) & (cols < width)

    blocked_radius = max(params.spacing_m / 2.0, 1.0)

    for index in range(grid_point_count):
        x = float(grid_x[index])
        y = float(grid_y[index])
        point = Point(x, y)

        if not prepared_area.contains(point):
            rejections[RejectionReason.OUTSIDE_AREA] += 1
            continue
        if not inside_raster[index]:
            rejections[RejectionReason.NODATA] += 1
            continue

        row = int(rows[index])
        col = int(cols[index])
        if not valid_mask[row, col]:
            rejections[RejectionReason.NODATA] += 1
            continue

        if any(zone.intersects(point) for zone in prepared_exclusions):
            rejections[RejectionReason.EXCLUDED_ZONE] += 1
            continue

        if any((x - bx) ** 2 + (y - by) ** 2 <= blocked_radius**2 for bx, by in blocked_points):
            rejections[RejectionReason.BLOCKED_SITE] += 1
            blocked_records.append(RejectedCandidate(x, y, RejectionReason.BLOCKED_SITE))
            continue

        elevation_m = float(filled[row, col])
        if params.min_elevation_m is not None and elevation_m < params.min_elevation_m:
            rejections[RejectionReason.ELEVATION_OUT_OF_RANGE] += 1
            continue
        if params.max_elevation_m is not None and elevation_m > params.max_elevation_m:
            rejections[RejectionReason.ELEVATION_OUT_OF_RANGE] += 1
            continue

        slope_deg = float(slope[row, col])
        if slope_deg > params.max_slope_deg:
            rejections[RejectionReason.SLOPE_TOO_STEEP] += 1
            continue

        accepted.append(
            Candidate(
                x_m=x,
                y_m=y,
                elevation_m=elevation_m,
                slope_deg=slope_deg,
                prominence_m=float(prominence[row, col]),
            )
        )

    accepted.extend(
        _sample_required_sites(
            required_sites or [],
            filled=filled,
            valid_mask=valid_mask,
            slope=slope,
            prominence=prominence,
            transform=transform,
            width=width,
            height=height,
        )
    )

    kept, dropped = _thin_by_separation(accepted, params.min_separation_m)
    if dropped:
        rejections[RejectionReason.TOO_CLOSE] += dropped

    # Best sites first, mandatory ones always at the front. The order is part
    # of the result: it is what the Phase 4 optimizer will iterate.
    kept.sort(key=lambda c: (not c.is_mandatory, -c.score, c.x_m, c.y_m))

    if params.max_candidates is not None and len(kept) > params.max_candidates:
        rejections[RejectionReason.MAX_CANDIDATES] += len(kept) - params.max_candidates
        kept = kept[: params.max_candidates]

    runtime = time.perf_counter() - started
    result = CandidateGenerationResult(
        candidates=kept,
        crs=crs,
        parameters=params,
        grid_point_count=grid_point_count,
        rejection_counts={str(reason): count for reason, count in sorted(rejections.items())},
        blocked=blocked_records,
        runtime_seconds=runtime,
    )
    _log.info(
        "candidates_generated",
        crs=crs,
        spacing_m=params.spacing_m,
        grid_points=grid_point_count,
        accepted=len(kept),
        rejections=result.rejection_counts,
        runtime_seconds=round(runtime, 3),
    )
    return result


def _sample_required_sites(
    required_sites: list[tuple[float, float]],
    *,
    filled: NDArray[np.float64],
    valid_mask: NDArray[np.bool_],
    slope: NDArray[np.float32],
    prominence: NDArray[np.float32],
    transform: Any,
    width: int,
    height: int,
) -> list[Candidate]:
    """Turn operator-supplied coordinates into mandatory candidates.

    They bypass slope, elevation and exclusion filters: an existing tower is a
    fact, not a proposal. Terrain values are still sampled so the site can be
    compared with the rest; a site outside the surface gets NaN-free defaults.
    """
    inverse = ~transform
    sites: list[Candidate] = []
    for x, y in required_sites:
        col_f, row_f = inverse * (x, y)
        col, row = int(np.floor(col_f)), int(np.floor(row_f))
        inside = 0 <= row < height and 0 <= col < width and bool(valid_mask[row, col])
        sites.append(
            Candidate(
                x_m=float(x),
                y_m=float(y),
                elevation_m=float(filled[row, col]) if inside else 0.0,
                slope_deg=float(slope[row, col]) if inside else 0.0,
                prominence_m=float(prominence[row, col]) if inside else 0.0,
                is_mandatory=True,
                source="required_site",
            )
        )
    return sites
