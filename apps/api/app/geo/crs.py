"""Analysis CRS selection.

Every metric calculation in Sentinel Planner runs in a projected CRS whose unit
is the metre. This module picks that CRS deterministically from the study area
and refuses anything that would make distances meaningless.
"""

from __future__ import annotations

from dataclasses import dataclass

from pyproj import CRS
from pyproj.aoi import AreaOfInterest
from pyproj.database import query_utm_crs_info

from app.core.errors import InvalidInputError

WGS84 = "EPSG:4326"

# ETRS89 is the official datum for continental Europe and is what Spanish
# cartography (CNIG) publishes; its UTM codes are 25800 + zone.
ETRS89_UTM_BASE = 25800
ETRS89_ZONE_RANGE = range(28, 39)
# Rough area of use of ETRS89. Outside it, fall back to WGS84 UTM.
ETRS89_BOUNDS_LON = (-16.1, 40.18)
ETRS89_BOUNDS_LAT = (32.88, 84.73)

WGS84_UTM_NORTH_BASE = 32600
WGS84_UTM_SOUTH_BASE = 32700

METRE_UNITS = frozenset({"metre", "meter", "m"})


@dataclass(frozen=True, slots=True)
class CrsSelection:
    """A chosen analysis CRS and why it was chosen."""

    crs: str
    utm_zone: int
    hemisphere: str
    datum: str
    reason: str


def utm_zone_for_longitude(longitude: float) -> int:
    """Return the UTM zone (1-60) containing ``longitude`` in degrees."""
    if not -180.0 <= longitude <= 180.0:
        msg = f"Longitude {longitude} is outside [-180, 180]"
        raise InvalidInputError(msg, details={"longitude": longitude})
    # Longitude 180 belongs to zone 60, not to a non-existent zone 61.
    return min(int((longitude + 180.0) / 6.0) + 1, 60)


def select_analysis_crs(centroid_lon: float, centroid_lat: float) -> CrsSelection:
    """Choose the projected metric CRS for a study area centred on this point.

    ETRS89 / UTM inside its area of use, WGS84 / UTM everywhere else. The rule
    is deterministic: the same centroid always yields the same CRS, which is
    what makes an analysis reproducible.
    """
    if not -90.0 <= centroid_lat <= 90.0:
        msg = f"Latitude {centroid_lat} is outside [-90, 90]"
        raise InvalidInputError(msg, details={"latitude": centroid_lat})

    zone = utm_zone_for_longitude(centroid_lon)
    northern = centroid_lat >= 0.0

    in_etrs89_area = (
        ETRS89_BOUNDS_LON[0] <= centroid_lon <= ETRS89_BOUNDS_LON[1]
        and ETRS89_BOUNDS_LAT[0] <= centroid_lat <= ETRS89_BOUNDS_LAT[1]
        and zone in ETRS89_ZONE_RANGE
    )

    if in_etrs89_area:
        return CrsSelection(
            crs=f"EPSG:{ETRS89_UTM_BASE + zone}",
            utm_zone=zone,
            hemisphere="N",
            datum="ETRS89",
            reason="centroid inside the ETRS89 area of use",
        )

    base = WGS84_UTM_NORTH_BASE if northern else WGS84_UTM_SOUTH_BASE
    return CrsSelection(
        crs=f"EPSG:{base + zone}",
        utm_zone=zone,
        hemisphere="N" if northern else "S",
        datum="WGS 84",
        reason="centroid outside the ETRS89 area of use",
    )


def suggest_utm_crs(centroid_lon: float, centroid_lat: float) -> str:
    """Ask PROJ for the best UTM CRS at this point.

    Used as a cross-check of :func:`select_analysis_crs` in tests; the hand
    written rule is what production uses, because it never depends on the PROJ
    database version.
    """
    candidates = query_utm_crs_info(
        datum_name="WGS 84",
        area_of_interest=AreaOfInterest(
            west_lon_degree=centroid_lon,
            south_lat_degree=centroid_lat,
            east_lon_degree=centroid_lon,
            north_lat_degree=centroid_lat,
        ),
    )
    if not candidates:  # pragma: no cover - PROJ always has UTM coverage
        msg = "PROJ returned no UTM candidate for this location"
        raise InvalidInputError(msg, details={"lon": centroid_lon, "lat": centroid_lat})
    return f"{candidates[0].auth_name}:{candidates[0].code}"


def require_metric_crs(crs_input: str | CRS) -> CRS:
    """Return the CRS, or raise if it is not projected with metre units.

    Distances, buffers, slopes, areas and viewsheds may only be computed in a
    CRS that passes this check. Units are never assumed.
    """
    crs = crs_input if isinstance(crs_input, CRS) else CRS.from_user_input(crs_input)
    if crs.is_geographic:
        msg = "A projected CRS is required; this one is geographic and measures degrees"
        raise InvalidInputError(msg, details={"crs": crs.to_string()})

    axis_units = {axis.unit_name.lower() for axis in crs.axis_info}
    if not axis_units <= METRE_UNITS:
        msg = f"A metre based CRS is required; this one uses {sorted(axis_units)}"
        raise InvalidInputError(msg, details={"crs": crs.to_string(), "units": sorted(axis_units)})
    return crs


def is_metric_crs(crs_input: str | CRS) -> bool:
    """Non-raising variant of :func:`require_metric_crs`."""
    try:
        require_metric_crs(crs_input)
    except InvalidInputError:
        return False
    return True
