"""GeoJSON payloads.

Only the shapes the API actually accepts are modelled. Coordinates are always
EPSG:4326 longitude/latitude, in that order.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

GeoJSONGeometryType = Literal["Polygon", "MultiPolygon"]


class GeoJSONGeometry(BaseModel):
    """A GeoJSON Polygon or MultiPolygon in EPSG:4326."""

    model_config = ConfigDict(extra="forbid")

    type: GeoJSONGeometryType = Field(description="Polygon or MultiPolygon.")
    coordinates: list[Any] = Field(description="Longitude/latitude ring coordinates.")

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "coordinates": self.coordinates}


class BoundsWGS84(BaseModel):
    """Axis-aligned extent in EPSG:4326, for placing an image on a map."""

    model_config = ConfigDict(extra="forbid")

    west: Annotated[float, Field(ge=-180.0, le=180.0)]
    south: Annotated[float, Field(ge=-90.0, le=90.0)]
    east: Annotated[float, Field(ge=-180.0, le=180.0)]
    north: Annotated[float, Field(ge=-90.0, le=90.0)]


class BoundsMetric(BaseModel):
    """Axis-aligned extent in the dataset's own projected CRS, in metres."""

    model_config = ConfigDict(extra="forbid")

    left: float
    bottom: float
    right: float
    top: float
    crs: str = Field(description="CRS these coordinates belong to.")
    units: str = Field(description="Unit of the values; 'm' for a metric CRS.")
