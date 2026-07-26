"""Configuration dataclasses shared across the pipeline.

Dependency-free (stdlib + dataclasses only) so every other module can import
this without risking an import cycle.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass(frozen=True)
class SensorSpec:
    """Physical/optical model of a single Karajan Sentinel mast.

    Defaults come from the Sentinel product spec: a 15-20 m galvanized mast
    with two AXIS Q6358-LE PTZ cameras that continuously rotate through a
    full 360 degrees, so coverage is modelled as omnidirectional rather than
    a fixed field-of-view cone.

    This models GEOMETRIC line-of-sight coverage only -- not a smoke-detection
    probability model. Actual detection also depends on plume size, atmospheric
    visibility, and camera zoom, none of which are represented here.

    target_height_m defaults to 25m (above bare ground) rather than 0m: the
    Sentinel detects rising smoke, not the ignition point itself, and smoke is
    only visible once it clears the surrounding tree line. In densely forested
    terrain, target_height_m=0 models seeing bare ground *through* the canopy
    -- physically wrong for what the camera actually detects, and it makes
    coverage collapse almost everywhere there are trees. Set it to 0 only to
    study strict ground-level visibility (e.g. open terrain, or a
    non-wildfire use case).
    """

    mast_height_m: float = 18.0
    target_height_m: float = 25.0
    max_range_m: float = 15_000.0
    refraction_k: float = 0.13
    earth_radius_m: float = 6_371_000.0

    def curvature_drop_m(self, distance_m: float) -> float:
        """Apparent drop of the horizon due to earth curvature minus standard
        atmospheric refraction, at the given distance."""
        return (1.0 - self.refraction_k) * distance_m**2 / (2.0 * self.earth_radius_m)


@dataclass(frozen=True)
class StudyArea:
    """Area of interest, either as an explicit WGS84 bbox or a center+radius."""

    bbox: tuple[float, float, float, float] | None = None  # (lon_min, lat_min, lon_max, lat_max)
    center_lon: float | None = None
    center_lat: float | None = None
    radius_km: float | None = None

    def resolve_bbox_wgs84(self) -> tuple[float, float, float, float]:
        if self.bbox is not None:
            return self.bbox
        if self.center_lon is None or self.center_lat is None or self.radius_km is None:
            raise ValueError("StudyArea needs either bbox or center_lon/center_lat/radius_km")
        # Local degrees-per-meter approximation, fine for buffering a center point.
        dlat = (self.radius_km * 1000.0) / 111_320.0
        dlon = (self.radius_km * 1000.0) / (111_320.0 * math.cos(math.radians(self.center_lat)))
        return (
            self.center_lon - dlon,
            self.center_lat - dlat,
            self.center_lon + dlon,
            self.center_lat + dlat,
        )

    def center(self) -> tuple[float, float]:
        """Returns (lon, lat) of the area's center."""
        if self.center_lon is not None and self.center_lat is not None:
            return self.center_lon, self.center_lat
        lon_min, lat_min, lon_max, lat_max = self.resolve_bbox_wgs84()
        return (lon_min + lon_max) / 2.0, (lat_min + lat_max) / 2.0


@dataclass(frozen=True)
class GridSpec:
    """Sampling resolution knobs for the pipeline."""

    eval_resolution_m: float = 30.0
    candidate_spacing_m: float = 400.0
    n_rays: int | None = None  # None -> resolved_n_rays(max_range_m)
    ray_step_m: float | None = None  # None -> eval_resolution_m / 2

    def resolved_ray_step_m(self) -> float:
        return self.ray_step_m if self.ray_step_m is not None else self.eval_resolution_m / 2.0

    def resolved_n_rays(self, max_range_m: float) -> int:
        """Default ray count keeps the arc-length between adjacent rays at
        max range no coarser than one eval cell. Too few rays relative to
        range/resolution doesn't leave visible gaps (every eval cell is
        still queried directly, see viewshed.py) but it does make sharp,
        high-frequency obstructions -- e.g. forest-canopy edges -- get
        inconsistently assigned between neighboring cells that round to
        different ray buckets, showing up as speckle in the coverage map.
        """
        if self.n_rays is not None:
            return self.n_rays
        import math

        return max(360, math.ceil(2.0 * math.pi * max_range_m / self.eval_resolution_m))


@dataclass(frozen=True)
class StudyConfig:
    area: StudyArea
    sensor: SensorSpec = field(default_factory=SensorSpec)
    grid: GridSpec = field(default_factory=GridSpec)
    terrarium_zoom: int = 12
    cache_dir: str = "~/.cache/sentinel_coverage"
    max_sentinels: int | None = None
    target_coverage: float | None = None
    min_marginal_gain_frac: float | None = 0.005

    def __post_init__(self) -> None:
        if self.max_sentinels is None and self.target_coverage is None:
            raise ValueError("StudyConfig needs at least one of max_sentinels or target_coverage")


# Montseny Natural Park, Catalonia -- real mountainous, forested, wildfire-prone
# terrain used as the default demo area. Any other location works via CLI flags.
DEMO_STUDY_AREA = StudyArea(bbox=(2.35, 41.75, 2.50, 41.85))
