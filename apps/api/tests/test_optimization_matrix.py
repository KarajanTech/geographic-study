"""Embedding per-candidate viewshed masks into a shared candidate-cell matrix."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

from app.core.errors import InvalidInputError
from app.geo.viewshed import write_packed_bitset
from app.optimization.greedy import solve_greedy
from app.optimization.matrix import ViewshedMaskRef, build_candidate_cell_matrix

ORIGIN_X = 400_000.0
ORIGIN_Y = 4_500_000.0
RES = 25.0


@pytest.fixture
def surface(tmp_path: Path) -> Path:
    """A 40x40 surface with a nodata strip down the middle column-wise."""
    path = tmp_path / "surface.tif"
    elevation = np.full((40, 40), 500.0, dtype=np.float32)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=40,
        height=40,
        count=1,
        dtype="float32",
        crs="EPSG:25830",
        transform=from_origin(ORIGIN_X, ORIGIN_Y, RES, RES),
        nodata=-9999.0,
    ) as dataset:
        elevation[:, 20] = -9999.0  # one nodata column
        dataset.write(elevation, 1)
    return path


def _write_local_mask(
    path: Path, row_min: int, col_min: int, height: int, width: int, value: bool = True
) -> tuple[float, float]:
    """Write a packed bitset plus the world coordinates of its top-left corner."""
    mask = np.full((height, width), value, dtype=bool)
    write_packed_bitset(path, mask)
    bounds_left = ORIGIN_X + col_min * RES
    bounds_top = ORIGIN_Y - row_min * RES
    return bounds_left, bounds_top


def test_matrix_shape_matches_valid_cell_count(surface: Path, tmp_path: Path) -> None:
    bitset_path = tmp_path / "a.npz"
    left, top = _write_local_mask(bitset_path, row_min=5, col_min=5, height=10, width=10)
    ref = ViewshedMaskRef("candidate-a", bitset_path, left, top)

    matrix = build_candidate_cell_matrix(surface, [ref])

    # 40x40 grid minus one full nodata column of 40 cells.
    assert matrix.total_valid_cells == 40 * 40 - 40
    assert matrix.candidate_masks[0].shape == (matrix.total_valid_cells,)
    assert matrix.cell_weights.shape == (matrix.total_valid_cells,)


def test_mask_is_embedded_at_the_correct_offset(surface: Path, tmp_path: Path) -> None:
    bitset_path = tmp_path / "a.npz"
    left, top = _write_local_mask(bitset_path, row_min=5, col_min=6, height=4, width=4)
    ref = ViewshedMaskRef("candidate-a", bitset_path, left, top)

    matrix = build_candidate_cell_matrix(surface, [ref])

    with rasterio.open(surface) as dataset:
        nodata_mask = np.ma.getmaskarray(dataset.read(1, masked=True))
    valid_index = np.flatnonzero((~nodata_mask).reshape(-1))

    full = np.zeros(40 * 40, dtype=bool)
    full[valid_index] = matrix.candidate_masks[0]
    full_2d = full.reshape(40, 40)

    assert full_2d[5:9, 6:10].all()
    assert not full_2d[0:5, :].any()
    assert not full_2d[9:, :].any()


def test_two_candidates_produce_two_rows_in_selection_order(surface: Path, tmp_path: Path) -> None:
    left_a, top_a = _write_local_mask(tmp_path / "a.npz", 0, 0, 5, 5)
    left_b, top_b = _write_local_mask(tmp_path / "b.npz", 30, 30, 5, 5)

    matrix = build_candidate_cell_matrix(
        surface,
        [
            ViewshedMaskRef("candidate-a", tmp_path / "a.npz", left_a, top_a),
            ViewshedMaskRef("candidate-b", tmp_path / "b.npz", left_b, top_b),
        ],
    )

    assert matrix.candidate_ids == ["candidate-a", "candidate-b"]
    assert len(matrix.candidate_masks) == 2


def test_nodata_cells_are_excluded_from_the_universe(surface: Path, tmp_path: Path) -> None:
    """A mask covering the nodata column must not inflate the valid universe."""
    bitset_path = tmp_path / "a.npz"
    # Local mask spans columns 18-23 (world), including the nodata column 20.
    left, top = _write_local_mask(bitset_path, row_min=0, col_min=18, height=40, width=6)
    ref = ViewshedMaskRef("candidate-a", bitset_path, left, top)

    matrix = build_candidate_cell_matrix(surface, [ref])

    assert matrix.total_valid_cells == 40 * 40 - 40
    # 40 rows x 5 valid columns (6 minus the 1 nodata column) covered.
    assert matrix.candidate_masks[0].sum() == 40 * 5


def test_cell_area_matches_the_surface_resolution(surface: Path, tmp_path: Path) -> None:
    bitset_path = tmp_path / "a.npz"
    left, top = _write_local_mask(bitset_path, 0, 0, 4, 4)
    ref = ViewshedMaskRef("candidate-a", bitset_path, left, top)

    matrix = build_candidate_cell_matrix(surface, [ref])

    assert matrix.cell_area_km2 == pytest.approx((RES * RES) / 1_000_000.0)


def test_misaligned_mask_is_rejected(surface: Path, tmp_path: Path) -> None:
    bitset_path = tmp_path / "a.npz"
    write_packed_bitset(bitset_path, np.ones((4, 4), dtype=bool))
    # Offset by half a cell: not a whole-pixel crop of this surface.
    ref = ViewshedMaskRef("candidate-a", bitset_path, ORIGIN_X + RES * 0.5, ORIGIN_Y)

    with pytest.raises(InvalidInputError):
        build_candidate_cell_matrix(surface, [ref])


def test_mask_extending_beyond_the_surface_is_rejected(surface: Path, tmp_path: Path) -> None:
    bitset_path = tmp_path / "a.npz"
    write_packed_bitset(bitset_path, np.ones((10, 10), dtype=bool))
    # Placed so it runs off the bottom-right edge of the 40x40 surface.
    ref = ViewshedMaskRef("candidate-a", bitset_path, ORIGIN_X + 35 * RES, ORIGIN_Y - 35 * RES)

    with pytest.raises(InvalidInputError):
        build_candidate_cell_matrix(surface, [ref])


def test_surface_without_crs_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "no_crs.tif"
    with rasterio.open(
        path, "w", driver="GTiff", width=10, height=10, count=1, dtype="float32"
    ) as dataset:
        dataset.write(np.full((10, 10), 500.0, dtype=np.float32), 1)

    with pytest.raises(InvalidInputError):
        build_candidate_cell_matrix(path, [])


def test_empty_viewshed_list_still_reports_the_valid_universe(surface: Path) -> None:
    matrix = build_candidate_cell_matrix(surface, [])

    assert matrix.candidate_ids == []
    assert matrix.candidate_masks == []
    assert matrix.total_valid_cells == 40 * 40 - 40


def test_default_weights_are_uniform(surface: Path, tmp_path: Path) -> None:
    bitset_path = tmp_path / "a.npz"
    left, top = _write_local_mask(bitset_path, 0, 0, 4, 4)
    ref = ViewshedMaskRef("candidate-a", bitset_path, left, top)

    matrix = build_candidate_cell_matrix(surface, [ref])

    assert matrix.cell_weights == pytest.approx(np.ones(matrix.total_valid_cells))
    assert matrix.weights_summary == {"source": "uniform"}


def test_priorities_array_is_normalized_into_cell_weights(surface: Path, tmp_path: Path) -> None:
    bitset_path = tmp_path / "a.npz"
    left, top = _write_local_mask(bitset_path, 0, 0, 4, 4)
    ref = ViewshedMaskRef("candidate-a", bitset_path, left, top)

    priorities = np.zeros((40, 40), dtype=np.float64)
    priorities[:, 21:] = 10.0  # right half more important; column 20 is nodata anyway

    matrix = build_candidate_cell_matrix(surface, [ref], priorities_array=priorities)

    assert matrix.cell_weights.min() == pytest.approx(0.0)
    assert matrix.cell_weights.max() == pytest.approx(1.0)
    assert matrix.weights_summary == {"source": "raster", "normalization": "min_max"}


def test_priorities_array_shape_mismatch_is_rejected(surface: Path, tmp_path: Path) -> None:
    bitset_path = tmp_path / "a.npz"
    left, top = _write_local_mask(bitset_path, 0, 0, 4, 4)
    ref = ViewshedMaskRef("candidate-a", bitset_path, left, top)

    with pytest.raises(InvalidInputError):
        build_candidate_cell_matrix(surface, [ref], priorities_array=np.zeros((10, 10)))


@pytest.fixture
def sloped_surface(tmp_path: Path) -> Path:
    """A 10x10 surface with no nodata, elevation rising from row 0 to row 9."""
    path = tmp_path / "sloped_surface.tif"
    elevation = np.zeros((10, 10), dtype=np.float32)
    for row in range(10):
        elevation[row, :] = row * 100.0
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=10,
        height=10,
        count=1,
        dtype="float32",
        crs="EPSG:25830",
        transform=from_origin(ORIGIN_X, ORIGIN_Y, RES, RES),
        nodata=-9999.0,
    ) as dataset:
        dataset.write(elevation, 1)
    return path


def test_preset_ridge_priority_weights_higher_ground_more(
    sloped_surface: Path, tmp_path: Path
) -> None:
    bitset_path = tmp_path / "a.npz"
    left, top = _write_local_mask(bitset_path, 0, 0, 10, 10)
    ref = ViewshedMaskRef("candidate-a", bitset_path, left, top)

    matrix = build_candidate_cell_matrix(sloped_surface, [ref], preset="ridge_priority")

    weights_2d = matrix.cell_weights.reshape(10, 10)
    assert weights_2d[9].mean() > weights_2d[0].mean()
    assert matrix.weights_summary == {
        "source": "preset",
        "preset": "ridge_priority",
        "normalization": "min_max",
    }


def test_preset_valley_priority_weights_lower_ground_more(
    sloped_surface: Path, tmp_path: Path
) -> None:
    bitset_path = tmp_path / "a.npz"
    left, top = _write_local_mask(bitset_path, 0, 0, 10, 10)
    ref = ViewshedMaskRef("candidate-a", bitset_path, left, top)

    matrix = build_candidate_cell_matrix(sloped_surface, [ref], preset="valley_priority")

    weights_2d = matrix.cell_weights.reshape(10, 10)
    assert weights_2d[0].mean() > weights_2d[9].mean()


def test_preset_uniform_matches_the_default(sloped_surface: Path, tmp_path: Path) -> None:
    bitset_path = tmp_path / "a.npz"
    left, top = _write_local_mask(bitset_path, 0, 0, 10, 10)
    ref = ViewshedMaskRef("candidate-a", bitset_path, left, top)

    matrix = build_candidate_cell_matrix(sloped_surface, [ref], preset="uniform")

    assert matrix.cell_weights == pytest.approx(np.ones(100))
    assert matrix.weights_summary == {"source": "uniform"}


def test_priority_zone_geometry_boosts_only_its_cells(surface: Path, tmp_path: Path) -> None:
    bitset_path = tmp_path / "a.npz"
    left, top = _write_local_mask(bitset_path, 0, 0, 40, 40)
    ref = ViewshedMaskRef("candidate-a", bitset_path, left, top)

    # The left 10 columns of the surface, in its own metric CRS.
    zone = box(ORIGIN_X, ORIGIN_Y - 40 * RES, ORIGIN_X + 10 * RES, ORIGIN_Y)

    matrix = build_candidate_cell_matrix(surface, [ref], priority_zone_geometries=[(zone, 5.0)])

    with rasterio.open(surface) as dataset:
        nodata_mask = np.ma.getmaskarray(dataset.read(1, masked=True))
    valid_index = np.flatnonzero((~nodata_mask).reshape(-1))
    full = np.zeros(40 * 40)
    full[valid_index] = matrix.cell_weights
    full_2d = full.reshape(40, 40)

    assert full_2d[:, :10].mean() == pytest.approx(5.0)
    assert full_2d[:, 30:].mean() == pytest.approx(1.0)
    assert matrix.weights_summary["priority_zones"] == [{"weight": 5.0}]


def test_priority_zone_weight_can_change_which_candidate_wins(
    surface: Path, tmp_path: Path
) -> None:
    """ROADMAP.md Phase 6: "aumentar el peso de una zona puede cambiar la solución"."""
    left_a, top_a = _write_local_mask(tmp_path / "a.npz", row_min=0, col_min=0, height=40, width=19)
    left_b, top_b = _write_local_mask(
        tmp_path / "b.npz", row_min=0, col_min=21, height=40, width=19
    )
    refs = [
        ViewshedMaskRef("candidate-a", tmp_path / "a.npz", left_a, top_a),
        ViewshedMaskRef("candidate-b", tmp_path / "b.npz", left_b, top_b),
    ]

    baseline = build_candidate_cell_matrix(surface, refs)
    baseline_solution = solve_greedy(
        baseline.candidate_masks, baseline.cell_weights, max_sites=1, target_coverage=None
    )
    # Equal-sized disjoint coverage under uniform weights: the deterministic
    # tie-break picks the lower index first.
    assert baseline.candidate_ids[baseline_solution.selected_order[0]] == "candidate-a"

    zone = box(ORIGIN_X + 21 * RES, ORIGIN_Y - 40 * RES, ORIGIN_X + 40 * RES, ORIGIN_Y)
    boosted = build_candidate_cell_matrix(surface, refs, priority_zone_geometries=[(zone, 10.0)])
    boosted_solution = solve_greedy(
        boosted.candidate_masks, boosted.cell_weights, max_sites=1, target_coverage=None
    )

    assert boosted.candidate_ids[boosted_solution.selected_order[0]] == "candidate-b"
