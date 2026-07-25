"""Application configuration.

All settings come from the environment (prefix ``SENTINEL_``) or from a local
``.env`` file. Nothing is hardcoded to a developer machine.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from app import ALGORITHM_VERSION, __version__
from app.core.paths import default_data_dir, find_repo_root


class Environment(StrEnum):
    LOCAL = "local"
    CI = "ci"
    STAGING = "staging"
    PRODUCTION = "production"


def _env_file() -> Path | None:
    root = find_repo_root()
    return (root / ".env") if root is not None else None


class Settings(BaseSettings):
    """Runtime settings for the Sentinel Planner API."""

    model_config = SettingsConfigDict(
        env_prefix="SENTINEL_",
        env_file=_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    # --- Identity ---------------------------------------------------------
    service_name: str = "sentinel-planner-api"
    version: str = __version__
    algorithm_version: str = ALGORITHM_VERSION
    environment: Environment = Environment.LOCAL

    # --- Logging ----------------------------------------------------------
    log_level: str = "INFO"
    # JSON logs everywhere except local development, where a console renderer
    # is easier to read. Explicitly overridable via SENTINEL_LOG_JSON.
    log_json: bool | None = None

    # --- HTTP -------------------------------------------------------------
    # Bound inside a container or a dev machine, never exposed directly.
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    # NoDecode: read the raw env string and split it below, instead of the
    # default JSON decoding, so SENTINEL_CORS_ORIGINS=a,b works in a shell.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )

    # --- Persistence ------------------------------------------------------
    database_url: str | None = None
    db_connect_timeout_s: Annotated[int, Field(ge=1, le=60)] = 5

    # --- Storage ----------------------------------------------------------
    data_dir: Path = Field(default_factory=default_data_dir)
    max_upload_mb: Annotated[int, Field(ge=1, le=10_240)] = 512

    @field_validator("log_level", mode="after")
    @classmethod
    def _upper_log_level(cls, value: str) -> str:
        level = value.upper()
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}
        if level not in allowed:
            msg = f"log_level must be one of {sorted(allowed)}, got {value!r}"
            raise ValueError(msg)
        return level

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, value: object) -> object:
        """Accept a comma separated string so the value is easy to set in a shell."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("data_dir", mode="after")
    @classmethod
    def _absolute_data_dir(cls, value: Path) -> Path:
        return value.expanduser().resolve()

    # --- Derived values ---------------------------------------------------
    @property
    def use_json_logs(self) -> bool:
        """Human readable logs locally, JSON everywhere else, unless overridden."""
        if self.log_json is None:
            return self.environment is not Environment.LOCAL
        return self.log_json

    @property
    def raw_dir(self) -> Path:
        """Uploaded datasets. Written once, never modified in place."""
        return self.data_dir / "raw"

    @property
    def processed_dir(self) -> Path:
        """Reprojected, clipped and derived rasters."""
        return self.data_dir / "processed"

    @property
    def outputs_dir(self) -> Path:
        """Exports produced by an analysis run."""
        return self.data_dir / "outputs"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def is_local(self) -> bool:
        return self.environment is Environment.LOCAL


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton.

    Cached so configuration is read once; tests clear the cache instead of
    mutating global state.
    """
    return Settings()
