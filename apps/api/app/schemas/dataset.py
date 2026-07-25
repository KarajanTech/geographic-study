"""Dataset request and response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import DatasetRole, DatasetStatus, DatasetType
from app.schemas.geojson import BoundsMetric, BoundsWGS84


class ValidationIssueResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


class ValidationResponse(BaseModel):
    """Result of validating a dataset against its project's study area."""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    errors: list[ValidationIssueResponse]
    warnings: list[ValidationIssueResponse]
    coverage_ratio: float | None = Field(
        default=None, description="Share of the study area covered by the dataset, 0 to 1."
    )


class DatasetResponse(BaseModel):
    """A stored dataset with its full geospatial description."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    project_id: uuid.UUID
    derived_from_id: uuid.UUID | None
    dataset_type: DatasetType
    role: DatasetRole
    status: DatasetStatus
    original_filename: str | None
    checksum_sha256: str
    size_bytes: int
    crs: str | None
    units: str = Field(description="Horizontal unit of the CRS: 'm', 'degree' or 'unknown'.")
    resolution_x: float | None = Field(description="Cell size along X, in `units`.")
    resolution_y: float | None = Field(description="Cell size along Y, in `units`.")
    nodata: float | None
    bounds: BoundsMetric | None = Field(description="Extent in the dataset's own CRS.")
    bounds_wgs84: BoundsWGS84 | None = Field(description="Extent in EPSG:4326, for display.")
    metadata: dict[str, Any] = Field(description="Driver, size, validation and derived files.")
    processing_history: list[dict[str, Any]] = Field(
        description="Ordered record of every transformation applied."
    )
    error: str | None
    created_at: datetime
    updated_at: datetime


class DatasetListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[DatasetResponse]
    total: int


class DemIngestionResponse(BaseModel):
    """The raw upload and the analysis-ready surface derived from it."""

    model_config = ConfigDict(extra="forbid")

    raw: DatasetResponse
    processed: DatasetResponse
    validation: ValidationResponse
    preview_url: str = Field(description="Relative URL of the hillshade PNG preview.")
    preview_bounds_wgs84: BoundsWGS84 = Field(description="Where to place the preview on a map.")
