"""Projects and datasets.

Revision ID: 0002_projects_and_datasets
Revises: 0001_enable_postgis
Create Date: Phase 1
"""

from __future__ import annotations

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_projects_and_datasets"
down_revision: str | None = "0001_enable_postgis"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DATASET_TYPE = sa.Enum(
    "dem",
    "dsm",
    "vegetation",
    "roads",
    "exclusions",
    "priorities",
    "existing_sites",
    name="dataset_type",
)
DATASET_ROLE = sa.Enum("raw", "processed", "derived", name="dataset_role")
DATASET_STATUS = sa.Enum("pending", "processing", "ready", "failed", name="dataset_status")


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "area_geometry",
            geoalchemy2.types.Geometry(
                geometry_type="MULTIPOLYGON",
                srid=4326,
                dimension=2,
                from_text="ST_GeomFromEWKT",
                name="geometry",
                nullable=False,
            ),
            nullable=False,
        ),
        sa.Column("analysis_crs", sa.String(length=64), nullable=False),
        sa.Column("area_km2", sa.Float(), nullable=False),
        sa.Column("centroid_lon", sa.Float(), nullable=False),
        sa.Column("centroid_lat", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("area_km2 > 0", name=op.f("ck_projects_area_km2_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_projects")),
    )
    op.create_index("ix_projects_created_at", "projects", ["created_at"], unique=False)

    op.create_table(
        "datasets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("derived_from_id", sa.UUID(), nullable=True),
        sa.Column("dataset_type", DATASET_TYPE, nullable=False),
        sa.Column("role", DATASET_ROLE, nullable=False),
        sa.Column("status", DATASET_STATUS, nullable=False),
        sa.Column("source_uri", sa.String(length=500), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("crs", sa.String(length=64), nullable=True),
        sa.Column("units", sa.String(length=16), nullable=False),
        sa.Column("resolution_x", sa.Float(), nullable=True),
        sa.Column("resolution_y", sa.Float(), nullable=True),
        sa.Column("nodata", sa.Float(), nullable=True),
        sa.Column("bounds_left", sa.Float(), nullable=True),
        sa.Column("bounds_bottom", sa.Float(), nullable=True),
        sa.Column("bounds_right", sa.Float(), nullable=True),
        sa.Column("bounds_top", sa.Float(), nullable=True),
        sa.Column(
            "footprint",
            geoalchemy2.types.Geometry(
                geometry_type="POLYGON",
                srid=4326,
                dimension=2,
                from_text="ST_GeomFromEWKT",
                name="geometry",
            ),
            nullable=True,
        ),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("processing_history", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["derived_from_id"],
            ["datasets.id"],
            name=op.f("fk_datasets_derived_from_id_datasets"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_datasets_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_datasets")),
    )
    op.create_index("ix_datasets_checksum", "datasets", ["checksum_sha256"], unique=False)
    op.create_index("ix_datasets_project_id", "datasets", ["project_id"], unique=False)
    op.create_index("ix_datasets_project_role", "datasets", ["project_id", "role"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_datasets_project_role", table_name="datasets")
    op.drop_index("ix_datasets_project_id", table_name="datasets")
    op.drop_index("ix_datasets_checksum", table_name="datasets")
    op.drop_table("datasets")
    op.drop_index("ix_projects_created_at", table_name="projects")
    op.drop_table("projects")
    # Dropping the tables leaves the enum types behind in PostgreSQL.
    bind = op.get_bind()
    DATASET_STATUS.drop(bind, checkfirst=True)
    DATASET_ROLE.drop(bind, checkfirst=True)
    DATASET_TYPE.drop(bind, checkfirst=True)
