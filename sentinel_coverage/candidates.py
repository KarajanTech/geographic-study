"""Candidate Sentinel mast positions: a regular grid over the AOI, with
optional filtering. Restricting candidates to local elevation maxima is kept
as an opt-in quality/interpretability refinement, not a performance
necessity -- a plain grid at a few hundred candidates is already cheap for
compute_viewshed_batch (see viewshed.py).
"""
from __future__ import annotations

import numpy as np
from affine import Affine
from scipy.ndimage import map_coordinates, maximum_filter


def generate_candidate_grid(
    aoi_bounds_utm: tuple[float, float, float, float], spacing_m: float
) -> np.ndarray:
    """Regular grid of candidate mast positions covering the AOI bounds (in
    the study's UTM CRS). Returns (N, 2) array of (x, y)."""
    minx, miny, maxx, maxy = aoi_bounds_utm
    xs = np.arange(minx + spacing_m / 2.0, maxx, spacing_m)
    ys = np.arange(miny + spacing_m / 2.0, maxy, spacing_m)
    if xs.size == 0:
        xs = np.array([(minx + maxx) / 2.0])
    if ys.size == 0:
        ys = np.array([(miny + maxy) / 2.0])
    xx, yy = np.meshgrid(xs, ys)
    return np.column_stack([xx.ravel(), yy.ravel()])


def sample_raster_at_points(
    raster: np.ndarray, transform: Affine, points_xy: np.ndarray, order: int = 1
) -> np.ndarray:
    """Sample a raster at world coordinates (order=1 bilinear for continuous
    data like elevation, order=0 nearest for categorical data)."""
    cols, rows = ~transform * (points_xy[:, 0], points_xy[:, 1])
    return map_coordinates(raster, [rows, cols], order=order, mode="nearest")


def attach_elevation(points_xy: np.ndarray, bare_earth_m: np.ndarray, transform: Affine) -> np.ndarray:
    return sample_raster_at_points(bare_earth_m, transform, points_xy, order=1)


def filter_candidates(
    points_xy: np.ndarray,
    bare_earth_m: np.ndarray,
    class_codes: np.ndarray,
    transform: Affine,
    exclude_classes: tuple[int, ...] = (80,),  # 80 = ESA WorldCover "permanent water bodies"
    max_slope_deg: float | None = None,
) -> np.ndarray:
    """Boolean keep-mask: drop candidates on water and, optionally, on
    slopes too steep for a mast foundation."""
    codes_at_points = sample_raster_at_points(class_codes.astype(np.float32), transform, points_xy, order=0)
    keep = np.isin(codes_at_points.round().astype(np.int32), exclude_classes, invert=True)

    if max_slope_deg is not None:
        resolution_m = abs(transform.a)
        gy, gx = np.gradient(bare_earth_m, resolution_m)
        slope_deg = np.degrees(np.arctan(np.hypot(gx, gy)))
        slope_at_points = sample_raster_at_points(slope_deg, transform, points_xy, order=1)
        keep &= slope_at_points <= max_slope_deg

    return keep


def local_maxima_mask(bare_earth_m: np.ndarray, transform: Affine, window_m: float) -> np.ndarray:
    """Optional refinement: boolean mask over bare_earth_m's own pixel grid,
    marking local elevation maxima within a window_m x window_m
    neighborhood. Intersect with a candidate grid to bias placements toward
    physically sensible high ground instead of every grid point."""
    resolution_m = abs(transform.a)
    size_px = max(1, int(round(window_m / resolution_m)))
    local_max = maximum_filter(bare_earth_m, size=size_px, mode="nearest")
    return bare_earth_m >= local_max
