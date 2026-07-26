"""Reprojection and clipping.

Both operations preserve CRS, nodata and units explicitly. The target
resolution is always stated in metres, because the target CRS is always metric.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from rasterio.crs import CRS as RioCRS
from rasterio.enums import Resampling
from rasterio.mask import mask as rio_mask
from rasterio.warp import calculate_default_transform, reproject
from shapely.geometry import mapping
from shapely.geometry.base import BaseGeometry

from app.core.errors import InvalidInputError
from app.geo.crs import require_metric_crs
from app.geo.raster import RasterBounds

# Elevation is stored as float32: 4 bytes per cell is enough for centimetre
# precision over any terrain, and it keeps nodata representable.
ELEVATION_DTYPE = "float32"
DEFAULT_NODATA = -9999.0

GTIFF_PROFILE: dict[str, object] = {
    "driver": "GTiff",
    "compress": "deflate",
    "predictor": 3,
    "tiled": True,
    "blockxsize": 256,
    "blockysize": 256,
    "BIGTIFF": "IF_SAFER",
}


@dataclass(frozen=True, slots=True)
class WarpResult:
    """What a reprojection or clip produced."""

    path: Path
    crs: str
    bounds: RasterBounds
    resolution_m: tuple[float, float]
    width: int
    height: int
    nodata: float
    valid_cell_count: int
    total_cell_count: int

    @property
    def valid_ratio(self) -> float:
        return self.valid_cell_count / self.total_cell_count if self.total_cell_count else 0.0


def _describe_output(path: Path) -> WarpResult:
    with rasterio.open(path) as dataset:
        data = dataset.read(1, masked=True)
        bounds = RasterBounds(
            left=dataset.bounds.left,
            bottom=dataset.bounds.bottom,
            right=dataset.bounds.right,
            top=dataset.bounds.top,
        )
        return WarpResult(
            path=path,
            crs=dataset.crs.to_string(),
            bounds=bounds,
            resolution_m=(float(dataset.res[0]), float(dataset.res[1])),
            width=dataset.width,
            height=dataset.height,
            nodata=float(dataset.nodata) if dataset.nodata is not None else DEFAULT_NODATA,
            valid_cell_count=int(data.count()),
            total_cell_count=int(data.size),
        )


def reproject_raster(
    source_path: Path,
    destination_path: Path,
    target_crs: str,
    *,
    target_resolution_m: float | None = None,
    resampling: Resampling = Resampling.bilinear,
) -> WarpResult:
    """Reproject a raster into a projected metric CRS.

    Args:
        source_path: Input raster. Never modified.
        destination_path: Output GeoTIFF. Parents are created.
        target_crs: Must be projected with metre units.
        target_resolution_m: Output cell size in metres. Defaults to whatever
            GDAL derives from the source grid.
        resampling: Bilinear by default — elevation is a continuous surface, so
            nearest neighbour would create artificial terraces.

    Raises:
        InvalidInputError: if the source has no CRS or the target is not metric.
    """
    require_metric_crs(target_crs)
    destination_path.parent.mkdir(parents=True, exist_ok=True)

    with rasterio.open(source_path) as source:
        if source.crs is None:
            msg = "Cannot reproject a raster without a CRS"
            raise InvalidInputError(msg, details={"path": source_path.name})

        transform, width, height = calculate_default_transform(
            source.crs,
            RioCRS.from_user_input(target_crs),
            source.width,
            source.height,
            *source.bounds,
            resolution=target_resolution_m,
        )

        source_nodata = source.nodata if source.nodata is not None else DEFAULT_NODATA
        profile = {
            **GTIFF_PROFILE,
            "width": width,
            "height": height,
            "count": 1,
            "dtype": ELEVATION_DTYPE,
            "crs": RioCRS.from_user_input(target_crs),
            "transform": transform,
            "nodata": DEFAULT_NODATA,
        }

        with rasterio.open(destination_path, "w", **profile) as destination:
            reproject(
                source=rasterio.band(source, 1),
                destination=rasterio.band(destination, 1),
                src_transform=source.transform,
                src_crs=source.crs,
                src_nodata=source_nodata,
                dst_transform=transform,
                dst_crs=RioCRS.from_user_input(target_crs),
                dst_nodata=DEFAULT_NODATA,
                resampling=resampling,
            )
            destination.update_tags(
                units="m",
                processing="reprojected",
                source_crs=source.crs.to_string(),
                target_crs=target_crs,
                resampling=resampling.name,
            )

    return _describe_output(destination_path)


def resample_to_reference(
    source_path: Path,
    destination_path: Path,
    reference_path: Path,
    *,
    resampling: Resampling = Resampling.bilinear,
) -> WarpResult:
    """Reproject a raster onto another raster's exact grid.

    Unlike :func:`reproject_raster` (which derives its own transform) and
    :func:`clip_raster` (which clips to a geometry), this snaps the source
    directly to the reference's CRS, transform, width and height. Two rasters
    processed independently — even with the same nominal CRS and resolution —
    can disagree by fractions of a pixel; only sharing one's exact grid
    guarantees their cells correspond 1:1 by array index, which is what a
    per-cell weight surface needs to line up with the analysis DEM's cells.

    Raises:
        InvalidInputError: if the source has no CRS.
    """
    destination_path.parent.mkdir(parents=True, exist_ok=True)

    with rasterio.open(reference_path) as reference:
        dst_crs = reference.crs
        dst_transform = reference.transform
        dst_width = reference.width
        dst_height = reference.height

    with rasterio.open(source_path) as source:
        if source.crs is None:
            msg = "Cannot align a raster without a CRS"
            raise InvalidInputError(msg, details={"path": source_path.name})
        source_nodata = source.nodata if source.nodata is not None else DEFAULT_NODATA

        profile = {
            **GTIFF_PROFILE,
            "width": dst_width,
            "height": dst_height,
            "count": 1,
            "dtype": ELEVATION_DTYPE,
            "crs": dst_crs,
            "transform": dst_transform,
            "nodata": DEFAULT_NODATA,
        }

        with rasterio.open(destination_path, "w", **profile) as destination:
            reproject(
                source=rasterio.band(source, 1),
                destination=rasterio.band(destination, 1),
                src_transform=source.transform,
                src_crs=source.crs,
                src_nodata=source_nodata,
                dst_transform=dst_transform,
                dst_crs=dst_crs,
                dst_nodata=DEFAULT_NODATA,
                resampling=resampling,
            )
            destination.update_tags(
                units="m",
                processing="aligned_to_reference",
                source_crs=source.crs.to_string(),
                target_crs=dst_crs.to_string(),
                resampling=resampling.name,
            )

    return _describe_output(destination_path)


def clip_raster(
    source_path: Path,
    destination_path: Path,
    geometry: BaseGeometry,
    *,
    geometry_crs: str,
) -> WarpResult:
    """Clip a raster to a geometry expressed in the raster's own CRS.

    Args:
        geometry: Clip shape, already buffered by the caller.
        geometry_crs: CRS of ``geometry``; must match the raster's CRS, so that
            no silent reprojection happens inside a clip.

    Raises:
        InvalidInputError: on a CRS mismatch or an empty intersection.
    """
    destination_path.parent.mkdir(parents=True, exist_ok=True)

    with rasterio.open(source_path) as source:
        if source.crs is None:
            msg = "Cannot clip a raster without a CRS"
            raise InvalidInputError(msg, details={"path": source_path.name})
        if RioCRS.from_user_input(geometry_crs) != source.crs:
            msg = "Clip geometry CRS does not match the raster CRS"
            raise InvalidInputError(
                msg,
                details={"geometry_crs": geometry_crs, "raster_crs": source.crs.to_string()},
            )

        try:
            data, transform = rio_mask(
                source,
                [mapping(geometry)],
                crop=True,
                filled=True,
                nodata=DEFAULT_NODATA,
                all_touched=True,
            )
        except ValueError as error:
            msg = "Clip geometry does not overlap the raster"
            raise InvalidInputError(
                msg, details={"path": source_path.name, "reason": str(error)}
            ) from error

        profile = {
            **GTIFF_PROFILE,
            "height": data.shape[1],
            "width": data.shape[2],
            "count": 1,
            "dtype": ELEVATION_DTYPE,
            "crs": source.crs,
            "transform": transform,
            "nodata": DEFAULT_NODATA,
        }
        tags = source.tags()

    with rasterio.open(destination_path, "w", **profile) as destination:
        destination.write(data[0].astype(np.float32), 1)
        # Source tags are carried over, then overridden by this step's own.
        destination.update_tags(**{**tags, "processing": "clipped", "units": "m"})

    return _describe_output(destination_path)
