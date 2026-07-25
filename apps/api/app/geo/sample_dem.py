"""Synthetic sample terrain.

This module produces a *synthetic* DEM used by tests and by the local demo. It
is explicitly not production data and must never be presented as a real survey
of any territory: the header carries ``source = "synthetic"`` and the generating
parameters so it can always be told apart from an ingested dataset.

The raster is written in a projected CRS with metre units, because every
downstream calculation (distance, slope, viewshed) is metric. Writing a sample
in EPSG:4326 would bake a degree-based grid into the fixtures.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import numpy as np
import rasterio
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field
from rasterio.crs import CRS
from rasterio.transform import from_origin

from app.core.checksum import sha256_file
from app.core.errors import InvalidInputError

# ETRS89 / UTM zone 30N: the metric CRS covering most of mainland Spain.
DEFAULT_SAMPLE_CRS = "EPSG:25830"
NODATA_VALUE = -9999.0


class SyntheticDemSpec(BaseModel):
    """Parameters that fully determine a synthetic DEM.

    Storing the spec next to the raster keeps the fixture reproducible: same
    spec, same bytes.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    width: Annotated[int, Field(ge=8, le=8192, description="Columns.")] = 400
    height: Annotated[int, Field(ge=8, le=8192, description="Rows.")] = 400
    resolution_m: Annotated[float, Field(gt=0, le=1000, description="Cell size in metres.")] = 25.0
    origin_x_m: Annotated[float, Field(description="Easting of the upper-left corner, metres.")] = (
        400_000.0
    )
    origin_y_m: Annotated[
        float, Field(description="Northing of the upper-left corner, metres.")
    ] = 4_600_000.0
    crs: str = Field(default=DEFAULT_SAMPLE_CRS, description="Projected, metre based CRS.")
    base_elevation_m: float = 400.0
    relief_m: Annotated[float, Field(ge=0)] = 700.0
    roughness_m: Annotated[float, Field(ge=0)] = 12.0
    seed: int = Field(default=20240101, description="Seed for the deterministic noise field.")


@dataclass(frozen=True, slots=True)
class SyntheticDemResult:
    """Where the fixture landed and how to identify it."""

    path: Path
    crs: str
    bounds: tuple[float, float, float, float]
    resolution_m: tuple[float, float]
    nodata: float
    units: str
    checksum_sha256: str
    min_elevation_m: float
    max_elevation_m: float


def _require_metric_crs(crs_text: str) -> CRS:
    """Reject any CRS whose distances are not metres.

    Units are never assumed: a geographic CRS here would silently turn cell
    sizes into degrees.
    """
    crs = CRS.from_user_input(crs_text)
    if crs.is_geographic:
        msg = "Sample DEM requires a projected CRS; a geographic CRS has degree units"
        raise InvalidInputError(msg, details={"crs": crs_text})
    unit = (crs.linear_units or "").lower()
    if unit not in {"metre", "meter", "m"}:
        msg = f"Sample DEM requires metre units, CRS reports {unit!r}"
        raise InvalidInputError(msg, details={"crs": crs_text, "linear_units": unit})
    return crs


def _elevation_field(spec: SyntheticDemSpec) -> NDArray[np.float32]:
    """Deterministic terrain: two ridges, three peaks and bounded noise."""
    rng = np.random.default_rng(spec.seed)

    rows = np.arange(spec.height, dtype=np.float64)
    cols = np.arange(spec.width, dtype=np.float64)
    yy, xx = np.meshgrid(rows / spec.height, cols / spec.width, indexing="ij")

    # Vectorised: no Python loops over cells.
    ridges = 0.45 * np.sin(3.0 * np.pi * xx) * np.cos(2.0 * np.pi * yy)
    peaks = np.zeros_like(xx)
    for cx, cy, amplitude, spread in (
        (0.25, 0.30, 1.00, 0.10),
        (0.70, 0.55, 0.85, 0.07),
        (0.45, 0.80, 0.60, 0.05),
    ):
        peaks += amplitude * np.exp(-(((xx - cx) ** 2 + (yy - cy) ** 2) / (2.0 * spread)))

    noise = rng.normal(loc=0.0, scale=1.0, size=(spec.height, spec.width))
    surface = (
        spec.base_elevation_m + spec.relief_m * (0.5 * ridges + peaks) + spec.roughness_m * noise
    )
    return surface.astype(np.float32)


def write_synthetic_dem(path: Path, spec: SyntheticDemSpec | None = None) -> SyntheticDemResult:
    """Write a synthetic DEM GeoTIFF and return its geospatial description.

    Args:
        path: Destination GeoTIFF. Parent directories are created.
        spec: Generation parameters; defaults to a 10 x 10 km area at 25 m.

    Raises:
        InvalidInputError: if the requested CRS is not projected in metres.
    """
    resolved_spec = spec or SyntheticDemSpec()
    crs = _require_metric_crs(resolved_spec.crs)

    elevation = _elevation_field(resolved_spec)
    transform = from_origin(
        resolved_spec.origin_x_m,
        resolved_spec.origin_y_m,
        resolved_spec.resolution_m,
        resolved_spec.resolution_m,
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=resolved_spec.width,
        height=resolved_spec.height,
        count=1,
        dtype="float32",
        crs=crs,
        transform=transform,
        nodata=NODATA_VALUE,
        compress="deflate",
        tiled=True,
    ) as dataset:
        dataset.write(elevation, 1)
        dataset.update_tags(
            source="synthetic",
            generator="app.geo.sample_dem",
            units="m",
            vertical_datum="synthetic",
            spec=resolved_spec.model_dump_json(),
        )
        bounds = dataset.bounds
        resolution = dataset.res

    return SyntheticDemResult(
        path=path,
        crs=crs.to_string(),
        bounds=(bounds.left, bounds.bottom, bounds.right, bounds.top),
        resolution_m=(float(resolution[0]), float(resolution[1])),
        nodata=NODATA_VALUE,
        units="m",
        checksum_sha256=sha256_file(path),
        min_elevation_m=float(elevation.min()),
        max_elevation_m=float(elevation.max()),
    )
