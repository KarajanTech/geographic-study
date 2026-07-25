"""Candidate generation request and response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import AnalysisRunKind, AnalysisRunStatus
from app.schemas.geojson import GeoJSONGeometry, GeoJSONPoint


class LonLat(BaseModel):
    """A single point in EPSG:4326, as [longitude, latitude]."""

    model_config = ConfigDict(extra="forbid")

    lon: Annotated[float, Field(ge=-180.0, le=180.0)]
    lat: Annotated[float, Field(ge=-90.0, le=90.0)]


class CandidateGenerationRequest(BaseModel):
    """Parameters for one candidate generation run."""

    model_config = ConfigDict(extra="forbid")

    spacing_m: Annotated[float, Field(gt=0, le=20_000)] = 500.0
    max_slope_deg: Annotated[float, Field(ge=0, le=90)] = 25.0
    min_separation_m: Annotated[float, Field(ge=0, le=50_000)] = 0.0
    prominence_radius_m: Annotated[float, Field(gt=0, le=50_000)] = 1_000.0
    min_elevation_m: float | None = None
    max_elevation_m: float | None = None
    max_candidates: Annotated[int | None, Field(ge=1, le=100_000)] = None
    jitter_m: Annotated[float, Field(ge=0, le=10_000)] = 0.0
    seed: int = 20240101

    exclusion_zones: list[GeoJSONGeometry] = Field(
        default_factory=list, description="Zones in EPSG:4326 where no Sentinel may go."
    )
    required_sites: list[LonLat] = Field(
        default_factory=list,
        description="Existing towers or mandatory positions; bypass terrain filters.",
    )
    blocked_sites: list[LonLat] = Field(
        default_factory=list, description="Positions the operator has ruled out."
    )


class CandidateSiteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    location: GeoJSONPoint = Field(description="Point in EPSG:4326.")
    x_m: float = Field(description="Easting in the project's analysis CRS.")
    y_m: float = Field(description="Northing in the project's analysis CRS.")
    elevation_m: float
    slope_deg: float
    prominence_m: float
    rank: int = Field(description="0 is the highest ranked candidate.")
    is_allowed: bool
    is_mandatory: bool
    source: str
    filter_reasons: list[str]


class CandidateListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[CandidateSiteResponse]
    total: int


class AnalysisRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    project_id: uuid.UUID
    surface_dataset_id: uuid.UUID | None
    kind: AnalysisRunKind
    status: AnalysisRunStatus
    algorithm_version: str
    parameters: dict[str, Any]
    random_seed: int | None
    metrics: dict[str, Any]
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class AnalysisRunListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AnalysisRunResponse]
    total: int
