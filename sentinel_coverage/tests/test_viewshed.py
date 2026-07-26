import numpy as np
import pytest
from affine import Affine
from rasterio.crs import CRS

from sentinel_coverage.config import SensorSpec
from sentinel_coverage.viewshed import ViewshedGrids, compute_viewshed

UTM31N = CRS.from_epsg(32631)
RES = 10.0
SIZE = 700  # 700x700 px @ 10m = 7x7 km; half-extent (3.5km) > max_range_m used below
CENTER_ROW = CENTER_COL = SIZE // 2


def _grid(surface: np.ndarray, bare_earth: np.ndarray) -> ViewshedGrids:
    # North-up transform: x = col*RES, y = (SIZE*RES) - row*RES.
    transform = Affine(RES, 0.0, 0.0, 0.0, -RES, SIZE * RES)
    return ViewshedGrids(
        surface_m=surface,
        bare_earth_m=bare_earth,
        transform=transform,
        crs=UTM31N,
        eval_window=(0, SIZE, 0, SIZE),
    )


def _observer_xy() -> tuple[float, float]:
    transform = Affine(RES, 0.0, 0.0, 0.0, -RES, SIZE * RES)
    return transform * (CENTER_COL + 0.5, CENTER_ROW + 0.5)


def test_flat_terrain_fully_visible_within_range():
    flat = np.zeros((SIZE, SIZE), dtype=np.float32)
    grids = _grid(flat, flat)
    sensor = SensorSpec(mast_height_m=10.0, target_height_m=0.0, max_range_m=1500.0)

    visible, n_oob = compute_viewshed(grids, _observer_xy(), sensor, n_rays=360)

    row0, row1, col0, col1 = grids.eval_window
    rows, cols = np.meshgrid(np.arange(row0, row1), np.arange(col0, col1), indexing="ij")
    x, y = grids.transform * (cols + 0.5, rows + 0.5)
    ox, oy = _observer_xy()
    dist = np.hypot(x - ox, y - oy)
    within_range = dist <= sensor.max_range_m

    assert n_oob == 0
    # Everything within range on perfectly flat ground must be visible from
    # an elevated mast -- nothing pokes up to block it.
    assert visible[within_range].all()


def test_ridge_casts_a_shadow_directly_behind_it_only():
    flat = np.zeros((SIZE, SIZE), dtype=np.float32)
    surface = flat.copy()
    bare_earth = flat.copy()
    # A 200m ridge ~1000m due east of the observer (col offset +100 @ 10m/px),
    # spanning rows to comfortably block a wide azimuth band around due east.
    ridge_cols = slice(CENTER_COL + 98, CENTER_COL + 102)
    ridge_rows = slice(CENTER_ROW - 60, CENTER_ROW + 60)
    surface[ridge_rows, ridge_cols] = 200.0
    bare_earth[ridge_rows, ridge_cols] = 200.0
    grids = _grid(surface, bare_earth)
    sensor = SensorSpec(mast_height_m=10.0, target_height_m=0.0, max_range_m=3000.0)

    visible, n_oob = compute_viewshed(grids, _observer_xy(), sensor, n_rays=1440)
    ox, oy = _observer_xy()

    def visible_at(dx_m: float, dy_m: float) -> bool:
        x, y = ox + dx_m, oy + dy_m
        col, row = ~grids.transform * (x, y)
        return bool(visible[int(row), int(col)])

    assert n_oob == 0
    # Due east, safely before the ridge (which starts ~970m out): visible.
    assert all(visible_at(d, 0) for d in (300, 600, 900))
    # Due east, safely behind the ridge (flat ground again, but shadowed):
    # hidden. Not asserting on points inside/right at the ridge itself --
    # a flat-topped obstruction legitimately self-shadows its own far side
    # (ratio = height/distance strictly decreases across a constant-height
    # span), so only its single nearest sample is its own visible point.
    # That's correct viewshed behavior, not something to pin to one pixel.
    assert all(visible_at(d, 0) is False for d in (1100, 1500, 2000, 2500))
    # Other azimuths are entirely unaffected by the ridge, at any range.
    assert all(visible_at(0, d) for d in (900, 1500, 2500))
    assert all(visible_at(-d, 0) for d in (900, 1500, 2500))


@pytest.mark.parametrize(
    "distance_m,expected_drop_m",
    [(5_000, 1.71), (10_000, 6.83), (12_000, 9.83), (15_000, 15.36)],
)
def test_curvature_drop_matches_known_values(distance_m, expected_drop_m):
    sensor = SensorSpec()
    assert sensor.curvature_drop_m(distance_m) == pytest.approx(expected_drop_m, abs=0.01)
