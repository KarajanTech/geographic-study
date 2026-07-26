"""Optimization request and response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.optimization.weights import WeightPreset
from app.schemas.geojson import GeoJSONGeometry


class PriorityZoneRequest(BaseModel):
    """A zone in EPSG:4326 whose cells get an extra weight multiplier."""

    model_config = ConfigDict(extra="forbid")

    geometry: GeoJSONGeometry
    weight: Annotated[float, Field(gt=0.0, le=100.0)] = Field(
        description="Multiplier applied to this zone's cells, on top of the base weight."
    )


class OptimizationRunRequest(BaseModel):
    """Parameters for one greedy optimization run."""

    model_config = ConfigDict(extra="forbid")

    max_sites: Annotated[int | None, Field(ge=1, le=10_000)] = Field(
        default=None, description="Stop once this many Sentinel are selected."
    )
    target_coverage: Annotated[float | None, Field(gt=0.0, le=1.0)] = Field(
        default=None, description="Stop once weighted coverage reaches this fraction."
    )
    priorities_dataset_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "Use this project's priorities raster as the base cell weight, "
            "aligned to the analysis surface. Mutually exclusive with `preset`."
        ),
    )
    preset: WeightPreset | None = Field(
        default=None,
        description=(
            "Built-in terrain-derived weight preset. Exclusive with `priorities_dataset_id`."
        ),
    )
    priority_zones: list[PriorityZoneRequest] = Field(
        default_factory=list,
        description="Zone weight multiplies the base weight, on top of any preset or raster.",
    )

    @model_validator(mode="after")
    def _check_single_weight_source(self) -> OptimizationRunRequest:
        if self.priorities_dataset_id is not None and self.preset is not None:
            msg = "priorities_dataset_id and preset are mutually exclusive"
            raise ValueError(msg)
        return self


class OptimizationIteration(BaseModel):
    """One step of the greedy selection: which candidate, and what it gained."""

    model_config = ConfigDict(extra="forbid")

    step: int = Field(description="0 is the first Sentinel selected.")
    candidate_id: uuid.UUID
    viewshed_id: uuid.UUID | None
    marginal_gain: float = Field(description="Additional weighted surface this pick covers.")
    cumulative_coverage: float = Field(description="Unweighted fraction of cells covered so far.")
    cumulative_weighted_coverage: float = Field(description="Weighted fraction covered so far.")


class OptimizationSolutionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    analysis_run_id: uuid.UUID
    solver: str
    algorithm_version: str
    stop_reason: str
    selected_candidate_ids: list[uuid.UUID] = Field(
        description="In selection order: index 0 was picked first."
    )
    coverage_ratio: float
    weighted_coverage_ratio: float
    weights_summary: dict[str, Any] | None = Field(
        description="What produced the cell weights: uniform, a preset, a raster, or priority zone."
    )
    visible_area_km2: float
    hidden_area_km2: float
    objective_value: float
    total_cost: float | None
    redundancy_metrics: dict[str, Any] | None
    iterations: list[OptimizationIteration]
    runtime_seconds: float
    created_at: datetime


class OptimizationSolutionListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[OptimizationSolutionResponse]
    total: int
