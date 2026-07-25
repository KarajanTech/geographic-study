"""Health and readiness response schemas."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ComponentStatus(StrEnum):
    UP = "up"
    DOWN = "down"
    NOT_CONFIGURED = "not_configured"


class HealthResponse(BaseModel):
    """Liveness answer. Does not touch any external dependency."""

    model_config = ConfigDict(extra="forbid")

    status: str = Field(description="Always 'ok' when the process can serve requests.")
    service: str = Field(description="Service identifier.")
    version: str = Field(description="Deployed API version.")
    environment: str = Field(description="local | ci | staging | production.")
    algorithm_version: str = Field(
        description="Version of the analysis pipeline stored with every run."
    )


class ReadinessResponse(BaseModel):
    """Readiness answer. Reports each external dependency separately."""

    model_config = ConfigDict(extra="forbid")

    status: str = Field(description="'ready' when every required dependency is up.")
    database: ComponentStatus = Field(description="PostGIS connectivity.")
    data_dir: ComponentStatus = Field(description="Whether the data directory is writable.")
