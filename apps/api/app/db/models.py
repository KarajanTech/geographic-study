"""SQLAlchemy entities.

Geometries are stored in EPSG:4326 because that is a storage and display
convention, not a calculation CRS. Everything metric is computed after
projecting into ``Project.analysis_crs``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

STORAGE_SRID = 4326


def _enum_values(enum_class: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_class]


class DatasetType(StrEnum):
    """Dataset kinds from ARCHITECTURE.md section 4. Phase 1 ingests DEM only."""

    DEM = "dem"
    DSM = "dsm"
    VEGETATION = "vegetation"
    ROADS = "roads"
    EXCLUSIONS = "exclusions"
    PRIORITIES = "priorities"
    EXISTING_SITES = "existing_sites"


class DatasetRole(StrEnum):
    """Raw uploads are immutable; everything else is derived from them."""

    RAW = "raw"
    PROCESSED = "processed"
    DERIVED = "derived"


class DatasetStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class AnalysisRunKind(StrEnum):
    """What an analysis run produced. One kind per roadmap phase."""

    CANDIDATES = "candidates"
    VIEWSHED = "viewshed"


class ViewshedStatus(StrEnum):
    """PostgreSQL doubles as the job queue: a worker polls rows at ``pending``."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class AnalysisRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Project(TimestampMixin, Base):
    """A study area plus the CRS every calculation for it will use."""

    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    area_geometry: Mapped[Any] = mapped_column(
        Geometry(geometry_type="MULTIPOLYGON", srid=STORAGE_SRID, spatial_index=True),
        nullable=False,
    )
    analysis_crs: Mapped[str] = mapped_column(String(64), nullable=False)
    area_km2: Mapped[float] = mapped_column(Float, nullable=False)
    centroid_lon: Mapped[float] = mapped_column(Float, nullable=False)
    centroid_lat: Mapped[float] = mapped_column(Float, nullable=False)

    datasets: Mapped[list[Dataset]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="Dataset.created_at"
    )
    analysis_runs: Mapped[list[AnalysisRun]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="AnalysisRun.created_at",
    )

    __table_args__ = (
        CheckConstraint("area_km2 > 0", name="area_km2_positive"),
        Index("ix_projects_created_at", "created_at"),
    )


class Dataset(TimestampMixin, Base):
    """A file on the storage volume plus its full geospatial description."""

    __tablename__ = "datasets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    derived_from_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=True
    )

    # values_callable stores the lowercase values ('dem'), not the member names
    # ('DEM'), so the database rows read the same as the API payloads.
    dataset_type: Mapped[DatasetType] = mapped_column(
        Enum(DatasetType, name="dataset_type", values_callable=_enum_values), nullable=False
    )
    role: Mapped[DatasetRole] = mapped_column(
        Enum(DatasetRole, name="dataset_role", values_callable=_enum_values), nullable=False
    )
    status: Mapped[DatasetStatus] = mapped_column(
        Enum(DatasetStatus, name="dataset_status", values_callable=_enum_values),
        nullable=False,
        default=DatasetStatus.PENDING,
    )

    # Path relative to the configured data directory, never an absolute path:
    # the same row must resolve on a laptop and in a container.
    source_uri: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False)

    crs: Mapped[str | None] = mapped_column(String(64), nullable=True)
    units: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    resolution_x: Mapped[float | None] = mapped_column(Float, nullable=True)
    resolution_y: Mapped[float | None] = mapped_column(Float, nullable=True)
    nodata: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Extent in the dataset's own CRS, in its own units.
    bounds_left: Mapped[float | None] = mapped_column(Float, nullable=True)
    bounds_bottom: Mapped[float | None] = mapped_column(Float, nullable=True)
    bounds_right: Mapped[float | None] = mapped_column(Float, nullable=True)
    bounds_top: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Footprint in EPSG:4326, for map display only.
    footprint: Mapped[Any | None] = mapped_column(
        Geometry(geometry_type="POLYGON", srid=STORAGE_SRID, spatial_index=True), nullable=True
    )

    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    processing_history: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    project: Mapped[Project] = relationship(back_populates="datasets")
    derived_from: Mapped[Dataset | None] = relationship(remote_side=[id])

    __table_args__ = (
        Index("ix_datasets_project_id", "project_id"),
        Index("ix_datasets_project_role", "project_id", "role"),
        Index("ix_datasets_checksum", "checksum_sha256"),
    )


class AnalysisRun(TimestampMixin, Base):
    """One execution of a pipeline stage, with everything needed to repeat it.

    Parameters, seed and algorithm version are stored on the run rather than
    derived from the current code, so a result can always be traced back to how
    it was produced — even after the code has moved on.
    """

    __tablename__ = "analysis_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    surface_dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True
    )

    kind: Mapped[AnalysisRunKind] = mapped_column(
        Enum(AnalysisRunKind, name="analysis_run_kind", values_callable=_enum_values),
        nullable=False,
    )
    status: Mapped[AnalysisRunStatus] = mapped_column(
        Enum(AnalysisRunStatus, name="analysis_run_status", values_callable=_enum_values),
        nullable=False,
        default=AnalysisRunStatus.PENDING,
    )

    algorithm_version: Mapped[str] = mapped_column(String(64), nullable=False)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    random_seed: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped[Project] = relationship(back_populates="analysis_runs")
    surface_dataset: Mapped[Dataset | None] = relationship()
    candidate_sites: Mapped[list[CandidateSite]] = relationship(
        back_populates="analysis_run",
        cascade="all, delete-orphan",
        order_by="CandidateSite.rank",
    )

    __table_args__ = (
        Index("ix_analysis_runs_project_id", "project_id"),
        Index("ix_analysis_runs_project_kind", "project_id", "kind"),
    )


class CandidateSite(Base):
    """A potential Sentinel position produced by a candidate run.

    Geometry is stored twice on purpose: in EPSG:4326 for display and joins,
    and as plain metric coordinates in the run's analysis CRS, which is what
    every distance calculation uses.
    """

    __tablename__ = "candidate_sites"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
    )

    geometry: Mapped[Any] = mapped_column(
        Geometry(geometry_type="POINT", srid=STORAGE_SRID, spatial_index=True), nullable=False
    )
    x_m: Mapped[float] = mapped_column(Float, nullable=False)
    y_m: Mapped[float] = mapped_column(Float, nullable=False)

    elevation_m: Mapped[float] = mapped_column(Float, nullable=False)
    slope_deg: Mapped[float] = mapped_column(Float, nullable=False)
    prominence_m: Mapped[float] = mapped_column(Float, nullable=False)

    # Selection order within the run: 0 is the highest ranked site.
    rank: Mapped[int] = mapped_column(nullable=False)
    is_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="grid")
    filter_reasons: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    # Populated in Phase 7, when access and cost enter the model.
    access_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    site_cost: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    analysis_run: Mapped[AnalysisRun] = relationship(back_populates="candidate_sites")

    __table_args__ = (
        Index("ix_candidate_sites_run", "analysis_run_id"),
        Index("ix_candidate_sites_run_rank", "analysis_run_id", "rank"),
        Index("ix_candidate_sites_run_allowed", "analysis_run_id", "is_allowed"),
    )


class Viewshed(Base):
    """A computed visibility mask, keyed so identical requests are cached.

    ``cache_key`` (see ``app.geo.viewshed.compute_cache_key``) is unique: it
    encodes the surface checksum, observer position and height, target height,
    range and curvature settings. A repeat request with the same inputs finds
    this row instead of recomputing — the cache called for in
    ``ARCHITECTURE.md`` §7.

    Rows are created at ``pending`` by the API request and picked up by the
    worker; PostgreSQL is the job queue, so no separate broker is needed at
    this scale.
    """

    __tablename__ = "viewsheds"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidate_sites.id", ondelete="CASCADE"), nullable=False
    )
    surface_dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False
    )

    cache_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    crs: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[ViewshedStatus] = mapped_column(
        Enum(ViewshedStatus, name="viewshed_status", values_callable=_enum_values),
        nullable=False,
        default=ViewshedStatus.PENDING,
    )
    algorithm_version: Mapped[str] = mapped_column(String(64), nullable=False)

    observer_height_m: Mapped[float] = mapped_column(Float, nullable=False)
    target_height_m: Mapped[float] = mapped_column(Float, nullable=False)
    max_distance_m: Mapped[float] = mapped_column(Float, nullable=False)
    use_earth_curvature: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    refraction_coefficient: Mapped[float] = mapped_column(Float, nullable=False)

    # Populated once computed. Paths are relative to the data directory, like
    # every other stored file.
    raster_uri: Mapped[str | None] = mapped_column(String(500), nullable=True)
    bitset_uri: Mapped[str | None] = mapped_column(String(500), nullable=True)
    preview_uri: Mapped[str | None] = mapped_column(String(500), nullable=True)
    bounds_left: Mapped[float | None] = mapped_column(Float, nullable=True)
    bounds_bottom: Mapped[float | None] = mapped_column(Float, nullable=True)
    bounds_right: Mapped[float | None] = mapped_column(Float, nullable=True)
    bounds_top: Mapped[float | None] = mapped_column(Float, nullable=True)
    # The same extent reprojected to EPSG:4326, purely so the frontend can
    # place the preview image on a map without reprojecting anything itself.
    bounds_wgs84_west: Mapped[float | None] = mapped_column(Float, nullable=True)
    bounds_wgs84_south: Mapped[float | None] = mapped_column(Float, nullable=True)
    bounds_wgs84_east: Mapped[float | None] = mapped_column(Float, nullable=True)
    bounds_wgs84_north: Mapped[float | None] = mapped_column(Float, nullable=True)
    resolution_x: Mapped[float | None] = mapped_column(Float, nullable=True)
    resolution_y: Mapped[float | None] = mapped_column(Float, nullable=True)
    observer_elevation_m: Mapped[float | None] = mapped_column(Float, nullable=True)

    visible_cell_count: Mapped[int | None] = mapped_column(nullable=True)
    total_cell_count: Mapped[int | None] = mapped_column(nullable=True)
    # Uniform-weight score for now (visible_cell_count x cell area); becomes a
    # true risk-weighted score once Phase 6 introduces cell weights.
    weighted_visible_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    candidate_site: Mapped[CandidateSite] = relationship()
    surface_dataset: Mapped[Dataset] = relationship()

    __table_args__ = (
        Index("ix_viewsheds_candidate_site", "candidate_site_id"),
        Index("ix_viewsheds_status", "status"),
    )
