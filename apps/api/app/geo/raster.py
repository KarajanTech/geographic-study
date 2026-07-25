"""Raster metadata reading.

Every dataset that enters the system is described by the same record: CRS,
bounds, resolution, nodata, units, checksum, source and processing history.
Nothing downstream is allowed to guess these values.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import rasterio
from pydantic import BaseModel, ConfigDict, Field
from pyproj import CRS, Transformer
from rasterio.errors import RasterioIOError

from app.core.checksum import sha256_file
from app.core.errors import InvalidInputError
from app.geo.crs import WGS84, is_metric_crs


class RasterBounds(BaseModel):
    """Axis-aligned extent, in the units of the raster's own CRS."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    left: float
    bottom: float
    right: float
    top: float

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.left, self.bottom, self.right, self.top)

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.top - self.bottom


class RasterMetadata(BaseModel):
    """Full geospatial description of a raster file."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = Field(description="Absolute path on the storage volume.")
    driver: str
    width: int
    height: int
    band_count: int
    dtype: str
    crs: str | None = Field(description="CRS as an authority string, None when absent.")
    is_projected: bool
    is_metric: bool = Field(description="True when the CRS measures metres.")
    units: str = Field(description="Horizontal unit of the CRS: 'm', 'degree', 'unknown'.")
    resolution_x: float
    resolution_y: float
    bounds: RasterBounds = Field(description="Extent in the raster's own CRS.")
    bounds_wgs84: RasterBounds | None = Field(
        default=None, description="Extent in EPSG:4326, for map display."
    )
    nodata: float | None
    checksum_sha256: str
    size_bytes: int
    tags: dict[str, str] = Field(default_factory=dict)


def _horizontal_unit(crs: CRS | None) -> str:
    if crs is None:
        return "unknown"
    if crs.is_geographic:
        return "degree"
    units = {axis.unit_name.lower() for axis in crs.axis_info}
    if units <= {"metre", "meter", "m"}:
        return "m"
    return "/".join(sorted(units)) if units else "unknown"


def _bounds_to_wgs84(bounds: RasterBounds, crs: CRS) -> RasterBounds | None:
    """Reproject an extent to EPSG:4326 for display purposes only.

    A transformed axis-aligned box is an approximation of the real footprint;
    it is never used for calculation, only to place the dataset on a map.
    """
    if crs.to_epsg() == 4326:
        return bounds
    try:
        transformer = Transformer.from_crs(crs, CRS.from_user_input(WGS84), always_xy=True)
        xs, ys = transformer.transform(
            [bounds.left, bounds.right, bounds.left, bounds.right],
            [bounds.bottom, bounds.top, bounds.top, bounds.bottom],
        )
    except Exception:  # noqa: BLE001 - display extent is best effort
        return None
    if not all(math.isfinite(value) for value in (*xs, *ys)):
        return None
    return RasterBounds(left=min(xs), bottom=min(ys), right=max(xs), top=max(ys))


def describe_raster(path: Path) -> RasterMetadata:
    """Read a raster's full geospatial description.

    Raises:
        InvalidInputError: when the file cannot be opened as a raster.
    """
    try:
        with rasterio.open(path) as dataset:
            crs: CRS | None = CRS.from_user_input(dataset.crs) if dataset.crs else None
            bounds = RasterBounds(
                left=dataset.bounds.left,
                bottom=dataset.bounds.bottom,
                right=dataset.bounds.right,
                top=dataset.bounds.top,
            )
            metadata = RasterMetadata(
                path=str(path),
                driver=dataset.driver,
                width=dataset.width,
                height=dataset.height,
                band_count=dataset.count,
                dtype=dataset.dtypes[0],
                crs=crs.to_string() if crs is not None else None,
                is_projected=bool(crs is not None and crs.is_projected),
                is_metric=bool(crs is not None and is_metric_crs(crs)),
                units=_horizontal_unit(crs),
                resolution_x=float(dataset.res[0]),
                resolution_y=float(dataset.res[1]),
                bounds=bounds,
                bounds_wgs84=_bounds_to_wgs84(bounds, crs) if crs is not None else None,
                nodata=None if dataset.nodata is None else float(dataset.nodata),
                checksum_sha256=sha256_file(path),
                size_bytes=path.stat().st_size,
                tags={str(k): str(v) for k, v in dataset.tags().items()},
            )
    except RasterioIOError as error:
        msg = "File could not be opened as a raster"
        raise InvalidInputError(msg, details={"path": path.name, "reason": str(error)}) from error
    return metadata


def metadata_to_storage_dict(metadata: RasterMetadata) -> dict[str, Any]:
    """Flatten metadata for the ``Dataset.metadata_json`` column."""
    return {
        "driver": metadata.driver,
        "width": metadata.width,
        "height": metadata.height,
        "band_count": metadata.band_count,
        "dtype": metadata.dtype,
        "is_projected": metadata.is_projected,
        "is_metric": metadata.is_metric,
        "size_bytes": metadata.size_bytes,
        "tags": metadata.tags,
        "bounds_wgs84": (
            metadata.bounds_wgs84.model_dump() if metadata.bounds_wgs84 is not None else None
        ),
    }
