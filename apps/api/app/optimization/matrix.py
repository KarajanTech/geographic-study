"""Candidate-cell matrix construction.

Turns the per-candidate viewshed masks Phase 3 computed — each cropped to its
own bounding box around its observer — into rows of one shared boolean matrix
over the surface's full grid, so the greedy optimizer can combine them with
plain array operations.

Every viewshed mask is grid-aligned with the surface it was computed against:
``LineOfSightViewshedEngine.compute`` crops by whole pixels and never
resamples (see ``app.geo.viewshed``). Embedding a local mask into the full
grid is therefore exact array placement, not reprojection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from numpy.typing import NDArray
from rasterio.features import rasterize
from shapely.geometry import mapping
from shapely.geometry.base import BaseGeometry

from app.core.errors import InvalidInputError
from app.geo.viewshed import read_packed_bitset
from app.optimization.weights import (
    PriorityZoneMask,
    WeightPreset,
    apply_priority_zones,
    normalize_weights,
    preset_weights,
)

# Grid-aligned offsets are exact integers in theory; this only absorbs
# floating point noise from the affine transform round trip.
ALIGNMENT_TOLERANCE = 1e-6


@dataclass(frozen=True, slots=True)
class ViewshedMaskRef:
    """What the matrix builder needs from one computed viewshed."""

    candidate_site_id: str
    bitset_path: Path
    bounds_left: float
    bounds_top: float


@dataclass(frozen=True, slots=True)
class CandidateCellMatrix:
    """One boolean row per candidate, all aligned to the same valid-cell universe."""

    candidate_ids: list[str]
    candidate_masks: list[NDArray[np.bool_]]
    cell_weights: NDArray[np.float64]
    cell_area_km2: float
    total_valid_cells: int
    weights_summary: dict[str, Any] = field(default_factory=lambda: {"source": "uniform"})


def build_candidate_cell_matrix(
    surface_path: Path,
    viewsheds: list[ViewshedMaskRef],
    *,
    priorities_array: NDArray[np.floating] | None = None,
    preset: WeightPreset | None = None,
    priority_zone_geometries: list[tuple[BaseGeometry, float]] | None = None,
) -> CandidateCellMatrix:
    """Embed every viewshed mask into the surface grid and flatten to valid cells.

    Args:
        surface_path: The analysis DEM every viewshed in ``viewsheds`` was
            computed against.
        viewsheds: One reference per candidate to include.
        priorities_array: A risk/priority raster already aligned to
            ``surface_path``'s exact grid (see
            ``app.geo.warp.resample_to_reference``) — min-max normalized and
            used as the base cell weight. Takes precedence over ``preset``.
        preset: A named terrain-derived weight preset, used when no
            ``priorities_array`` is given. ``None`` or ``"uniform"`` weights
            every cell equally, matching Phase 4.
        priority_zone_geometries: Zones (in the surface's own CRS) whose cells
            get their weight multiplied by the paired factor, on top of
            whichever base weight was chosen above.

    Raises:
        InvalidInputError: if the surface has no CRS, no valid cells, a
            viewshed mask does not align with or fit inside the surface grid,
            or ``priorities_array`` does not match the surface's shape — any
            of which means the inputs do not actually belong together.
    """
    with rasterio.open(surface_path) as dataset:
        if dataset.crs is None:
            msg = "Surface has no CRS; cannot build a candidate-cell matrix"
            raise InvalidInputError(msg, details={"path": surface_path.name})
        transform = dataset.transform
        height, width = dataset.height, dataset.width
        res_x, res_y = float(dataset.res[0]), float(dataset.res[1])
        band = dataset.read(1, masked=True)
        nodata_mask = np.ma.getmaskarray(band)
        elevation = np.ma.getdata(band)

    valid_mask = ~nodata_mask
    valid_flat_index = np.flatnonzero(valid_mask.reshape(-1))
    total_valid_cells = int(valid_flat_index.size)
    if total_valid_cells == 0:
        msg = "Surface has no valid cells"
        raise InvalidInputError(msg, details={"path": surface_path.name})

    inverse = ~transform
    candidate_ids: list[str] = []
    candidate_masks: list[NDArray[np.bool_]] = []

    for ref in viewsheds:
        local_mask = read_packed_bitset(ref.bitset_path)
        local_height, local_width = local_mask.shape

        col_f, row_f = inverse * (ref.bounds_left, ref.bounds_top)
        col_min, row_min = round(col_f), round(row_f)
        if abs(col_f - col_min) > ALIGNMENT_TOLERANCE or abs(row_f - row_min) > ALIGNMENT_TOLERANCE:
            msg = "Viewshed mask is not grid-aligned with the surface"
            raise InvalidInputError(
                msg,
                details={
                    "candidate_site_id": ref.candidate_site_id,
                    "col_offset": col_f,
                    "row_offset": row_f,
                },
            )
        if (
            row_min < 0
            or col_min < 0
            or row_min + local_height > height
            or col_min + local_width > width
        ):
            msg = "Viewshed mask extends beyond the surface it was computed from"
            raise InvalidInputError(
                msg,
                details={
                    "candidate_site_id": ref.candidate_site_id,
                    "row_min": row_min,
                    "col_min": col_min,
                },
            )

        full_mask = np.zeros((height, width), dtype=bool)
        full_mask[row_min : row_min + local_height, col_min : col_min + local_width] = local_mask

        candidate_ids.append(ref.candidate_site_id)
        candidate_masks.append(full_mask.reshape(-1)[valid_flat_index])

    weights_summary: dict[str, Any]
    if priorities_array is not None:
        if priorities_array.shape != (height, width):
            msg = "Priorities raster does not match the surface's grid"
            raise InvalidInputError(
                msg,
                details={
                    "priorities_shape": priorities_array.shape,
                    "surface_shape": (height, width),
                },
            )
        base_weights = normalize_weights(priorities_array.reshape(-1)[valid_flat_index])
        weights_summary = {"source": "raster", "normalization": "min_max"}
    elif preset is not None and preset != "uniform":
        elevation_flat = elevation.reshape(-1)[valid_flat_index]
        base_weights = preset_weights(preset, elevation_flat)
        weights_summary = {"source": "preset", "preset": preset, "normalization": "min_max"}
    else:
        base_weights = np.ones(total_valid_cells, dtype=np.float64)
        weights_summary = {"source": "uniform"}

    zone_masks: list[PriorityZoneMask] = []
    for geometry, zone_weight in priority_zone_geometries or []:
        rasterized = rasterize(
            [(mapping(geometry), 1)],
            out_shape=(height, width),
            transform=transform,
            fill=0,
            dtype="uint8",
        )
        zone_masks.append(
            PriorityZoneMask(
                weight=zone_weight,
                mask=rasterized.reshape(-1)[valid_flat_index].astype(bool),
            )
        )
    cell_weights = apply_priority_zones(base_weights, zone_masks) if zone_masks else base_weights
    if zone_masks:
        weights_summary["priority_zones"] = [{"weight": z.weight} for z in zone_masks]

    return CandidateCellMatrix(
        candidate_ids=candidate_ids,
        candidate_masks=candidate_masks,
        cell_weights=cell_weights,
        cell_area_km2=(res_x * res_y) / 1_000_000.0,
        total_valid_cells=total_valid_cells,
        weights_summary=weights_summary,
    )
