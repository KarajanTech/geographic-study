"""Viewsheds.

Revision ID: 0004_viewsheds
Revises: 0003_candidate_sites
Create Date: Phase 3
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_viewsheds"
down_revision: str | None = "0003_candidate_sites"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VIEWSHED_STATUS = sa.Enum("pending", "running", "completed", "failed", name="viewshed_status")


def upgrade() -> None:
    op.create_table(
        "viewsheds",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("candidate_site_id", sa.UUID(), nullable=False),
        sa.Column("surface_dataset_id", sa.UUID(), nullable=False),
        sa.Column("cache_key", sa.String(length=64), nullable=False),
        sa.Column("crs", sa.String(length=64), nullable=True),
        sa.Column("status", VIEWSHED_STATUS, nullable=False),
        sa.Column("algorithm_version", sa.String(length=64), nullable=False),
        sa.Column("observer_height_m", sa.Float(), nullable=False),
        sa.Column("target_height_m", sa.Float(), nullable=False),
        sa.Column("max_distance_m", sa.Float(), nullable=False),
        sa.Column("use_earth_curvature", sa.Boolean(), nullable=False),
        sa.Column("refraction_coefficient", sa.Float(), nullable=False),
        sa.Column("raster_uri", sa.String(length=500), nullable=True),
        sa.Column("bitset_uri", sa.String(length=500), nullable=True),
        sa.Column("preview_uri", sa.String(length=500), nullable=True),
        sa.Column("bounds_left", sa.Float(), nullable=True),
        sa.Column("bounds_bottom", sa.Float(), nullable=True),
        sa.Column("bounds_right", sa.Float(), nullable=True),
        sa.Column("bounds_top", sa.Float(), nullable=True),
        sa.Column("bounds_wgs84_west", sa.Float(), nullable=True),
        sa.Column("bounds_wgs84_south", sa.Float(), nullable=True),
        sa.Column("bounds_wgs84_east", sa.Float(), nullable=True),
        sa.Column("bounds_wgs84_north", sa.Float(), nullable=True),
        sa.Column("resolution_x", sa.Float(), nullable=True),
        sa.Column("resolution_y", sa.Float(), nullable=True),
        sa.Column("observer_elevation_m", sa.Float(), nullable=True),
        sa.Column("visible_cell_count", sa.Integer(), nullable=True),
        sa.Column("total_cell_count", sa.Integer(), nullable=True),
        sa.Column("weighted_visible_score", sa.Float(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["candidate_site_id"],
            ["candidate_sites.id"],
            name=op.f("fk_viewsheds_candidate_site_id_candidate_sites"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["surface_dataset_id"],
            ["datasets.id"],
            name=op.f("fk_viewsheds_surface_dataset_id_datasets"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_viewsheds")),
        sa.UniqueConstraint("cache_key", name=op.f("uq_viewsheds_cache_key")),
    )
    op.create_index("ix_viewsheds_candidate_site", "viewsheds", ["candidate_site_id"], unique=False)
    op.create_index("ix_viewsheds_status", "viewsheds", ["status"], unique=False)

    # AnalysisRunKind gains a new member; PostgreSQL enums are altered in place.
    op.execute("ALTER TYPE analysis_run_kind ADD VALUE IF NOT EXISTS 'viewshed'")


def downgrade() -> None:
    op.drop_index("ix_viewsheds_status", table_name="viewsheds")
    op.drop_index("ix_viewsheds_candidate_site", table_name="viewsheds")
    op.drop_table("viewsheds")
    bind = op.get_bind()
    VIEWSHED_STATUS.drop(bind, checkfirst=True)
    # PostgreSQL cannot remove a single enum value; recreating analysis_run_kind
    # without 'viewshed' would fail if any row already uses it, and Phase 3 is
    # the first user of that value, so this downgrade is intentionally a no-op
    # for the enum itself.
