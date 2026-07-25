"""Analysis runs and candidate sites.

Revision ID: 0003_candidate_sites
Revises: 0002_projects_and_datasets
Create Date: Phase 2
"""

from __future__ import annotations

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_candidate_sites"
down_revision: str | None = "0002_projects_and_datasets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ANALYSIS_RUN_KIND = sa.Enum("candidates", name="analysis_run_kind")
ANALYSIS_RUN_STATUS = sa.Enum(
    "pending", "running", "completed", "failed", name="analysis_run_status"
)


def upgrade() -> None:
    op.create_table(
        "analysis_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("surface_dataset_id", sa.UUID(), nullable=True),
        sa.Column("kind", ANALYSIS_RUN_KIND, nullable=False),
        sa.Column("status", ANALYSIS_RUN_STATUS, nullable=False),
        sa.Column("algorithm_version", sa.String(length=64), nullable=False),
        sa.Column("parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("random_seed", sa.BigInteger(), nullable=True),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
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
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_analysis_runs_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["surface_dataset_id"],
            ["datasets.id"],
            name=op.f("fk_analysis_runs_surface_dataset_id_datasets"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_analysis_runs")),
    )
    op.create_index("ix_analysis_runs_project_id", "analysis_runs", ["project_id"], unique=False)
    op.create_index(
        "ix_analysis_runs_project_kind", "analysis_runs", ["project_id", "kind"], unique=False
    )
    op.create_table(
        "candidate_sites",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("analysis_run_id", sa.UUID(), nullable=False),
        sa.Column(
            "geometry",
            geoalchemy2.types.Geometry(
                geometry_type="POINT",
                srid=4326,
                dimension=2,
                from_text="ST_GeomFromEWKT",
                name="geometry",
                nullable=False,
            ),
            nullable=False,
        ),
        sa.Column("x_m", sa.Float(), nullable=False),
        sa.Column("y_m", sa.Float(), nullable=False),
        sa.Column("elevation_m", sa.Float(), nullable=False),
        sa.Column("slope_deg", sa.Float(), nullable=False),
        sa.Column("prominence_m", sa.Float(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("is_allowed", sa.Boolean(), nullable=False),
        sa.Column("is_mandatory", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("filter_reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("access_score", sa.Float(), nullable=True),
        sa.Column("site_cost", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["analysis_run_id"],
            ["analysis_runs.id"],
            name=op.f("fk_candidate_sites_analysis_run_id_analysis_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_candidate_sites")),
    )
    op.create_index("ix_candidate_sites_run", "candidate_sites", ["analysis_run_id"], unique=False)
    op.create_index(
        "ix_candidate_sites_run_allowed",
        "candidate_sites",
        ["analysis_run_id", "is_allowed"],
        unique=False,
    )
    op.create_index(
        "ix_candidate_sites_run_rank", "candidate_sites", ["analysis_run_id", "rank"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_candidate_sites_run_rank", table_name="candidate_sites")
    op.drop_index("ix_candidate_sites_run_allowed", table_name="candidate_sites")
    op.drop_index("ix_candidate_sites_run", table_name="candidate_sites")
    op.drop_table("candidate_sites")
    op.drop_index("ix_analysis_runs_project_kind", table_name="analysis_runs")
    op.drop_index("ix_analysis_runs_project_id", table_name="analysis_runs")
    op.drop_table("analysis_runs")
    # Dropping the tables leaves the enum types behind in PostgreSQL.
    bind = op.get_bind()
    ANALYSIS_RUN_STATUS.drop(bind, checkfirst=True)
    ANALYSIS_RUN_KIND.drop(bind, checkfirst=True)
