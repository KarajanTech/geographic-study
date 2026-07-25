"""Viewshed mask storage: GeoTIFF, packed bits, and the overlay preview."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio import Affine

from app.geo.viewshed import (
    read_packed_bitset,
    write_mask_geotiff,
    write_packed_bitset,
    write_visibility_preview_png,
)

TRANSFORM = Affine(25.0, 0.0, 400_000.0, 0.0, -25.0, 4_500_000.0)


@pytest.fixture
def mask() -> np.ndarray:
    rng = np.random.default_rng(4)
    return rng.random((37, 53)) > 0.5


def test_mask_geotiff_round_trips_the_boolean_array(tmp_path: Path, mask: np.ndarray) -> None:
    path = tmp_path / "mask.tif"

    write_mask_geotiff(path, mask, "EPSG:25830", TRANSFORM)

    with rasterio.open(path) as dataset:
        assert dataset.crs.to_epsg() == 25830
        assert dataset.transform == TRANSFORM
        assert dataset.nodata == 255
        assert dataset.dtypes[0] == "uint8"
        restored = dataset.read(1).astype(bool)

    assert np.array_equal(restored, mask)


def test_packed_bitset_round_trips_the_boolean_array(tmp_path: Path, mask: np.ndarray) -> None:
    path = tmp_path / "mask.npz"

    write_packed_bitset(path, mask)
    restored = read_packed_bitset(path)

    assert restored.shape == mask.shape
    assert np.array_equal(restored, mask)


def test_packed_bitset_is_smaller_than_one_byte_per_cell(tmp_path: Path) -> None:
    """The whole point of packing: 8 cells per byte, not 1."""
    large_mask = np.ones((1000, 1000), dtype=bool)
    path = tmp_path / "mask.npz"

    write_packed_bitset(path, large_mask)

    assert path.stat().st_size < large_mask.size // 4


def test_preview_png_is_transparent_where_not_visible(tmp_path: Path, mask: np.ndarray) -> None:
    path = tmp_path / "preview.png"

    write_visibility_preview_png(path, mask)

    assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    with rasterio.open(path) as dataset:
        rgba = dataset.read()
    alpha = rgba[3]
    assert np.array_equal(alpha > 0, mask)


def test_preview_png_uses_the_frontend_accent_colour(tmp_path: Path, mask: np.ndarray) -> None:
    path = tmp_path / "preview.png"

    write_visibility_preview_png(path, mask)

    with rasterio.open(path) as dataset:
        rgba = dataset.read()
    visible_pixel = tuple(rgba[:, mask][:, 0])
    assert visible_pixel == (63, 185, 80, 165)
