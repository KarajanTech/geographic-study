"""Study area geometry.

A study area arrives as GeoJSON in EPSG:4326, which is the only place in the
system where degrees are acceptable: it is a location, not a measurement. Any
metric property of the area (its surface, its buffer) is computed after
projecting it to the analysis CRS.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pyproj import CRS, Transformer
from shapely.geometry import MultiPolygon, Polygon, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shapely_transform

from app.core.errors import InvalidInputError
from app.geo.crs import WGS84, require_metric_crs, select_analysis_crs

# A study area larger than this is almost certainly a mistake (a whole country
# pasted in, or coordinates in the wrong order). Refuse it rather than spend an
# hour building candidates for it.
MAX_AREA_KM2 = 50_000.0
MIN_AREA_KM2 = 0.01

ALLOWED_GEOMETRY_TYPES = frozenset({"Polygon", "MultiPolygon"})


@dataclass(frozen=True, slots=True)
class StudyArea:
    """A validated study area, in EPSG:4326, with its metric properties."""

    geometry: MultiPolygon
    analysis_crs: str
    centroid_lon: float
    centroid_lat: float
    area_km2: float
    perimeter_km: float

    def to_geojson(self) -> dict[str, Any]:
        return _mapping(self.geometry)

    def projected(self) -> BaseGeometry:
        """The area reprojected into its analysis CRS, in metres."""
        return reproject_geometry(self.geometry, WGS84, self.analysis_crs)

    def buffered_projected(self, buffer_m: float) -> BaseGeometry:
        """The projected area grown by ``buffer_m`` metres.

        Used to clip rasters: a Sentinel can see terrain outside the study area,
        so the surface model must extend beyond it by the maximum sight range.
        """
        if buffer_m < 0:
            msg = "Buffer distance must be zero or positive"
            raise InvalidInputError(msg, details={"buffer_m": buffer_m})
        return self.projected().buffer(buffer_m)


def _mapping(geometry: BaseGeometry) -> dict[str, Any]:
    from shapely.geometry import mapping

    return dict(mapping(geometry))


def reproject_geometry(geometry: BaseGeometry, source_crs: str, target_crs: str) -> BaseGeometry:
    """Reproject a shapely geometry between two CRS, preserving CRS awareness.

    The transformer is built with ``always_xy=True`` so coordinates are read as
    (x, y) = (longitude, latitude), never in authority axis order.
    """
    source = CRS.from_user_input(source_crs)
    target = CRS.from_user_input(target_crs)
    if source == target:
        return geometry
    transformer = Transformer.from_crs(source, target, always_xy=True)
    return shapely_transform(transformer.transform, geometry)


def _as_multipolygon(geometry: BaseGeometry) -> MultiPolygon:
    if isinstance(geometry, MultiPolygon):
        return geometry
    if isinstance(geometry, Polygon):
        return MultiPolygon([geometry])
    msg = f"Study area must be a Polygon or MultiPolygon, got {geometry.geom_type}"
    raise InvalidInputError(msg, details={"geometry_type": geometry.geom_type})


def parse_study_area(geojson: dict[str, Any], analysis_crs: str | None = None) -> StudyArea:
    """Validate a GeoJSON study area and derive its metric properties.

    Args:
        geojson: A GeoJSON Polygon, MultiPolygon, Feature or FeatureCollection
            in EPSG:4326.
        analysis_crs: Pin the analysis CRS instead of deriving it from the
            centroid. Must be projected and metre based.

    Raises:
        InvalidInputError: for malformed, empty, invalid or implausible areas.
    """
    geometry = _geometry_from_geojson(geojson)

    if geometry.is_empty:
        msg = "Study area geometry is empty"
        raise InvalidInputError(msg)
    if not geometry.is_valid:
        # Self-intersections make area and buffer meaningless; a zero-width
        # buffer is the standard repair, but the caller should know it happened.
        msg = "Study area geometry is invalid (self-intersecting or malformed)"
        raise InvalidInputError(msg, details={"hint": "repair the polygon before uploading"})

    multipolygon = _as_multipolygon(geometry)
    _check_wgs84_range(multipolygon)

    centroid = multipolygon.centroid
    crs = analysis_crs or select_analysis_crs(centroid.x, centroid.y).crs
    require_metric_crs(crs)

    projected = reproject_geometry(multipolygon, WGS84, crs)
    area_km2 = projected.area / 1_000_000.0
    perimeter_km = projected.length / 1_000.0

    if area_km2 < MIN_AREA_KM2:
        msg = f"Study area is too small: {area_km2:.4f} km² (minimum {MIN_AREA_KM2} km²)"
        raise InvalidInputError(msg, details={"area_km2": area_km2})
    if area_km2 > MAX_AREA_KM2:
        msg = f"Study area is too large: {area_km2:.0f} km² (maximum {MAX_AREA_KM2:.0f} km²)"
        raise InvalidInputError(msg, details={"area_km2": area_km2})

    return StudyArea(
        geometry=multipolygon,
        analysis_crs=crs,
        centroid_lon=float(centroid.x),
        centroid_lat=float(centroid.y),
        area_km2=area_km2,
        perimeter_km=perimeter_km,
    )


def _geometry_from_geojson(geojson: dict[str, Any]) -> BaseGeometry:
    """Accept a bare geometry, a Feature, or a FeatureCollection."""
    payload = geojson
    kind = payload.get("type")

    if kind == "FeatureCollection":
        features = payload.get("features") or []
        if not features:
            msg = "FeatureCollection contains no features"
            raise InvalidInputError(msg)
        if len(features) > 1:
            msg = "Study area must be a single feature"
            raise InvalidInputError(msg, details={"feature_count": len(features)})
        payload = features[0]
        kind = payload.get("type")

    if kind == "Feature":
        payload = payload.get("geometry") or {}
        kind = payload.get("type")

    if kind not in ALLOWED_GEOMETRY_TYPES:
        msg = f"Study area must be a Polygon or MultiPolygon, got {kind!r}"
        raise InvalidInputError(msg, details={"geometry_type": kind})

    try:
        return shape(payload)
    except Exception as error:
        msg = "Study area is not valid GeoJSON geometry"
        raise InvalidInputError(msg, details={"reason": str(error)}) from error


def _check_wgs84_range(geometry: MultiPolygon) -> None:
    """Coordinates outside the WGS84 range mean the input is not in EPSG:4326."""
    minx, miny, maxx, maxy = geometry.bounds
    if not (-180.0 <= minx <= 180.0 and -180.0 <= maxx <= 180.0):
        msg = "Longitudes outside [-180, 180]; the study area must be in EPSG:4326"
        raise InvalidInputError(msg, details={"bounds": [minx, miny, maxx, maxy]})
    if not (-90.0 <= miny <= 90.0 and -90.0 <= maxy <= 90.0):
        msg = "Latitudes outside [-90, 90]; the study area must be in EPSG:4326"
        raise InvalidInputError(msg, details={"bounds": [minx, miny, maxx, maxy]})
