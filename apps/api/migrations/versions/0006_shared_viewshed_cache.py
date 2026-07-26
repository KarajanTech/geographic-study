"""Viewshed cache_key is no longer unique.

A cache hit now materializes a new row per candidate instead of reusing one
row's identity across candidates (see ADR 0006's addendum and
app/services/viewsheds.py), so more than one row can legitimately share a
cache_key.

Revision ID: 0006_shared_viewshed_cache
Revises: 0005_optimization_solutions
Create Date: Phase 4
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006_shared_viewshed_cache"
down_revision: str | None = "0005_optimization_solutions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("uq_viewsheds_cache_key", "viewsheds", type_="unique")
    op.create_index("ix_viewsheds_cache_key", "viewsheds", ["cache_key"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_viewsheds_cache_key", table_name="viewsheds")
    op.create_unique_constraint("uq_viewsheds_cache_key", "viewsheds", ["cache_key"])
