"""Candidate grid, sampling, filtering and thinning."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Point, box
from shapely.geometry.base import BaseGeometry

from app.core.errors import InvalidInputError
from app.geo.candidates import (
    CandidateParameters,
    RejectionReason,
    build_grid,
    generate_candidates,
)

# ---------------------------------------------------------------------------
# Grid


def test_grid_covers_the_bounding_box_at_the_requested_spacing() -> None:
    area = box(0.0, 0.0, 1000.0, 1000.0)

    xs, ys = build_grid(area, spacing_m=100.0)

    assert xs.size == ys.size == 100  # 10 x 10
    assert xs.min() >= 0.0
    assert xs.max() <= 1000.0


def test_grid_spacing_changes_the_point_count_coherently() -> None:
    area = box(0.0, 0.0, 1000.0, 1000.0)

    coarse_x, _ = build_grid(area, spacing_m=200.0)
    fine_x, _ = build_grid(area, spacing_m=100.0)

    assert fine_x.size > coarse_x.size


def test_grid_is_deterministic() -> None:
    area = box(0.0, 0.0, 500.0, 500.0)

    first_x, first_y = build_grid(area, spacing_m=50.0)
    second_x, second_y = build_grid(area, spacing_m=50.0)

    assert np.array_equal(first_x, second_x)
    assert np.array_equal(first_y, second_y)


def test_jitter_is_seeded_and_reproducible() -> None:
    area = box(0.0, 0.0, 500.0, 500.0)

    first_x, first_y = build_grid(area, spacing_m=50.0, jitter_m=10.0, seed=42)
    second_x, second_y = build_grid(area, spacing_m=50.0, jitter_m=10.0, seed=42)

    assert np.array_equal(first_x, second_x)
    assert np.array_equal(first_y, second_y)


def test_different_seeds_jitter_differently() -> None:
    area = box(0.0, 0.0, 500.0, 500.0)

    x_a, _ = build_grid(area, spacing_m=50.0, jitter_m=10.0, seed=1)
    x_b, _ = build_grid(area, spacing_m=50.0, jitter_m=10.0, seed=2)

    assert not np.array_equal(x_a, x_b)


def test_zero_spacing_is_rejected() -> None:
    with pytest.raises(InvalidInputError):
        build_grid(box(0, 0, 100, 100), spacing_m=0.0)


def test_an_enormous_grid_is_rejected() -> None:
    huge_area = box(0.0, 0.0, 1_000_000.0, 1_000_000.0)

    with pytest.raises(InvalidInputError):
        build_grid(huge_area, spacing_m=1.0)


def test_empty_geometry_produces_no_grid_points() -> None:
    tiny = box(0.0, 0.0, 1.0, 1.0)  # smaller than the spacing

    xs, ys = build_grid(tiny, spacing_m=100.0)

    assert xs.size == 0
    assert ys.size == 0


# ---------------------------------------------------------------------------
# Fixtures local to this module: a simple metric surface with a known slope.


@pytest.fixture
def flat_surface(tmp_path: Path) -> Path:
    """A flat 2 x 2 km surface at 25 m resolution, entirely valid."""
    path = tmp_path / "flat.tif"
    size = 80
    elevation = np.full((size, size), 500.0, dtype=np.float32)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=size,
        height=size,
        count=1,
        dtype="float32",
        crs="EPSG:25830",
        transform=from_origin(400_000.0, 4_500_000.0, 25.0, 25.0),
        nodata=-9999.0,
    ) as dataset:
        dataset.write(elevation, 1)
    return path


@pytest.fixture
def ramped_surface(tmp_path: Path) -> Path:
    """A surface with a steep half and a flat half, both within the same area."""
    path = tmp_path / "ramp.tif"
    size = 80
    columns = np.arange(size, dtype=np.float32)
    # Steep on the left half (up to 45+ degrees over 25 m cells), flat on the right.
    ramp = np.where(columns < size / 2, columns * 20.0, columns[int(size / 2)] * 20.0)
    elevation = np.tile(ramp, (size, 1)).astype(np.float32)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=size,
        height=size,
        count=1,
        dtype="float32",
        crs="EPSG:25830",
        transform=from_origin(400_000.0, 4_500_000.0, 25.0, 25.0),
        nodata=-9999.0,
    ) as dataset:
        dataset.write(elevation, 1)
    return path


def _full_area(surface_path: Path) -> BaseGeometry:
    with rasterio.open(surface_path) as dataset:
        return box(*dataset.bounds)


# ---------------------------------------------------------------------------
# generate_candidates


def test_flat_surface_produces_one_candidate_per_grid_point(flat_surface: Path) -> None:
    area = _full_area(flat_surface)

    result = generate_candidates(flat_surface, area, CandidateParameters(spacing_m=200.0))

    assert len(result.candidates) == result.grid_point_count
    assert all(c.slope_deg == pytest.approx(0.0, abs=1e-3) for c in result.candidates)


def test_steep_terrain_is_rejected_by_max_slope(ramped_surface: Path) -> None:
    area = _full_area(ramped_surface)
    params = CandidateParameters(spacing_m=100.0, max_slope_deg=10.0)

    result = generate_candidates(ramped_surface, area, params)

    assert all(c.slope_deg <= 10.0 for c in result.candidates)
    assert result.rejection_counts.get(str(RejectionReason.SLOPE_TOO_STEEP), 0) > 0


def test_relaxing_max_slope_admits_more_candidates(ramped_surface: Path) -> None:
    area = _full_area(ramped_surface)

    strict = generate_candidates(
        ramped_surface, area, CandidateParameters(spacing_m=100.0, max_slope_deg=5.0)
    )
    lenient = generate_candidates(
        ramped_surface, area, CandidateParameters(spacing_m=100.0, max_slope_deg=89.0)
    )

    assert len(lenient.candidates) > len(strict.candidates)


def test_candidates_never_fall_outside_the_study_area(flat_surface: Path) -> None:
    with rasterio.open(flat_surface) as dataset:
        left, bottom, _, _ = dataset.bounds
    # A smaller area than the surface: candidates must respect it, not the raster.
    small_area = box(left + 500, bottom + 500, left + 1000, bottom + 1000)

    result = generate_candidates(flat_surface, small_area, CandidateParameters(spacing_m=50.0))

    for candidate in result.candidates:
        assert small_area.contains(Point(candidate.x_m, candidate.y_m))
    assert result.rejection_counts.get(str(RejectionReason.OUTSIDE_AREA), 0) == 0


def test_elevation_band_filters_candidates(tmp_path: Path) -> None:
    path = tmp_path / "graded.tif"
    size = 40
    rows = np.arange(size, dtype=np.float32).reshape(-1, 1)
    elevation = np.tile(rows * 10.0, (1, size)).astype(np.float32)  # 0..390 m north-south
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=size,
        height=size,
        count=1,
        dtype="float32",
        crs="EPSG:25830",
        transform=from_origin(400_000.0, 4_500_000.0, 25.0, 25.0),
        nodata=-9999.0,
    ) as dataset:
        dataset.write(elevation, 1)

    area = _full_area(path)
    result = generate_candidates(
        path,
        area,
        CandidateParameters(spacing_m=50.0, min_elevation_m=100.0, max_elevation_m=200.0),
    )

    assert all(100.0 <= c.elevation_m <= 200.0 for c in result.candidates)
    assert result.rejection_counts.get(str(RejectionReason.ELEVATION_OUT_OF_RANGE), 0) > 0


def test_exclusion_zone_removes_candidates_inside_it(flat_surface: Path) -> None:
    area = _full_area(flat_surface)
    minx, miny, maxx, maxy = area.bounds
    exclusion = box(minx, miny, (minx + maxx) / 2, maxy)  # left half excluded

    result = generate_candidates(
        flat_surface,
        area,
        CandidateParameters(spacing_m=100.0),
        exclusion_zones=[exclusion],
    )

    assert all(c.x_m > (minx + maxx) / 2 for c in result.candidates)
    assert result.rejection_counts.get(str(RejectionReason.EXCLUDED_ZONE), 0) > 0


def test_required_sites_are_mandatory_and_bypass_filters(ramped_surface: Path) -> None:
    """A required site on very steep ground must still appear."""
    area = _full_area(ramped_surface)
    minx, miny, _, maxy = area.bounds
    steep_point = (minx + 10.0, (miny + maxy) / 2)  # deep in the steep half

    result = generate_candidates(
        ramped_surface,
        area,
        CandidateParameters(spacing_m=200.0, max_slope_deg=1.0),
        required_sites=[steep_point],
    )

    mandatory = [c for c in result.candidates if c.is_mandatory]
    assert len(mandatory) == 1
    assert mandatory[0].source == "required_site"
    assert mandatory[0].x_m == pytest.approx(steep_point[0])


def test_blocked_sites_are_recorded_and_excluded(flat_surface: Path) -> None:
    area = _full_area(flat_surface)
    spacing = 100.0
    xs, ys = build_grid(area, spacing_m=spacing)
    # A blocked site placed exactly on a grid vertex is guaranteed to remove it.
    blocked_point = (float(xs[len(xs) // 2]), float(ys[len(ys) // 2]))

    result = generate_candidates(
        flat_surface,
        area,
        CandidateParameters(spacing_m=spacing),
        blocked_sites=[blocked_point],
    )

    assert len(result.blocked) >= 1
    assert result.blocked[0].reason == RejectionReason.BLOCKED_SITE
    for candidate in result.candidates:
        assert (candidate.x_m - blocked_point[0]) ** 2 + (
            candidate.y_m - blocked_point[1]
        ) ** 2 > 1.0


def test_min_separation_thins_candidates_deterministically(flat_surface: Path) -> None:
    area = _full_area(flat_surface)
    params = CandidateParameters(spacing_m=50.0, min_separation_m=150.0)

    first = generate_candidates(flat_surface, area, params)
    second = generate_candidates(flat_surface, area, params)

    assert [(round(c.x_m, 3), round(c.y_m, 3)) for c in first.candidates] == [
        (round(c.x_m, 3), round(c.y_m, 3)) for c in second.candidates
    ]
    assert result_min_pairwise_distance(first.candidates) >= 150.0 - 1e-6


def result_min_pairwise_distance(candidates: list) -> float:  # type: ignore[type-arg]
    """Smallest distance between any two candidates, for the separation test."""
    best = float("inf")
    for i, a in enumerate(candidates):
        for b in candidates[i + 1 :]:
            dist = ((a.x_m - b.x_m) ** 2 + (a.y_m - b.y_m) ** 2) ** 0.5
            best = min(best, dist)
    return best if best != float("inf") else 0.0


def test_min_separation_prefers_higher_prominence(tmp_path: Path) -> None:
    """Between two close points, the thinning keeps the one with more prominence."""
    path = tmp_path / "twin_peaks.tif"
    size = 60
    yy, xx = np.mgrid[0:size, 0:size]
    # Two peaks close together; the left one taller.
    left = 200.0 * np.exp(-(((xx - 15) ** 2 + (yy - 30) ** 2) / (2 * 8.0**2)))
    right = 100.0 * np.exp(-(((xx - 25) ** 2 + (yy - 30) ** 2) / (2 * 8.0**2)))
    elevation = (500.0 + left + right).astype(np.float32)

    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=size,
        height=size,
        count=1,
        dtype="float32",
        crs="EPSG:25830",
        transform=from_origin(400_000.0, 4_500_000.0, 25.0, 25.0),
        nodata=-9999.0,
    ) as dataset:
        dataset.write(elevation, 1)

    area = _full_area(path)
    result = generate_candidates(
        path,
        area,
        CandidateParameters(spacing_m=25.0, min_separation_m=400.0, prominence_radius_m=150.0),
    )

    # The tallest peak's neighbourhood should dominate the kept set: the best
    # surviving candidate sits on the left (taller) side, not the right.
    assert len(result.candidates) >= 1
    midpoint_x = 400_000.0 + 20 * 25.0  # halfway between the two peak columns
    best = max(result.candidates, key=lambda c: c.prominence_m)
    assert best.x_m < midpoint_x


def test_max_candidates_keeps_the_best_ranked(flat_surface: Path) -> None:
    area = _full_area(flat_surface)

    result = generate_candidates(
        flat_surface, area, CandidateParameters(spacing_m=50.0, max_candidates=5)
    )

    assert len(result.candidates) == 5
    assert result.rejection_counts.get(str(RejectionReason.MAX_CANDIDATES), 0) > 0


def test_candidates_are_ordered_best_first(tmp_path: Path) -> None:
    path = tmp_path / "single_peak.tif"
    size = 60
    yy, xx = np.mgrid[0:size, 0:size]
    peak = 300.0 * np.exp(-(((xx - 30) ** 2 + (yy - 30) ** 2) / (2 * 10.0**2)))
    elevation = (500.0 + peak).astype(np.float32)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=size,
        height=size,
        count=1,
        dtype="float32",
        crs="EPSG:25830",
        transform=from_origin(400_000.0, 4_500_000.0, 25.0, 25.0),
        nodata=-9999.0,
    ) as dataset:
        dataset.write(elevation, 1)

    area = _full_area(path)
    result = generate_candidates(path, area, CandidateParameters(spacing_m=50.0))

    scores = [c.score for c in result.candidates]
    assert scores == sorted(scores, reverse=True)


def test_generation_is_reproducible_end_to_end(ramped_surface: Path) -> None:
    area = _full_area(ramped_surface)
    params = CandidateParameters(spacing_m=100.0, max_slope_deg=15.0, min_separation_m=100.0)

    first = generate_candidates(ramped_surface, area, params)
    second = generate_candidates(ramped_surface, area, params)

    assert len(first.candidates) == len(second.candidates)
    for a, b in zip(first.candidates, second.candidates, strict=True):
        assert a.x_m == b.x_m
        assert a.y_m == b.y_m


def test_ungeoreferenced_surface_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "no_crs.tif"
    with rasterio.open(
        path, "w", driver="GTiff", width=16, height=16, count=1, dtype="float32"
    ) as dataset:
        dataset.write(np.full((16, 16), 500.0, dtype=np.float32), 1)

    with pytest.raises(InvalidInputError):
        generate_candidates(path, box(0, 0, 100, 100), CandidateParameters())


def test_inconsistent_elevation_bounds_are_rejected() -> None:
    with pytest.raises(InvalidInputError):
        CandidateParameters(min_elevation_m=500.0, max_elevation_m=100.0).validated()


def test_jitter_must_be_smaller_than_half_spacing() -> None:
    with pytest.raises(InvalidInputError):
        CandidateParameters(spacing_m=100.0, jitter_m=60.0).validated()
