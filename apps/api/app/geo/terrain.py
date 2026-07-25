"""Terrain derivatives.

Hillshade is a visualisation product and never feeds a coverage calculation.
Slope and local prominence do: they decide which grid points can hold a tower
and how good a site looks before any visibility is computed.

Every function here takes the cell size in metres explicitly. A gradient is a
rise over a run, and the run is only a distance if the grid is metric.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from numpy.typing import NDArray
from scipy.ndimage import uniform_filter

from app.core.errors import InvalidInputError
from app.geo.crs import require_metric_crs
from app.geo.warp import GTIFF_PROFILE

HILLSHADE_NODATA = 0
DEFAULT_AZIMUTH_DEG = 315.0
DEFAULT_ALTITUDE_DEG = 45.0


@dataclass(frozen=True, slots=True)
class HillshadeResult:
    path: Path
    azimuth_deg: float
    altitude_deg: float
    z_factor: float


def _horn_gradient(
    surface: NDArray[np.float64], resolution_x_m: float, resolution_y_m: float
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Horn's 3x3 weighted gradient, in metres of rise per metre of run.

    Edge cells have no full neighbourhood; replicating the border keeps the
    output the same shape as the input without inventing terrain.
    """
    padded = np.pad(surface, 1, mode="edge")
    dz_dx = (
        (padded[:-2, 2:] + 2 * padded[1:-1, 2:] + padded[2:, 2:])
        - (padded[:-2, :-2] + 2 * padded[1:-1, :-2] + padded[2:, :-2])
    ) / (8.0 * resolution_x_m)
    dz_dy = (
        (padded[2:, :-2] + 2 * padded[2:, 1:-1] + padded[2:, 2:])
        - (padded[:-2, :-2] + 2 * padded[:-2, 1:-1] + padded[:-2, 2:])
    ) / (8.0 * resolution_y_m)
    return dz_dx, dz_dy


def _require_metric_cells(resolution_x_m: float, resolution_y_m: float) -> None:
    if resolution_x_m <= 0 or resolution_y_m <= 0:
        msg = "Terrain derivatives need a positive cell size in metres"
        raise InvalidInputError(
            msg, details={"resolution_x_m": resolution_x_m, "resolution_y_m": resolution_y_m}
        )


def compute_slope_degrees(
    elevation: NDArray[np.float32] | NDArray[np.float64],
    *,
    resolution_x_m: float,
    resolution_y_m: float,
) -> NDArray[np.float32]:
    """Slope of the surface in degrees, 0 (flat) to 90 (vertical).

    Elevation and cell size are both in metres, so the ratio is dimensionless
    and the arctangent is a real angle.
    """
    _require_metric_cells(resolution_x_m, resolution_y_m)
    surface = np.asarray(elevation, dtype=np.float64)
    dz_dx, dz_dy = _horn_gradient(surface, resolution_x_m, resolution_y_m)
    slope: NDArray[np.float32] = np.degrees(np.arctan(np.hypot(dz_dx, dz_dy))).astype(np.float32)
    return slope


def compute_local_prominence(
    elevation: NDArray[np.float32] | NDArray[np.float64],
    *,
    resolution_x_m: float,
    resolution_y_m: float,
    radius_m: float,
) -> NDArray[np.float32]:
    """How far a cell stands above the mean of its neighbourhood, in metres.

    A cheap stand-in for topographic prominence: positive on ridges and
    summits, negative in valleys. It ranks sites before any viewshed is
    computed, so a hilltop is preferred to the valley floor next to it.

    The radius is in metres and converted to cells here, which is the only
    place the two units meet.
    """
    _require_metric_cells(resolution_x_m, resolution_y_m)
    if radius_m <= 0:
        msg = "Prominence radius must be positive, in metres"
        raise InvalidInputError(msg, details={"radius_m": radius_m})

    surface = np.asarray(elevation, dtype=np.float64)
    size_y = max(1, round(2.0 * radius_m / resolution_y_m) | 1)
    size_x = max(1, round(2.0 * radius_m / resolution_x_m) | 1)
    # 'nearest' extends the edge value rather than treating outside as zero,
    # which would make every border cell look like a summit.
    local_mean = uniform_filter(surface, size=(size_y, size_x), mode="nearest")
    prominence: NDArray[np.float32] = (surface - local_mean).astype(np.float32)
    return prominence


def compute_hillshade(
    elevation: NDArray[np.float32],
    *,
    resolution_x_m: float,
    resolution_y_m: float,
    azimuth_deg: float = DEFAULT_AZIMUTH_DEG,
    altitude_deg: float = DEFAULT_ALTITUDE_DEG,
    z_factor: float = 1.0,
) -> NDArray[np.uint8]:
    """Horn hillshade over a metric grid, returned as 1-255 (0 means nodata).

    Elevation and cell size share the same unit (metres), so ``z_factor`` stays
    1.0. It is exposed only for exaggerated visualisations, never for analysis.
    """
    _require_metric_cells(resolution_x_m, resolution_y_m)

    surface = np.asarray(elevation, dtype=np.float64)
    dz_dx, dz_dy = _horn_gradient(surface, resolution_x_m, resolution_y_m)

    dz_dx *= z_factor
    dz_dy *= z_factor

    slope = np.arctan(np.hypot(dz_dx, dz_dy))
    aspect = np.arctan2(dz_dy, -dz_dx)

    zenith = math.radians(90.0 - altitude_deg)
    # Azimuth is clockwise from north; trigonometry is counter-clockwise from east.
    azimuth = math.radians(360.0 - azimuth_deg + 90.0)

    shaded = np.cos(zenith) * np.cos(slope) + np.sin(zenith) * np.sin(slope) * np.cos(
        azimuth - aspect
    )
    scaled = np.clip(shaded, 0.0, 1.0) * 254.0 + 1.0
    result: NDArray[np.uint8] = scaled.astype(np.uint8)
    return result


def write_hillshade(
    source_path: Path,
    destination_path: Path,
    *,
    azimuth_deg: float = DEFAULT_AZIMUTH_DEG,
    altitude_deg: float = DEFAULT_ALTITUDE_DEG,
    z_factor: float = 1.0,
) -> HillshadeResult:
    """Write a hillshade GeoTIFF from a metric elevation raster."""
    destination_path.parent.mkdir(parents=True, exist_ok=True)

    with rasterio.open(source_path) as source:
        if source.crs is None:
            msg = "Hillshade needs a georeferenced raster"
            raise InvalidInputError(msg, details={"path": source_path.name})
        require_metric_crs(source.crs.to_string())

        elevation = source.read(1, masked=True)
        filled = elevation.filled(np.nan).astype(np.float32)
        # Interpolating across nodata would invent terrain; treat gaps as flat
        # at the mean so the shading stays neutral there, then mask them out.
        valid = ~np.isnan(filled)
        if not valid.any():
            msg = "Raster contains no valid elevation values"
            raise InvalidInputError(msg, details={"path": source_path.name})
        filled = np.where(valid, filled, float(np.nanmean(filled)))

        shade = compute_hillshade(
            filled,
            resolution_x_m=float(source.res[0]),
            resolution_y_m=float(source.res[1]),
            azimuth_deg=azimuth_deg,
            altitude_deg=altitude_deg,
            z_factor=z_factor,
        )
        shade = np.where(valid, shade, HILLSHADE_NODATA).astype(np.uint8)

        profile = {
            **GTIFF_PROFILE,
            "width": source.width,
            "height": source.height,
            "count": 1,
            "dtype": "uint8",
            "crs": source.crs,
            "transform": source.transform,
            "nodata": HILLSHADE_NODATA,
            # Predictor 3 is for floating point; hillshade is integer.
            "predictor": 2,
        }

    with rasterio.open(destination_path, "w", **profile) as destination:
        destination.write(shade, 1)
        destination.update_tags(
            processing="hillshade",
            units="none",
            azimuth_deg=str(azimuth_deg),
            altitude_deg=str(altitude_deg),
            z_factor=str(z_factor),
        )

    return HillshadeResult(
        path=destination_path,
        azimuth_deg=azimuth_deg,
        altitude_deg=altitude_deg,
        z_factor=z_factor,
    )
