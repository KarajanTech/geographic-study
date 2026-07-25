"""Analysis CRS selection is deterministic, metric and correct per region."""

from __future__ import annotations

import pytest

from app.core.errors import InvalidInputError
from app.geo.crs import (
    is_metric_crs,
    require_metric_crs,
    select_analysis_crs,
    suggest_utm_crs,
    utm_zone_for_longitude,
)


@pytest.mark.parametrize(
    ("longitude", "zone"),
    [
        (-180.0, 1),
        (-179.9, 1),
        (-3.70, 30),  # Madrid
        (2.17, 31),  # Barcelona
        (0.0, 31),
        (-15.6, 28),  # Canary Islands
        (179.9, 60),
        (180.0, 60),
    ],
)
def test_utm_zone_boundaries(longitude: float, zone: int) -> None:
    assert utm_zone_for_longitude(longitude) == zone


def test_longitude_outside_the_world_is_rejected() -> None:
    with pytest.raises(InvalidInputError):
        utm_zone_for_longitude(200.0)


@pytest.mark.parametrize(
    ("lon", "lat", "expected", "datum"),
    [
        (-3.70, 40.42, "EPSG:25830", "ETRS89"),  # Madrid
        (2.17, 41.39, "EPSG:25831", "ETRS89"),  # Barcelona
        (-8.55, 42.88, "EPSG:25829", "ETRS89"),  # Galicia
        (-15.60, 28.10, "EPSG:32628", "WGS 84"),  # Canary Islands, south of ETRS89
        (-58.38, -34.60, "EPSG:32721", "WGS 84"),  # Buenos Aires, southern hemisphere
        (-122.33, 47.61, "EPSG:32610", "WGS 84"),  # Seattle
    ],
)
def test_analysis_crs_per_region(lon: float, lat: float, expected: str, datum: str) -> None:
    selection = select_analysis_crs(lon, lat)

    assert selection.crs == expected
    assert selection.datum == datum
    assert is_metric_crs(selection.crs)


def test_selection_is_deterministic() -> None:
    first = select_analysis_crs(-3.70, 40.42)
    second = select_analysis_crs(-3.70, 40.42)

    assert first == second


def test_selected_zone_matches_proj_outside_europe() -> None:
    """Outside the ETRS89 area our rule must agree with the PROJ database."""
    for lon, lat in [(-58.38, -34.60), (-122.33, 47.61), (139.69, 35.68)]:
        assert select_analysis_crs(lon, lat).crs == suggest_utm_crs(lon, lat)


def test_latitude_outside_the_world_is_rejected() -> None:
    with pytest.raises(InvalidInputError):
        select_analysis_crs(0.0, 100.0)


def test_geographic_crs_is_not_metric() -> None:
    assert not is_metric_crs("EPSG:4326")
    with pytest.raises(InvalidInputError) as excinfo:
        require_metric_crs("EPSG:4326")
    assert "geographic" in str(excinfo.value)


def test_projected_crs_in_feet_is_not_metric() -> None:
    # NAD83 / Texas Central (ftUS).
    assert not is_metric_crs("EPSG:2277")


def test_projected_metric_crs_passes() -> None:
    crs = require_metric_crs("EPSG:25830")

    assert crs.is_projected
    assert not crs.is_geographic
