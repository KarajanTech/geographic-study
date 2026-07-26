"""Optimization solutions.

Revision ID: 0005_optimization_solutions
Revises: 0004_viewsheds
Create Date: Phase 4
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_optimization_solutions"
down_revision: str | None = "0004_viewsheds"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "optimization_solutions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("analysis_run_id", sa.UUID(), nullable=False),
        sa.Column("solver", sa.String(length=32), nullable=False),
        sa.Column("algorithm_version", sa.String(length=64), nullable=False),
        sa.Column("stop_reason", sa.String(length=32), nullable=False),
        sa.Column(
            "selected_candidate_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("coverage_ratio", sa.Float(), nullable=False),
        sa.Column("weighted_coverage_ratio", sa.Float(), nullable=False),
        sa.Column("visible_area_km2", sa.Float(), nullable=False),
        sa.Column("hidden_area_km2", sa.Float(), nullable=False),
        sa.Column("objective_value", sa.Float(), nullable=False),
        sa.Column("total_cost", sa.Float(), nullable=True),
        sa.Column("redundancy_metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("iterations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("runtime_seconds", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["analysis_run_id"],
            ["analysis_runs.id"],
            name=op.f("fk_optimization_solutions_analysis_run_id_analysis_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_optimization_solutions")),
    )
    op.create_index(
        "ix_optimization_solutions_run", "optimization_solutions", ["analysis_run_id"], unique=False
    )

    # AnalysisRunKind gains a new member; PostgreSQL enums are altered in place.
    op.execute("ALTER TYPE analysis_run_kind ADD VALUE IF NOT EXISTS 'optimization'")


def downgrade() -> None:
    op.drop_index("ix_optimization_solutions_run", table_name="optimization_solutions")
    op.drop_table("optimization_solutions")
    # PostgreSQL cannot remove a single enum value; see 0004_viewsheds for the
    # same trade-off applied to 'viewshed'.
