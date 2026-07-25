"""Web preview rendering.

The frontend needs an image it can place on a map, not a GeoTIFF. A preview is
a display artefact: it is downsampled, it carries an alpha channel for nodata,
and no measurement is ever taken from it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
import rasterio.shutil
from numpy.typing import NDArray
from rasterio.enums import Resampling
from rasterio.io import MemoryFile
from rasterio.warp import transform_bounds

from app.geo.crs import WGS84
from app.geo.raster import RasterBounds

MAX_PREVIEW_PX = 1024


@dataclass(frozen=True, slots=True)
class PreviewResult:
    """A PNG plus the geographic corners needed to position it on a map."""

    path: Path
    width: int
    height: int
    bounds_wgs84: RasterBounds
    bounds_source_crs: RasterBounds
    source_crs: str


def write_png_preview(
    source_path: Path,
    destination_path: Path,
    *,
    max_size_px: int = MAX_PREVIEW_PX,
) -> PreviewResult:
    """Render a single-band raster to a greyscale PNG with transparent nodata.

    The image keeps the source aspect ratio and is capped at ``max_size_px`` on
    its longest side, so a large DEM does not become a large download.
    """
    destination_path.parent.mkdir(parents=True, exist_ok=True)

    with rasterio.open(source_path) as source:
        scale = min(1.0, max_size_px / max(source.width, source.height))
        out_width = max(1, round(source.width * scale))
        out_height = max(1, round(source.height * scale))

        data = source.read(
            1,
            out_shape=(out_height, out_width),
            resampling=Resampling.average,
            masked=True,
        )
        source_bounds = RasterBounds(
            left=source.bounds.left,
            bottom=source.bounds.bottom,
            right=source.bounds.right,
            top=source.bounds.top,
        )
        west, south, east, north = transform_bounds(source.crs, WGS84, *source.bounds)
        source_crs = source.crs.to_string()

    grey = _to_grey(data)
    alpha = np.where(np.ma.getmaskarray(data), 0, 255).astype(np.uint8)

    # The PNG driver only supports CreateCopy, so the image is built in memory
    # as a GeoTIFF and then copied out as a PNG.
    with (
        MemoryFile() as memfile,
        memfile.open(
            driver="GTiff",
            width=out_width,
            height=out_height,
            count=2,  # greyscale + alpha
            dtype="uint8",
        ) as tmp,
    ):
        tmp.write(grey, 1)
        tmp.write(alpha, 2)
        rasterio.shutil.copy(tmp, destination_path, driver="PNG")

    return PreviewResult(
        path=destination_path,
        width=out_width,
        height=out_height,
        bounds_wgs84=RasterBounds(left=west, bottom=south, right=east, top=north),
        bounds_source_crs=source_bounds,
        source_crs=source_crs,
    )


def _to_grey(data: np.ma.MaskedArray) -> NDArray[np.uint8]:
    """Stretch valid values to 1-255 using a 2-98 percentile window."""
    if data.dtype == np.uint8:
        return np.ma.filled(data, 0).astype(np.uint8)

    valid = data.compressed()
    if valid.size == 0:
        return np.zeros(data.shape, dtype=np.uint8)

    low, high = np.percentile(valid, [2.0, 98.0])
    if high <= low:
        low, high = float(valid.min()), float(valid.max())
    if high <= low:
        return np.full(data.shape, 128, dtype=np.uint8)

    stretched = (np.ma.filled(data, low) - low) / (high - low)
    result: NDArray[np.uint8] = (np.clip(stretched, 0.0, 1.0) * 254.0 + 1.0).astype(np.uint8)
    return result
