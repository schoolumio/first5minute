"""Automatic competition eligibility (coverage-based) with admin override.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-02
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("competitions", sa.Column("eligibility_mode", sa.String(10), nullable=False, server_default="auto"))
    op.add_column("competitions", sa.Column("eligibility_status", sa.String(12), nullable=False, server_default="unassessed"))
    op.add_column("competitions", sa.Column("eligibility_reason", sa.String(255), nullable=True))
    op.add_column("competitions", sa.Column("coverage_pct", sa.Float(), nullable=True))
    op.add_column("competitions", sa.Column("finished_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("competitions", sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    for col in ("assessed_at", "finished_count", "coverage_pct", "eligibility_reason", "eligibility_status", "eligibility_mode"):
        op.drop_column("competitions", col)
