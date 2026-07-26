"""Real elevation data: fetch, mosaic and reproject Mapzen/AWS Terrarium tiles.

`fetch_dem_utm` is the only function other modules should call. It owns the
AOI+range-buffer contract (callers pass the raw AOI bbox and a buffer distance;
this module fetches enough terrain to cover every candidate's full sensor
range, not just the bare AOI) and the CRS logic (source tiles are EPSG:3857,
output is a local UTM zone picked from the AOI center).
"""
from __future__ import annotations

import math
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import requests
from affine import Affine
from PIL import Image
from rasterio.crs import CRS
from rasterio.warp import Resampling, reproject, transform_bounds

TERRARIUM_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
WGS84 = CRS.from_epsg(4326)

_MERCATOR_EXTENT = 20037508.342789244  # meters, half-circumference of EPSG:3857's square world
_TILE_PX = 256


class TerrainFetchError(RuntimeError):
    pass


def deg2num(lat_deg: float, lon_deg: float, zoom: int) -> tuple[float, float]:
    """Standard slippy-map lon/lat -> fractional tile index."""
    lat_rad = math.radians(lat_deg)
    n = 2.0**zoom
    xtile = (lon_deg + 180.0) / 360.0 * n
    ytile = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
    return xtile, ytile


def buffer_bbox_deg(
    bbox_wgs84: tuple[float, float, float, float], buffer_m: float
) -> tuple[float, float, float, float]:
    """Expand a WGS84 bbox by buffer_m in every direction (approximate, via
    the bbox's own center latitude -- adequate for tile-fetch padding)."""
    lon_min, lat_min, lon_max, lat_max = bbox_wgs84
    center_lat = (lat_min + lat_max) / 2.0
    dlat = buffer_m / 111_320.0
    dlon = buffer_m / (111_320.0 * math.cos(math.radians(center_lat)))
    return (lon_min - dlon, lat_min - dlat, lon_max + dlon, lat_max + dlat)


def utm_crs_for_lonlat(lon: float, lat: float) -> CRS:
    zone = int(math.floor((lon + 180.0) / 6.0)) + 1
    epsg = (32600 if lat >= 0 else 32700) + zone
    return CRS.from_epsg(epsg)


def tiles_for_bbox(bbox_wgs84: tuple[float, float, float, float], zoom: int) -> tuple[int, int, int, int]:
    """Returns inclusive tile index range (x0, y0, x1, y1) covering bbox."""
    lon_min, lat_min, lon_max, lat_max = bbox_wgs84
    lat_min_c = max(lat_min, -85.0511)
    lat_max_c = min(lat_max, 85.0511)
    x0f, y0f = deg2num(lat_max_c, lon_min, zoom)
    x1f, y1f = deg2num(lat_min_c, lon_max, zoom)
    x0, x1 = int(math.floor(x0f)), int(math.floor(x1f))
    y0, y1 = int(math.floor(y0f)), int(math.floor(y1f))
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


def decode_terrarium(rgb: np.ndarray) -> np.ndarray:
    """rgb: (..., 3) uint8 -> elevation in meters, float32."""
    r = rgb[..., 0].astype(np.float32)
    g = rgb[..., 1].astype(np.float32)
    b = rgb[..., 2].astype(np.float32)
    return (r * 256.0 + g + b / 256.0) - 32768.0


def _tile_cache_path(cache_dir: Path, zoom: int, x: int, y: int) -> Path:
    return cache_dir / "terrarium" / str(zoom) / str(x) / f"{y}.png"


def fetch_tile_png(x: int, y: int, zoom: int, cache_dir: Path, timeout: float = 20.0) -> np.ndarray:
    """Fetch (or load from disk cache) one Terrarium tile, decoded to elevation."""
    path = _tile_cache_path(cache_dir, zoom, x, y)
    if path.exists():
        rgb = np.array(Image.open(path).convert("RGB"))
    else:
        n = 2**zoom
        url = TERRARIUM_URL.format(z=zoom, x=x % n, y=y)
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(resp.content)
        rgb = np.array(Image.open(path).convert("RGB"))
    return decode_terrarium(rgb)


def mosaic_tiles(
    x0: int, y0: int, x1: int, y1: int, zoom: int, cache_dir: Path, max_workers: int = 12
) -> tuple[np.ndarray, Affine, CRS]:
    """Concurrently fetch and paste a contiguous rectangle of tiles.

    Returns the mosaic in its native CRS (EPSG:3857).
    """
    nx, ny = x1 - x0 + 1, y1 - y0 + 1
    mosaic = np.full((ny * _TILE_PX, nx * _TILE_PX), np.nan, dtype=np.float32)

    def _load(ix: int, iy: int) -> tuple[int, int, np.ndarray]:
        return ix, iy, fetch_tile_png(x0 + ix, y0 + iy, zoom, cache_dir)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_load, ix, iy) for iy in range(ny) for ix in range(nx)]
        for fut in as_completed(futures):
            ix, iy, elev = fut.result()
            if np.all(elev == 0.0):
                warnings.warn(
                    f"Tile z={zoom} x={x0 + ix} y={y0 + iy} decoded to a uniform 0m "
                    "(Terrarium's ocean/no-data convention) -- verify the bbox is over land.",
                    stacklevel=2,
                )
            mosaic[iy * _TILE_PX : (iy + 1) * _TILE_PX, ix * _TILE_PX : (ix + 1) * _TILE_PX] = elev

    tile_size_m = (2 * _MERCATOR_EXTENT) / (2**zoom)
    left = -_MERCATOR_EXTENT + x0 * tile_size_m
    top = _MERCATOR_EXTENT - y0 * tile_size_m
    px = tile_size_m / _TILE_PX
    transform = Affine(px, 0.0, left, 0.0, -px, top)
    return mosaic, transform, CRS.from_epsg(3857)


def compute_dst_grid(
    bbox_wgs84: tuple[float, float, float, float], resolution_m: float, dst_crs: CRS
) -> tuple[Affine, int, int]:
    """Canonical destination grid for a bbox: a north-up transform at a fixed
    resolution, sized to fully contain the bbox. Both terrain.py and
    landcover.py must reproject onto the *same* (transform, width, height)
    for the two rasters to stay pixel-aligned."""
    minx, miny, maxx, maxy = transform_bounds(WGS84, dst_crs, *bbox_wgs84)
    width = max(1, math.ceil((maxx - minx) / resolution_m))
    height = max(1, math.ceil((maxy - miny) / resolution_m))
    transform = Affine(resolution_m, 0.0, minx, 0.0, -resolution_m, maxy)
    return transform, width, height


def pixel_window_for_bbox(
    bbox_wgs84: tuple[float, float, float, float], transform: Affine, dst_crs: CRS, width: int, height: int
) -> tuple[int, int, int, int]:
    """Returns a half-open pixel window (row0, row1, col0, col1) into a raster
    of the given transform/shape covering bbox_wgs84, clipped to the raster's
    own bounds. Used to crop the AOI-only eval grid out of the AOI+halo
    working grid via an exact integer-pixel slice (no second reprojection,
    so it can't introduce misalignment)."""
    minx, miny, maxx, maxy = transform_bounds(WGS84, dst_crs, *bbox_wgs84)
    col0f, row0f = ~transform * (minx, maxy)
    col1f, row1f = ~transform * (maxx, miny)
    row0 = max(0, int(math.floor(min(row0f, row1f))))
    row1 = min(height, int(math.ceil(max(row0f, row1f))))
    col0 = max(0, int(math.floor(min(col0f, col1f))))
    col1 = min(width, int(math.ceil(max(col0f, col1f))))
    return row0, row1, col0, col1


def fetch_dem_utm(
    aoi_bbox_wgs84: tuple[float, float, float, float],
    buffer_m: float,
    zoom: int,
    cache_dir: Path,
    dst_resolution_m: float = 30.0,
) -> tuple[np.ndarray, Affine, CRS]:
    """The only function other modules should call for elevation.

    Buffers the AOI by `buffer_m` (callers pass sensor.max_range_m) before
    fetching, so candidates near the AOI edge still get full-range rays --
    this buffering happens here, it is not the caller's responsibility.

    Returns (bare_earth_m float32, transform, utm_crs) covering AOI+halo, in
    a UTM zone chosen from the AOI's center.
    """
    cache_dir = Path(cache_dir).expanduser()
    # Small safety margin beyond the theoretical minimum so legitimate
    # boundary candidates don't spuriously hit the array edge from rounding.
    padded_bbox = buffer_bbox_deg(aoi_bbox_wgs84, buffer_m + 2 * dst_resolution_m)

    center_lon = (aoi_bbox_wgs84[0] + aoi_bbox_wgs84[2]) / 2.0
    center_lat = (aoi_bbox_wgs84[1] + aoi_bbox_wgs84[3]) / 2.0
    utm_crs = utm_crs_for_lonlat(center_lon, center_lat)

    x0, y0, x1, y1 = tiles_for_bbox(padded_bbox, zoom)
    src_mosaic, src_transform, src_crs = mosaic_tiles(x0, y0, x1, y1, zoom, cache_dir)

    dst_transform, width, height = compute_dst_grid(padded_bbox, dst_resolution_m, utm_crs)
    dst = np.full((height, width), np.nan, dtype=np.float32)
    reproject(
        source=src_mosaic,
        destination=dst,
        src_transform=src_transform,
        src_crs=src_crs,
        dst_transform=dst_transform,
        dst_crs=utm_crs,
        resampling=Resampling.bilinear,
        src_nodata=np.nan,
        dst_nodata=np.nan,
    )
    if np.isnan(dst).all():
        raise TerrainFetchError("Reprojected DEM is entirely NaN -- check the AOI bbox.")
    return dst, dst_transform, utm_crs
