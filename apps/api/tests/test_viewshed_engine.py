"""Line-of-sight viewshed algorithm: the roadmap's critical terrain tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from app.core.errors import InvalidInputError
from app.geo.viewshed import (
    MAX_MAX_DISTANCE_M,
    MIN_MAX_DISTANCE_M,
    LineOfSightViewshedEngine,
    compute_cache_key,
)

RESOLUTION_M = 25.0
ORIGIN_X = 400_000.0
ORIGIN_Y = 4_500_000.0


def _write_dem(path: Path, elevation: np.ndarray) -> None:
    height, width = elevation.shape
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=width,
        height=height,
        count=1,
        dtype="float32",
        crs="EPSG:25830",
        transform=from_origin(ORIGIN_X, ORIGIN_Y, RESOLUTION_M, RESOLUTION_M),
        nodata=-9999.0,
    ) as dataset:
        dataset.write(elevation.astype(np.float32), 1)


def _cell_center(col: int, row: int) -> tuple[float, float]:
    return ORIGIN_X + (col + 0.5) * RESOLUTION_M, ORIGIN_Y - (row + 0.5) * RESOLUTION_M


@pytest.fixture
def flat_dem(tmp_path: Path) -> Path:
    path = tmp_path / "flat.tif"
    _write_dem(path, np.full((160, 160), 500.0))
    return path


@pytest.fixture
def ridge_dem(tmp_path: Path) -> Path:
    """Flat terrain with a tall north-south ridge between two open plains."""
    path = tmp_path / "ridge.tif"
    elevation = np.full((160, 160), 500.0)
    elevation[:, 78:82] = 650.0  # a 150 m wall, 100 m wide
    _write_dem(path, elevation)
    return path


def test_flat_terrain_is_visible_everywhere_within_range(flat_dem: Path) -> None:
    """'una superficie plana genera cobertura circular limitada por alcance'."""
    engine = LineOfSightViewshedEngine()
    observer_x, observer_y = _cell_center(80, 80)

    result = engine.compute(flat_dem, observer_x, observer_y, 10.0, 0.0, 1500.0)

    assert result.visible_cell_count / result.total_cell_count > 0.99


def test_flat_terrain_coverage_is_bounded_by_max_distance(flat_dem: Path) -> None:
    engine = LineOfSightViewshedEngine()
    observer_x, observer_y = _cell_center(80, 80)

    near = engine.compute(flat_dem, observer_x, observer_y, 10.0, 0.0, 500.0)
    far = engine.compute(flat_dem, observer_x, observer_y, 10.0, 0.0, 1500.0)

    assert far.total_cell_count > near.total_cell_count
    assert far.visible_cell_count > near.visible_cell_count


def test_a_ridge_blocks_the_far_side(ridge_dem: Path) -> None:
    """'una barrera elevada crea sombra'."""
    engine = LineOfSightViewshedEngine()
    # Observer well east of the ridge (low column), looking across it.
    observer_x, observer_y = _cell_center(30, 80)

    result = engine.compute(ridge_dem, observer_x, observer_y, 2.0, 0.0, 3000.0)

    inverse = ~result.transform
    in_front_col, in_front_row = inverse * _cell_center(60, 80)
    behind_col, behind_row = inverse * _cell_center(120, 80)

    assert result.visible[int(in_front_row), int(in_front_col)]
    assert not result.visible[int(behind_row), int(behind_col)]


def test_a_ridge_shadow_shrinks_as_target_height_rises(ridge_dem: Path) -> None:
    """'cambiar la altura objetivo modifica la cobertura'."""
    engine = LineOfSightViewshedEngine()
    observer_x, observer_y = _cell_center(30, 80)

    ground = engine.compute(ridge_dem, observer_x, observer_y, 2.0, 0.0, 3000.0)
    raised = engine.compute(ridge_dem, observer_x, observer_y, 2.0, 200.0, 3000.0)

    # Raising the target above the ridge can only add visibility, never remove it.
    assert raised.visible_cell_count > ground.visible_cell_count
    assert np.all(raised.visible[ground.visible])


def test_higher_observer_sees_more_than_a_ground_level_one(ridge_dem: Path) -> None:
    engine = LineOfSightViewshedEngine()
    observer_x, observer_y = _cell_center(30, 80)

    low = engine.compute(ridge_dem, observer_x, observer_y, 1.0, 0.0, 3000.0)
    high = engine.compute(ridge_dem, observer_x, observer_y, 100.0, 0.0, 3000.0)

    assert high.visible_cell_count >= low.visible_cell_count


def test_earth_curvature_reduces_visibility_at_long_range(flat_dem: Path) -> None:
    """Over a long enough range, curvature must start to matter."""
    engine = LineOfSightViewshedEngine()
    observer_x, observer_y = _cell_center(80, 80)

    curved = engine.compute(
        flat_dem, observer_x, observer_y, 2.0, 0.0, 2000.0, use_earth_curvature=True
    )
    flat_earth = engine.compute(
        flat_dem, observer_x, observer_y, 2.0, 0.0, 2000.0, use_earth_curvature=False
    )

    assert curved.visible_cell_count <= flat_earth.visible_cell_count


def test_observer_cell_is_always_visible(flat_dem: Path) -> None:
    engine = LineOfSightViewshedEngine()
    observer_x, observer_y = _cell_center(80, 80)

    result = engine.compute(flat_dem, observer_x, observer_y, 10.0, 0.0, 500.0)

    inverse = ~result.transform
    col, row = inverse * (observer_x, observer_y)
    assert result.visible[int(row), int(col)]


def test_observer_outside_the_surface_is_rejected(flat_dem: Path) -> None:
    engine = LineOfSightViewshedEngine()

    with pytest.raises(InvalidInputError):
        engine.compute(flat_dem, ORIGIN_X - 10_000.0, ORIGIN_Y, 10.0, 0.0, 500.0)


def test_observer_on_a_nodata_cell_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "hole.tif"
    elevation = np.full((40, 40), 500.0)
    elevation[20, 20] = -9999.0
    _write_dem(path, elevation)

    engine = LineOfSightViewshedEngine()
    observer_x, observer_y = _cell_center(20, 20)

    with pytest.raises(InvalidInputError):
        engine.compute(path, observer_x, observer_y, 10.0, 0.0, 500.0)


@pytest.mark.parametrize("max_distance_m", [MIN_MAX_DISTANCE_M - 1.0, MAX_MAX_DISTANCE_M + 1.0])
def test_out_of_range_max_distance_is_rejected(flat_dem: Path, max_distance_m: float) -> None:
    engine = LineOfSightViewshedEngine()
    observer_x, observer_y = _cell_center(80, 80)

    with pytest.raises(InvalidInputError):
        engine.compute(flat_dem, observer_x, observer_y, 10.0, 0.0, max_distance_m)


def test_surface_without_crs_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "no_crs.tif"
    with rasterio.open(
        path, "w", driver="GTiff", width=20, height=20, count=1, dtype="float32"
    ) as dataset:
        dataset.write(np.full((20, 20), 500.0, dtype=np.float32), 1)

    engine = LineOfSightViewshedEngine()
    with pytest.raises(InvalidInputError):
        engine.compute(path, ORIGIN_X, ORIGIN_Y, 10.0, 0.0, 500.0)


def test_computation_is_deterministic(ridge_dem: Path) -> None:
    engine = LineOfSightViewshedEngine()
    observer_x, observer_y = _cell_center(30, 80)

    first = engine.compute(ridge_dem, observer_x, observer_y, 2.0, 0.0, 1000.0)
    second = engine.compute(ridge_dem, observer_x, observer_y, 2.0, 0.0, 1000.0)

    assert np.array_equal(first.visible, second.visible)
    assert first.visible_cell_count == second.visible_cell_count


# --- Cache key ----------------------------------------------------------------


def _key(**overrides: object) -> str:
    base: dict[str, object] = {
        "surface_checksum": "abc123",
        "observer_x": 1.0,
        "observer_y": 2.0,
        "observer_height_m": 10.0,
        "target_height_m": 0.0,
        "max_distance_m": 1000.0,
        "use_earth_curvature": True,
        "refraction_coefficient": 0.13,
    }
    base.update(overrides)
    return compute_cache_key(**base)  # type: ignore[arg-type]


def test_cache_key_is_deterministic() -> None:
    assert _key() == _key()


@pytest.mark.parametrize(
    "overrides",
    [
        {"surface_checksum": "different"},
        {"observer_x": 1.0001},
        {"observer_y": 2.0001},
        {"observer_height_m": 10.1},
        {"target_height_m": 0.1},
        {"max_distance_m": 1000.1},
        {"use_earth_curvature": False},
        {"refraction_coefficient": 0.14},
    ],
)
def test_cache_key_changes_with_every_input(overrides: dict[str, object]) -> None:
    assert _key(**overrides) != _key()
