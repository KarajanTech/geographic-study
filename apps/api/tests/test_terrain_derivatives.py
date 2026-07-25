"""Slope and local prominence, the terrain values candidates are filtered on."""

from __future__ import annotations

import numpy as np
import pytest

from app.core.errors import InvalidInputError
from app.geo.terrain import compute_local_prominence, compute_slope_degrees


def test_flat_terrain_has_zero_slope() -> None:
    flat = np.full((16, 16), 500.0, dtype=np.float32)

    slope = compute_slope_degrees(flat, resolution_x_m=25.0, resolution_y_m=25.0)

    assert np.allclose(slope, 0.0, atol=1e-4)


def test_a_45_degree_ramp_is_measured_correctly() -> None:
    """Rising 1 m per 1 m of run is exactly a 45 degree slope."""
    size = 20
    resolution = 10.0
    ramp = np.tile(np.arange(size, dtype=np.float32) * resolution, (size, 1))

    slope = compute_slope_degrees(ramp, resolution_x_m=resolution, resolution_y_m=resolution)

    # Away from the padded edges, where the gradient is exact.
    assert slope[5:-5, 5:-5] == pytest.approx(45.0, abs=0.5)


def test_steeper_ramp_gives_a_larger_angle() -> None:
    size = 20
    gentle = np.tile(np.arange(size, dtype=np.float32) * 1.0, (size, 1))
    steep = np.tile(np.arange(size, dtype=np.float32) * 10.0, (size, 1))

    gentle_slope = compute_slope_degrees(gentle, resolution_x_m=10.0, resolution_y_m=10.0)
    steep_slope = compute_slope_degrees(steep, resolution_x_m=10.0, resolution_y_m=10.0)

    assert steep_slope.mean() > gentle_slope.mean()


def test_slope_is_a_real_angle_bounded_by_90_degrees() -> None:
    rng = np.random.default_rng(3)
    wild = rng.normal(0.0, 10_000.0, size=(32, 32)).astype(np.float32)

    slope = compute_slope_degrees(wild, resolution_x_m=1.0, resolution_y_m=1.0)

    assert slope.min() >= 0.0
    assert slope.max() <= 90.0


def test_finer_cells_measure_the_same_terrain_as_steeper() -> None:
    """The same elevation change over a smaller run is a steeper angle."""
    ramp = np.tile(np.arange(20, dtype=np.float32) * 10.0, (20, 1))

    coarse = compute_slope_degrees(ramp, resolution_x_m=100.0, resolution_y_m=100.0)
    fine = compute_slope_degrees(ramp, resolution_x_m=10.0, resolution_y_m=10.0)

    assert fine.mean() > coarse.mean()


def test_zero_cell_size_is_rejected() -> None:
    with pytest.raises(InvalidInputError):
        compute_slope_degrees(
            np.zeros((4, 4), dtype=np.float32), resolution_x_m=0.0, resolution_y_m=25.0
        )


def test_a_summit_has_positive_prominence() -> None:
    size = 41
    yy, xx = np.mgrid[0:size, 0:size]
    center = size // 2
    dist = np.hypot(xx - center, yy - center)
    summit = (500.0 - dist * 5.0).astype(np.float32)  # a cone, peak at the centre

    prominence = compute_local_prominence(
        summit, resolution_x_m=25.0, resolution_y_m=25.0, radius_m=250.0
    )

    assert prominence[center, center] > 0.0


def test_a_valley_has_negative_prominence() -> None:
    size = 41
    yy, xx = np.mgrid[0:size, 0:size]
    center = size // 2
    dist = np.hypot(xx - center, yy - center)
    valley = (dist * 5.0).astype(np.float32)  # inverted cone, low at the centre

    prominence = compute_local_prominence(
        valley, resolution_x_m=25.0, resolution_y_m=25.0, radius_m=250.0
    )

    assert prominence[center, center] < 0.0


def test_flat_terrain_has_zero_prominence_everywhere() -> None:
    flat = np.full((20, 20), 300.0, dtype=np.float32)

    prominence = compute_local_prominence(
        flat, resolution_x_m=25.0, resolution_y_m=25.0, radius_m=100.0
    )

    assert np.allclose(prominence, 0.0, atol=1e-4)


def test_prominence_is_deterministic() -> None:
    rng = np.random.default_rng(9)
    terrain = rng.normal(500.0, 50.0, size=(30, 30)).astype(np.float32)

    first = compute_local_prominence(
        terrain, resolution_x_m=25.0, resolution_y_m=25.0, radius_m=200.0
    )
    second = compute_local_prominence(
        terrain, resolution_x_m=25.0, resolution_y_m=25.0, radius_m=200.0
    )

    assert np.array_equal(first, second)


def test_negative_radius_is_rejected() -> None:
    with pytest.raises(InvalidInputError):
        compute_local_prominence(
            np.zeros((10, 10), dtype=np.float32),
            resolution_x_m=25.0,
            resolution_y_m=25.0,
            radius_m=-10.0,
        )


def test_prominence_zero_cell_size_is_rejected() -> None:
    with pytest.raises(InvalidInputError):
        compute_local_prominence(
            np.zeros((10, 10), dtype=np.float32),
            resolution_x_m=0.0,
            resolution_y_m=25.0,
            radius_m=100.0,
        )
