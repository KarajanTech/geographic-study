"""Study area parsing, metric properties and buffering."""

from __future__ import annotations

from typing import Any

import pytest
from shapely.geometry import box

from app.core.errors import InvalidInputError
from app.geo.area import MAX_AREA_KM2, parse_study_area, reproject_geometry

# A 10 x 10 km square near Madrid, expressed in degrees.
MADRID_SQUARE: dict[str, Any] = {
    "type": "Polygon",
    "coordinates": [
        [[-3.80, 40.35], [-3.68, 40.35], [-3.68, 40.44], [-3.80, 40.44], [-3.80, 40.35]]
    ],
}


def test_polygon_is_accepted_and_measured_in_metres() -> None:
    area = parse_study_area(MADRID_SQUARE)

    assert area.analysis_crs == "EPSG:25830"
    assert area.geometry.geom_type == "MultiPolygon"
    # ~10.2 km x ~10.0 km near 40 degrees north.
    assert 90.0 < area.area_km2 < 120.0
    assert 35.0 < area.perimeter_km < 50.0


def test_centroid_is_reported_in_degrees() -> None:
    area = parse_study_area(MADRID_SQUARE)

    assert -3.80 < area.centroid_lon < -3.68
    assert 40.35 < area.centroid_lat < 40.44


def test_feature_and_feature_collection_are_unwrapped() -> None:
    feature = {"type": "Feature", "properties": {}, "geometry": MADRID_SQUARE}
    collection = {"type": "FeatureCollection", "features": [feature]}

    assert parse_study_area(feature).area_km2 == pytest.approx(
        parse_study_area(collection).area_km2
    )


def test_analysis_crs_can_be_pinned() -> None:
    area = parse_study_area(MADRID_SQUARE, analysis_crs="EPSG:32630")

    assert area.analysis_crs == "EPSG:32630"


def test_pinned_crs_must_be_metric() -> None:
    with pytest.raises(InvalidInputError):
        parse_study_area(MADRID_SQUARE, analysis_crs="EPSG:4326")


def test_area_is_computed_in_the_analysis_crs_not_in_degrees() -> None:
    """The same polygon measured in two UTM zones agrees to within a percent."""
    in_zone_30 = parse_study_area(MADRID_SQUARE, analysis_crs="EPSG:25830").area_km2
    in_zone_29 = parse_study_area(MADRID_SQUARE, analysis_crs="EPSG:25829").area_km2

    assert in_zone_30 == pytest.approx(in_zone_29, rel=0.02)


def test_buffer_grows_the_area_by_the_requested_metres() -> None:
    area = parse_study_area(MADRID_SQUARE)
    projected = area.projected()
    buffered = area.buffered_projected(5_000.0)

    minx, miny, maxx, maxy = projected.bounds
    bminx, bminy, bmaxx, bmaxy = buffered.bounds

    assert bminx == pytest.approx(minx - 5_000.0, abs=1.0)
    assert bmaxx == pytest.approx(maxx + 5_000.0, abs=1.0)
    assert bminy == pytest.approx(miny - 5_000.0, abs=1.0)
    assert bmaxy == pytest.approx(maxy + 5_000.0, abs=1.0)
    assert buffered.area > projected.area


def test_zero_buffer_keeps_the_area() -> None:
    area = parse_study_area(MADRID_SQUARE)

    assert area.buffered_projected(0.0).area == pytest.approx(area.projected().area, rel=1e-9)


def test_negative_buffer_is_rejected() -> None:
    area = parse_study_area(MADRID_SQUARE)

    with pytest.raises(InvalidInputError):
        area.buffered_projected(-1.0)


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "Point", "coordinates": [0, 0]},
        {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
        {"type": "FeatureCollection", "features": []},
    ],
)
def test_non_polygon_inputs_are_rejected(payload: dict[str, Any]) -> None:
    with pytest.raises(InvalidInputError):
        parse_study_area(payload)


def test_self_intersecting_polygon_is_rejected() -> None:
    bowtie = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]],
    }

    with pytest.raises(InvalidInputError) as excinfo:
        parse_study_area(bowtie)

    assert "invalid" in str(excinfo.value)


def test_coordinates_outside_wgs84_are_rejected() -> None:
    """A polygon in metres pasted as degrees must not be silently accepted."""
    projected_coords = {
        "type": "Polygon",
        "coordinates": [
            [
                [400000.0, 4590000.0],
                [410000.0, 4590000.0],
                [410000.0, 4600000.0],
                [400000.0, 4600000.0],
                [400000.0, 4590000.0],
            ]
        ],
    }

    with pytest.raises(InvalidInputError) as excinfo:
        parse_study_area(projected_coords)

    assert "EPSG:4326" in str(excinfo.value)


def test_tiny_area_is_rejected() -> None:
    tiny = {
        "type": "Polygon",
        "coordinates": [
            [
                [-3.7000, 40.4000],
                [-3.6999, 40.4000],
                [-3.6999, 40.4001],
                [-3.7000, 40.4001],
                [-3.7000, 40.4000],
            ]
        ],
    }

    with pytest.raises(InvalidInputError) as excinfo:
        parse_study_area(tiny)

    assert "too small" in str(excinfo.value)


def test_country_sized_area_is_rejected() -> None:
    huge = {
        "type": "Polygon",
        "coordinates": [[[-9.0, 36.0], [3.0, 36.0], [3.0, 44.0], [-9.0, 44.0], [-9.0, 36.0]]],
    }

    with pytest.raises(InvalidInputError) as excinfo:
        parse_study_area(huge)

    assert f"{MAX_AREA_KM2:.0f}" in str(excinfo.value)


def test_geometry_round_trips_through_reprojection() -> None:
    """4326 -> 25830 -> 4326 must return the original coordinates."""
    original = box(-3.80, 40.35, -3.68, 40.44)

    projected = reproject_geometry(original, "EPSG:4326", "EPSG:25830")
    restored = reproject_geometry(projected, "EPSG:25830", "EPSG:4326")

    assert restored.bounds == pytest.approx(original.bounds, abs=1e-7)
    # And the projected version is in metres, not degrees.
    assert projected.bounds[0] > 1000.0


def test_reprojection_to_the_same_crs_is_a_no_op() -> None:
    original = box(-3.80, 40.35, -3.68, 40.44)

    assert reproject_geometry(original, "EPSG:4326", "EPSG:4326") is original
