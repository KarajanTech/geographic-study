"""Project request and response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.geojson import GeoJSONGeometry


class ProjectCreateRequest(BaseModel):
    """Create a project from a study area drawn or uploaded as GeoJSON."""

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=200)]
    description: Annotated[str | None, Field(max_length=2000)] = None
    area: GeoJSONGeometry = Field(description="Study area in EPSG:4326.")
    analysis_crs: str | None = Field(
        default=None,
        description=(
            "Pin the projected metric CRS used for every calculation. "
            "Derived from the study area centroid when omitted."
        ),
        examples=["EPSG:25830"],
    )


class ProjectUpdateRequest(BaseModel):
    """Descriptive fields only.

    The study area and analysis CRS are immutable once datasets exist against
    them.
    """

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str | None, Field(min_length=1, max_length=200)] = None
    description: Annotated[str | None, Field(max_length=2000)] = None


class ProjectResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    name: str
    description: str | None
    area: GeoJSONGeometry = Field(description="Study area in EPSG:4326.")
    analysis_crs: str = Field(description="Projected metric CRS used for all calculations.")
    area_km2: float = Field(description="Study area surface, measured in the analysis CRS.")
    centroid_lon: float
    centroid_lat: float
    dataset_count: int
    created_at: datetime
    updated_at: datetime


class ProjectListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ProjectResponse]
    total: int
