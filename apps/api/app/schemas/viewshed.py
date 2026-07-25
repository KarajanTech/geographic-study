"""Viewshed request and response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import ViewshedStatus
from app.geo.viewshed import (
    DEFAULT_MAX_DISTANCE_M,
    DEFAULT_OBSERVER_HEIGHT_M,
    DEFAULT_REFRACTION_COEFFICIENT,
    DEFAULT_TARGET_HEIGHT_M,
    MAX_MAX_DISTANCE_M,
    MIN_MAX_DISTANCE_M,
)
from app.schemas.geojson import BoundsMetric, BoundsWGS84


class ViewshedRunRequest(BaseModel):
    """Parameters for a batch viewshed computation over a candidate run."""

    model_config = ConfigDict(extra="forbid")

    observer_height_m: Annotated[float, Field(ge=0, le=200)] = DEFAULT_OBSERVER_HEIGHT_M
    target_height_m: Annotated[float, Field(ge=0, le=200)] = DEFAULT_TARGET_HEIGHT_M
    max_distance_m: Annotated[float, Field(ge=MIN_MAX_DISTANCE_M, le=MAX_MAX_DISTANCE_M)] = (
        DEFAULT_MAX_DISTANCE_M
    )
    use_earth_curvature: bool = True
    refraction_coefficient: Annotated[float, Field(ge=0, le=1)] = DEFAULT_REFRACTION_COEFFICIENT
    candidate_site_ids: list[uuid.UUID] | None = Field(
        default=None,
        description="Compute only these candidates; defaults to every accepted site.",
    )


class ViewshedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    candidate_site_id: uuid.UUID
    surface_dataset_id: uuid.UUID
    status: ViewshedStatus
    algorithm_version: str
    observer_height_m: float
    target_height_m: float
    max_distance_m: float
    use_earth_curvature: bool
    refraction_coefficient: float
    bounds: BoundsMetric | None
    bounds_wgs84: BoundsWGS84 | None = Field(description="Extent in EPSG:4326, for map display.")
    preview_url: str | None = Field(default=None, description="Relative URL of the overlay PNG.")
    observer_elevation_m: float | None
    visible_cell_count: int | None
    total_cell_count: int | None
    coverage_ratio: float | None = Field(
        default=None, description="visible_cell_count / total_cell_count, 0 to 1."
    )
    weighted_visible_score: float | None
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class ViewshedListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ViewshedResponse]
    total: int
