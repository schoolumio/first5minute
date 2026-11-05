"""Booking code converter history.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-05
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "booking_conversions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_bookmaker", sa.String(48), nullable=False),
        sa.Column("destination_bookmaker", sa.String(48), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="started"),
        sa.Column("selections_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("selections_matched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("code_generated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error_code", sa.String(48), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_booking_conversions_user_created", "booking_conversions", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_table("booking_conversions")
