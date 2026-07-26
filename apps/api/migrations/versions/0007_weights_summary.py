"""Add OptimizationSolution.weights_summary.

Revision ID: 0007_weights_summary
Revises: 0006_shared_viewshed_cache
Create Date: Phase 6
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_weights_summary"
down_revision: str | None = "0006_shared_viewshed_cache"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "optimization_solutions",
        sa.Column("weights_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("optimization_solutions", "weights_summary")
