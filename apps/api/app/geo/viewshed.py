"""Viewshed computation.

Answers one question: from an observer at a given point and height, which
cells of the terrain — raised to a target height — have an unobstructed line
of sight, within a maximum range?

The engine is behind an interface (:class:`ViewshedEngine`) precisely so the
algorithm can be replaced or compared later, per ``ARCHITECTURE.md`` §7. GDAL's
own viewshed generator was the suggested default, but its Python bindings
(``osgeo``) are not available alongside the ``rasterio`` wheels this project
uses (see ADR 0002, which deliberately avoided a system GDAL dependency).
:class:`LineOfSightViewshedEngine` is a radial line-of-sight algorithm
implemented in NumPy: for each of a set of angles around the observer, it
walks outward along the ray and marks a cell visible when nothing between the
observer and that cell blocks the sightline.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
import rasterio.shutil
from numpy.typing import NDArray
from rasterio.io import MemoryFile

from app.core.errors import InvalidInputError
from app.geo.crs import require_metric_crs

ALGORITHM_VERSION = "los-radial-sweep-v1"

EARTH_RADIUS_M = 6_371_000.0
DEFAULT_REFRACTION_COEFFICIENT = 0.13

DEFAULT_OBSERVER_HEIGHT_M = 10.0
DEFAULT_TARGET_HEIGHT_M = 0.0
DEFAULT_MAX_DISTANCE_M = 10_000.0
MIN_MAX_DISTANCE_M = 100.0
MAX_MAX_DISTANCE_M = 50_000.0

# Hard cap on the number of angular rays swept, whatever the geometry asks for.
# Keeps a pathological request (huge range on a fine raster) bounded in time.
MAX_RAYS = 20_000


@dataclass(frozen=True, slots=True)
class ViewshedResult:
    """A computed viewshed mask and its geospatial description."""

    visible: NDArray[np.bool_]
    """2D boolean array: True where the cell is visible from the observer."""
    crs: str
    transform: rasterio.Affine
    bounds: tuple[float, float, float, float]
    resolution_m: tuple[float, float]
    visible_cell_count: int
    total_cell_count: int
    observer_elevation_m: float


def compute_cache_key(
    *,
    surface_checksum: str,
    observer_x: float,
    observer_y: float,
    observer_height_m: float,
    target_height_m: float,
    max_distance_m: float,
    use_earth_curvature: bool,
    refraction_coefficient: float,
    algorithm_version: str = ALGORITHM_VERSION,
) -> str:
    """Deterministic cache key per ``ARCHITECTURE.md`` §7.

    Identical inputs always produce the same key, so a repeated request can be
    served from a previously computed :class:`~app.db.models.Viewshed` row
    instead of recomputing.
    """
    payload = "|".join(
        [
            algorithm_version,
            surface_checksum,
            f"{observer_x:.6f}",
            f"{observer_y:.6f}",
            f"{observer_height_m:.3f}",
            f"{target_height_m:.3f}",
            f"{max_distance_m:.3f}",
            "curved" if use_earth_curvature else "flat",
            f"{refraction_coefficient:.4f}",
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ViewshedEngine(ABC):
    """Interface every viewshed implementation must satisfy."""

    algorithm_version: str

    @abstractmethod
    def compute(
        self,
        surface_raster: Path,
        observer_x: float,
        observer_y: float,
        observer_height_m: float,
        target_height_m: float,
        max_distance_m: float,
        *,
        use_earth_curvature: bool = True,
        refraction_coefficient: float = DEFAULT_REFRACTION_COEFFICIENT,
    ) -> ViewshedResult: ...


class LineOfSightViewshedEngine(ViewshedEngine):
    """Radial line-of-sight viewshed over a metric elevation grid.

    For each of ``num_rays`` angles around the observer, walks outward in
    steps of half the cell size and keeps a running maximum elevation angle
    (the horizon so far). A point is visible when its own elevation angle
    meets or exceeds that running maximum — nothing between it and the
    observer has blocked it.

    Earth curvature and atmospheric refraction are applied as the standard
    correction: a point's apparent elevation drops by
    ``distance^2 * (1 - refraction_coefficient) / (2 * earth_radius)``.
    """

    algorithm_version = ALGORITHM_VERSION

    def compute(
        self,
        surface_raster: Path,
        observer_x: float,
        observer_y: float,
        observer_height_m: float,
        target_height_m: float,
        max_distance_m: float,
        *,
        use_earth_curvature: bool = True,
        refraction_coefficient: float = DEFAULT_REFRACTION_COEFFICIENT,
    ) -> ViewshedResult:
        if not MIN_MAX_DISTANCE_M <= max_distance_m <= MAX_MAX_DISTANCE_M:
            msg = (
                f"max_distance_m must be between {MIN_MAX_DISTANCE_M} and "
                f"{MAX_MAX_DISTANCE_M} metres"
            )
            raise InvalidInputError(msg, details={"max_distance_m": max_distance_m})

        with rasterio.open(surface_raster) as dataset:
            if dataset.crs is None:
                msg = "Viewshed needs a georeferenced surface"
                raise InvalidInputError(msg, details={"path": surface_raster.name})
            crs = require_metric_crs(dataset.crs.to_string())

            transform = dataset.transform
            res_x, res_y = float(dataset.res[0]), float(dataset.res[1])
            full_height, full_width = dataset.height, dataset.width

            masked = dataset.read(1, masked=True)
            nodata_mask = np.ma.getmaskarray(masked)
            elevation = masked.filled(np.nan).astype(np.float64)

            inverse = ~transform
            obs_col_f, obs_row_f = inverse * (observer_x, observer_y)
            obs_row, obs_col = int(np.floor(obs_row_f)), int(np.floor(obs_col_f))

            if (
                not (0 <= obs_row < full_height and 0 <= obs_col < full_width)
                or nodata_mask[obs_row, obs_col]
            ):
                msg = "Observer position has no elevation data on this surface"
                raise InvalidInputError(
                    msg, details={"observer_x": observer_x, "observer_y": observer_y}
                )

            observer_elevation = float(elevation[obs_row, obs_col]) + observer_height_m

            radius_cols = int(np.ceil(max_distance_m / res_x)) + 1
            radius_rows = int(np.ceil(max_distance_m / res_y)) + 1
            row_min = max(0, obs_row - radius_rows)
            row_max = min(full_height - 1, obs_row + radius_rows)
            col_min = max(0, obs_col - radius_cols)
            col_max = min(full_width - 1, obs_col + radius_cols)

            sub_elevation = elevation[row_min : row_max + 1, col_min : col_max + 1]
            sub_nodata = nodata_mask[row_min : row_max + 1, col_min : col_max + 1]
            sub_height, sub_width = sub_elevation.shape

            visible = _sweep(
                sub_elevation=sub_elevation,
                sub_nodata=sub_nodata,
                observer_x=observer_x,
                observer_y=observer_y,
                observer_elevation=observer_elevation,
                target_height_m=target_height_m,
                max_distance_m=max_distance_m,
                res_x=res_x,
                res_y=res_y,
                inverse_transform=inverse,
                row_min=row_min,
                col_min=col_min,
                use_earth_curvature=use_earth_curvature,
                refraction_coefficient=refraction_coefficient,
            )

            sub_transform = transform * rasterio.Affine.translation(col_min, row_min)

            # The denominator for a coverage ratio: valid cells actually within
            # range, not every cell of the (necessarily rectangular) bounding
            # box — the box's corners fall outside the circle by construction.
            in_range = _cells_within_range(
                sub_transform, sub_height, sub_width, observer_x, observer_y, max_distance_m
            )

            local_obs_row = obs_row - row_min
            local_obs_col = obs_col - col_min
            visible &= in_range
            visible[local_obs_row, local_obs_col] = True
            visible[sub_nodata] = False

            left, top = sub_transform * (0, 0)
            right, bottom = sub_transform * (sub_width, sub_height)
            valid_total = int((in_range & ~sub_nodata).sum())

            return ViewshedResult(
                visible=visible,
                crs=crs.to_string(),
                transform=sub_transform,
                bounds=(left, bottom, right, top),
                resolution_m=(res_x, res_y),
                visible_cell_count=int(visible.sum()),
                total_cell_count=valid_total,
                observer_elevation_m=observer_elevation,
            )


def _cells_within_range(
    transform: rasterio.Affine,
    height: int,
    width: int,
    observer_x: float,
    observer_y: float,
    max_distance_m: float,
) -> NDArray[np.bool_]:
    """Boolean mask of cells whose centre is within ``max_distance_m``."""
    rows, cols = np.meshgrid(np.arange(height) + 0.5, np.arange(width) + 0.5, indexing="ij")
    xs, ys = transform * (cols, rows)
    distance = np.hypot(xs - observer_x, ys - observer_y)
    within: NDArray[np.bool_] = distance <= max_distance_m
    return within


def _sweep(
    *,
    sub_elevation: NDArray[np.float64],
    sub_nodata: NDArray[np.bool_],
    observer_x: float,
    observer_y: float,
    observer_elevation: float,
    target_height_m: float,
    max_distance_m: float,
    res_x: float,
    res_y: float,
    inverse_transform: rasterio.Affine,
    row_min: int,
    col_min: int,
    use_earth_curvature: bool,
    refraction_coefficient: float,
) -> NDArray[np.bool_]:
    sub_height, sub_width = sub_elevation.shape
    visible = np.zeros((sub_height, sub_width), dtype=bool)

    max_radius_cells = max(max_distance_m / res_x, max_distance_m / res_y)
    # Enough rays that adjacent ray endpoints are about one cell apart at the
    # far edge of the circle, so no cell out there is skipped entirely.
    num_rays = min(MAX_RAYS, max(360, int(2.0 * np.pi * max_radius_cells)))
    angles = np.linspace(0.0, 2.0 * np.pi, num_rays, endpoint=False)

    step_m = min(res_x, res_y) * 0.5
    n_steps = max(1, int(max_distance_m / step_m))
    step_distances = (np.arange(1, n_steps + 1) * step_m).astype(np.float64)
    step_distances = step_distances[step_distances <= max_distance_m]

    curvature_coefficient = (
        (1.0 - refraction_coefficient) / (2.0 * EARTH_RADIUS_M) if use_earth_curvature else 0.0
    )

    for angle in angles:
        dx = np.cos(angle)
        dy = np.sin(angle)
        xs = observer_x + step_distances * dx
        ys = observer_y + step_distances * dy

        cols_f, rows_f = inverse_transform * (xs, ys)
        cols = np.round(cols_f).astype(np.intp) - col_min
        rows = np.round(rows_f).astype(np.intp) - row_min

        in_bounds = (rows >= 0) & (rows < sub_height) & (cols >= 0) & (cols < sub_width)
        if not in_bounds.any():
            continue
        rows, cols, dists = rows[in_bounds], cols[in_bounds], step_distances[in_bounds]

        has_data = ~sub_nodata[rows, cols]
        if not has_data.any():
            continue
        rows, cols, dists = rows[has_data], cols[has_data], dists[has_data]

        elevations = sub_elevation[rows, cols]
        curvature_drop = curvature_coefficient * dists * dists

        # Two series along the same ray: the horizon is built from bare
        # terrain only (an obstacle's height does not depend on what we are
        # trying to see beyond it), while visibility of a point is tested with
        # target_height_m added to *that point alone* — raising it can only
        # help it clear a horizon that intermediate terrain already set.
        terrain_angle = np.arctan2(elevations - curvature_drop - observer_elevation, dists)
        target_angle = np.arctan2(
            elevations + target_height_m - curvature_drop - observer_elevation, dists
        )

        running_max = np.maximum.accumulate(terrain_angle)
        previous_max = np.concatenate(([-np.inf], running_max[:-1]))
        ray_visible = target_angle >= previous_max

        np.logical_or.at(visible, (rows, cols), ray_visible)

    return visible


# --- Storage -------------------------------------------------------------
#
# Two artefacts per computed viewshed, matching ARCHITECTURE.md §8:
#   - a compressed GeoTIFF, for display and export;
#   - a packed-bit array, for the fast bitwise coverage combination the
#     Phase 4 optimizer will need (numpy.packbits, per that section).


def write_mask_geotiff(
    path: Path,
    visible: NDArray[np.bool_],
    crs: str,
    transform: rasterio.Affine,
) -> None:
    """Write a viewshed mask as a single-band uint8 GeoTIFF (0/1, nodata=255)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    height, width = visible.shape
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=width,
        height=height,
        count=1,
        dtype="uint8",
        crs=crs,
        transform=transform,
        nodata=255,
        compress="deflate",
        predictor=2,
    ) as dataset:
        dataset.write(visible.astype(np.uint8), 1)
        dataset.update_tags(processing="viewshed", algorithm_version=ALGORITHM_VERSION)


def write_packed_bitset(path: Path, visible: NDArray[np.bool_]) -> None:
    """Write a viewshed mask as packed bits, for fast bitwise coverage math.

    ``numpy.packbits`` on the flattened mask, per ``ARCHITECTURE.md`` §8;
    ``shape`` is stored alongside so the bits can be unpacked back to a grid.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    packed = np.packbits(visible.flatten())
    np.savez_compressed(path, packed=packed, shape=np.array(visible.shape, dtype=np.int64))


def read_packed_bitset(path: Path) -> NDArray[np.bool_]:
    """Inverse of :func:`write_packed_bitset`."""
    with np.load(path) as data:
        packed = data["packed"]
        shape = tuple(int(v) for v in data["shape"])
    total_cells = shape[0] * shape[1]
    unpacked = np.unpackbits(packed)[:total_cells]
    result: NDArray[np.bool_] = unpacked.reshape(shape).astype(bool)
    return result


def write_visibility_preview_png(path: Path, visible: NDArray[np.bool_]) -> None:
    """Write a map-overlay PNG: green where visible, fully transparent elsewhere.

    A display artefact only — every visibility figure the frontend shows comes
    from the ``Viewshed`` row, never from this image.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    height, width = visible.shape
    rgba = np.zeros((height, width, 4), dtype=np.uint8)
    rgba[visible] = (63, 185, 80, 165)  # matches the frontend's --ok green

    with (
        MemoryFile() as memfile,
        memfile.open(driver="GTiff", width=width, height=height, count=4, dtype="uint8") as tmp,
    ):
        for band in range(4):
            tmp.write(rgba[:, :, band], band + 1)
        rasterio.shutil.copy(tmp, path, driver="PNG")
