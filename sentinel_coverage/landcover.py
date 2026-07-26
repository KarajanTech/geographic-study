"""Vegetation/land-cover: ESA WorldCover 10m, read directly off S3 (no API key).

Provides two derived rasters from the same reprojected class-code array so
they never drift out of alignment with each other: a canopy-height estimate
(used by surface.py to build the line-of-sight obstruction surface) and a
coverage-priority weight (used by optimize.py to value vegetated/flammable
land above water/urban/bare land).

Canopy height is a heuristic derived from land-cover *class*, not a measured
canopy height product -- it should not be presented as ground truth.
"""
from __future__ import annotations

import math

import numpy as np
import rasterio
from affine import Affine
from rasterio.crs import CRS
from rasterio.warp import Resampling, reproject
from rasterio.windows import from_bounds

from .terrain import buffer_bbox_deg

WORLDCOVER_URL = (
    "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
    "ESA_WorldCover_10m_2021_v200_{tile}_Map.tif"
)

# ESA WorldCover v200 class codes -> rough obstruction/canopy height (m).
WORLDCOVER_CANOPY_HEIGHT_M: dict[int, float] = {
    10: 15.0,  # Tree cover
    20: 3.0,  # Shrubland
    30: 0.0,  # Grassland
    40: 0.5,  # Cropland
    50: 6.0,  # Built-up (coarse average building height)
    60: 0.0,  # Bare / sparse vegetation
    70: 0.0,  # Snow and ice
    80: 0.0,  # Permanent water bodies
    90: 0.5,  # Herbaceous wetland
    95: 10.0,  # Mangroves
    100: 0.0,  # Moss and lichen
}

# Coverage priority weight for a wildfire-surveillance study: vegetated /
# flammable land weighted highest, water weighted to zero, everything else
# in between (a mast can still usefully see roads or built-up assets near
# the wildland-urban interface).
WORLDCOVER_COVERAGE_WEIGHT: dict[int, float] = {
    10: 1.0,  # Tree cover
    20: 1.0,  # Shrubland
    30: 0.6,  # Grassland
    40: 0.4,  # Cropland
    50: 0.1,  # Built-up
    60: 0.3,  # Bare / sparse vegetation
    70: 0.2,  # Snow and ice
    80: 0.0,  # Permanent water bodies
    90: 0.5,  # Herbaceous wetland
    95: 0.8,  # Mangroves
    100: 0.2,  # Moss and lichen
}

_DEFAULT_CANOPY_M = 0.0
_DEFAULT_WEIGHT = 0.3


def worldcover_tile_name(lon: float, lat: float) -> str:
    tile_lat = int(math.floor(lat / 3.0) * 3)
    tile_lon = int(math.floor(lon / 3.0) * 3)
    ns = "N" if tile_lat >= 0 else "S"
    ew = "E" if tile_lon >= 0 else "W"
    return f"{ns}{abs(tile_lat):02d}{ew}{abs(tile_lon):03d}"


def tiles_for_bbox(bbox_wgs84: tuple[float, float, float, float]) -> list[str]:
    lon_min, lat_min, lon_max, lat_max = bbox_wgs84
    lat0, lat1 = math.floor(lat_min / 3.0) * 3, math.floor(lat_max / 3.0) * 3
    lon0, lon1 = math.floor(lon_min / 3.0) * 3, math.floor(lon_max / 3.0) * 3
    names = []
    tlat = lat0
    while tlat <= lat1:
        tlon = lon0
        while tlon <= lon1:
            ns = "N" if tlat >= 0 else "S"
            ew = "E" if tlon >= 0 else "W"
            names.append(f"{ns}{abs(int(tlat)):02d}{ew}{abs(int(tlon)):03d}")
            tlon += 3
        tlat += 3
    return names


def _read_tile_window(
    tile: str, bbox_wgs84: tuple[float, float, float, float]
) -> tuple[np.ndarray, Affine, CRS] | None:
    url = WORLDCOVER_URL.format(tile=tile)
    try:
        with rasterio.open(url) as src:
            window = from_bounds(*bbox_wgs84, transform=src.transform)
            if window.width <= 0 or window.height <= 0:
                return None
            data = src.read(1, window=window, boundless=True, fill_value=0)
            window_transform = src.window_transform(window)
            return data, window_transform, src.crs
    except rasterio.errors.RasterioIOError:
        # Tile doesn't exist on S3 (e.g. bbox padding reaches open ocean or
        # a region outside WorldCover's land coverage) -- treat as no data.
        return None


def fetch_landcover_class_utm(
    aoi_bbox_wgs84: tuple[float, float, float, float],
    buffer_m: float,
    dst_transform: Affine,
    dst_shape: tuple[int, int],
    dst_crs: CRS,
) -> np.ndarray:
    """Read WorldCover class codes over AOI+halo and reproject (nearest --
    this is categorical data, never bilinear) onto the exact grid
    terrain.fetch_dem_utm produced. dst_transform/dst_shape/dst_crs must be
    that same (transform, shape, crs) triple, computed once and shared, so
    the elevation and land-cover rasters stay pixel-aligned.
    """
    padded_bbox = buffer_bbox_deg(aoi_bbox_wgs84, buffer_m + 2 * abs(dst_transform.a))
    height, width = dst_shape
    dst = np.zeros((height, width), dtype=np.uint8)  # 0 = "no data" bucket
    covered_any = False

    for tile in tiles_for_bbox(padded_bbox):
        result = _read_tile_window(tile, padded_bbox)
        if result is None:
            continue
        data, src_transform, src_crs = result
        if data.size == 0:
            continue
        piece = np.zeros((height, width), dtype=np.uint8)
        reproject(
            source=data,
            destination=piece,
            src_transform=src_transform,
            src_crs=src_crs,
            dst_transform=dst_transform,
            dst_crs=dst_crs,
            resampling=Resampling.nearest,
            src_nodata=0,
            dst_nodata=0,
        )
        dst = np.where(piece != 0, piece, dst)
        covered_any = True

    if not covered_any:
        raise RuntimeError(f"No WorldCover tiles covered bbox {aoi_bbox_wgs84}")
    return dst


def _lut_apply(codes: np.ndarray, table: dict[int, float], default: float) -> np.ndarray:
    lut = np.full(256, default, dtype=np.float32)
    for code, value in table.items():
        lut[code] = value
    lut[0] = default  # "no data" bucket
    return lut[codes]


def canopy_height_from_classes(codes: np.ndarray) -> np.ndarray:
    return _lut_apply(codes, WORLDCOVER_CANOPY_HEIGHT_M, _DEFAULT_CANOPY_M)


def coverage_weight_from_classes(codes: np.ndarray) -> np.ndarray:
    return _lut_apply(codes, WORLDCOVER_COVERAGE_WEIGHT, _DEFAULT_WEIGHT)
