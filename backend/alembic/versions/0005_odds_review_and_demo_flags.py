"""Bookmaker review/source/demo flags and demo marking of odds snapshots.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-02
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("bookmakers", sa.Column("source", sa.String(16), nullable=False, server_default="manual"))
    op.add_column("bookmakers", sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("bookmakers", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("odds_snapshots", sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("odds_snapshots", "is_demo")
    for col in ("last_seen_at", "is_demo", "source"):
        op.drop_column("bookmakers", col)
