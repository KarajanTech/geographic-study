"""Core geometry: radial horizon-sweep viewshed for one Sentinel candidate.

This is a geometric line-of-sight coverage model, not a smoke-detection
probability model -- actual detection also depends on plume size,
atmospheric visibility and camera zoom, none of which are represented here.

Algorithm (standard horizon-tracking / sweep viewshed, as used by GRASS
r.viewshed): march outward along many azimuth rays from the observer,
maintaining the maximum obstruction-angle-tangent seen so far on each ray
("horizon so far"). A point is visible if its own angle-tangent to the
observer exceeds the horizon accumulated from everything strictly nearer on
its azimuth. Angle comparisons are done as raw tangent ratios (monotonic, so
equivalent to comparing angles directly) to avoid unnecessary arctan calls.

Two elevation surfaces are used for two different purposes and must never be
conflated:
- `surface_m` (bare earth + canopy) is what can BLOCK a ray.
- `bare_earth_m` + `target_height_m` is what is being tested for visibility.
  Using the canopy-inclusive surface here would double-count canopy height
  and silently redefine what `target_height_m=0` means.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from affine import Affine
from rasterio.crs import CRS
from scipy.ndimage import map_coordinates

from .config import SensorSpec
from .terrain import pixel_window_for_bbox


@dataclass
class ViewshedGrids:
    """Terrain data covering AOI+halo, plus the pixel window that crops the
    AOI-only evaluation grid out of it. The crop is an exact integer-pixel
    slice (not a second reprojection), so it can't introduce misalignment.
    """

    surface_m: np.ndarray  # AOI+halo, obstruction surface (bare earth + canopy)
    bare_earth_m: np.ndarray  # AOI+halo, same shape/transform, bare earth only
    transform: Affine
    crs: CRS
    eval_window: tuple[int, int, int, int]  # (row0, row1, col0, col1)

    @property
    def eval_shape(self) -> tuple[int, int]:
        row0, row1, col0, col1 = self.eval_window
        return row1 - row0, col1 - col0

    @property
    def resolution_m(self) -> float:
        return abs(self.transform.a)


def build_viewshed_grids(
    bare_earth_m: np.ndarray,
    canopy_height_m: np.ndarray,
    transform: Affine,
    crs: CRS,
    aoi_bbox_wgs84: tuple[float, float, float, float],
) -> ViewshedGrids:
    from .surface import build_surface_model

    height, width = bare_earth_m.shape
    eval_window = pixel_window_for_bbox(aoi_bbox_wgs84, transform, crs, width, height)
    surface_m = build_surface_model(bare_earth_m, canopy_height_m)
    return ViewshedGrids(surface_m, bare_earth_m, transform, crs, eval_window)


def compute_viewshed(
    grids: ViewshedGrids,
    observer_xy: tuple[float, float],
    sensor: SensorSpec,
    n_rays: int = 720,
    ray_step_m: float | None = None,
) -> tuple[np.ndarray, int]:
    """Returns (visible: bool array shaped like grids.eval_shape, n_out_of_bounds
    ray samples -- a diagnostic; nonzero for an interior candidate signals the
    halo buffer was too small)."""
    row0, row1, col0, col1 = grids.eval_window
    step = ray_step_m if ray_step_m is not None else grids.resolution_m / 2.0
    max_range = sensor.max_range_m
    n_steps = max(1, int(math.ceil(max_range / step)))

    d = (np.arange(n_steps, dtype=np.float64) + 1) * step  # d[i] = (i+1)*step
    drop_ray = sensor.curvature_drop_m(d)

    ox, oy = observer_xy
    obs_col_f, obs_row_f = ~grids.transform * (ox, oy)
    obs_row = int(np.clip(round(obs_row_f), 0, grids.bare_earth_m.shape[0] - 1))
    obs_col = int(np.clip(round(obs_col_f), 0, grids.bare_earth_m.shape[1] - 1))
    eye_elev = grids.bare_earth_m[obs_row, obs_col] + sensor.mast_height_m

    theta = np.arange(n_rays, dtype=np.float64) * (2.0 * math.pi / n_rays)
    xs = ox + np.outer(np.cos(theta), d)  # (n_rays, n_steps)
    ys = oy + np.outer(np.sin(theta), d)
    cols, rows = ~grids.transform * (xs, ys)

    surf_samples = map_coordinates(
        grids.surface_m, [rows, cols], order=1, mode="constant", cval=np.nan, prefilter=False
    )
    n_out_of_bounds = int(np.isnan(surf_samples).sum())

    obstruction_ratio = (surf_samples - drop_ray[None, :] - eye_elev) / d[None, :]
    horizon = np.maximum.accumulate(obstruction_ratio, axis=1)  # NaN-propagating: fail-closed
    horizon_before = np.concatenate([np.full((n_rays, 1), -np.inf), horizon[:, :-1]], axis=1)

    eval_rows, eval_cols = np.meshgrid(np.arange(row0, row1), np.arange(col0, col1), indexing="ij")
    cell_x, cell_y = grids.transform * (eval_cols + 0.5, eval_rows + 0.5)
    dx, dy = cell_x - ox, cell_y - oy
    dist = np.hypot(dx, dy)
    theta_cell = np.arctan2(dy, dx) % (2.0 * math.pi)
    ray_j = np.round(theta_cell / (2.0 * math.pi / n_rays)).astype(np.int64) % n_rays
    # horizon_before[:, m] holds the max obstruction ratio from every ray
    # sample strictly nearer than distance m*step. ceil(dist/step)-1 is the
    # count of full ray-steps strictly inside `dist` -- using floor()
    # instead would, at exact multiples of `step` (e.g. a target sitting
    # right on a sample ring), include the sample at the target's own
    # distance and compare the target against itself. Verified against a
    # synthetic ridge: a point exactly on the ridge crest must stay visible.
    step_i = np.clip(np.ceil(dist / step).astype(np.int64) - 1, 0, n_steps - 1)

    target_elev = grids.bare_earth_m[row0:row1, col0:col1] + sensor.target_height_m
    drop_cell = sensor.curvature_drop_m(dist)
    with np.errstate(invalid="ignore", divide="ignore"):
        target_ratio = (target_elev - drop_cell - eye_elev) / dist

    visible = (target_ratio >= horizon_before[ray_j, step_i]) & (dist <= max_range)
    visible |= dist < step  # near-field special case (1.5): nothing meaningful occludes this close
    return visible, n_out_of_bounds


def compute_viewshed_batch(
    grids: ViewshedGrids,
    observer_xy_list: list[tuple[float, float]],
    sensor: SensorSpec,
    n_rays: int = 720,
    ray_step_m: float | None = None,
) -> tuple[np.ndarray, int]:
    """Loop over compute_viewshed -> (n_candidates, n_eval_cells) bool matrix
    plus the total out-of-bounds ray-sample count across all candidates.
    No multiprocessing: single-candidate cost is a few ms, not a bottleneck.
    """
    eval_h, eval_w = grids.eval_shape
    n = len(observer_xy_list)
    out = np.empty((n, eval_h * eval_w), dtype=bool)
    total_out_of_bounds = 0
    for i, xy in enumerate(observer_xy_list):
        visible, n_oob = compute_viewshed(grids, xy, sensor, n_rays=n_rays, ray_step_m=ray_step_m)
        out[i] = visible.reshape(-1)
        total_out_of_bounds += n_oob
    return out, total_out_of_bounds
