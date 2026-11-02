"""Auto-renewal state, saved payment authorisations and the notification email outbox.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-02
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("subscriptions", sa.Column("auto_renew", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("subscriptions", sa.Column("renewal_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("subscriptions", sa.Column("next_renewal_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("subscriptions", sa.Column("reminder_sent_for", sa.DateTime(timezone=True), nullable=True))
    op.add_column("subscriptions", sa.Column("past_due_since", sa.DateTime(timezone=True), nullable=True))
    op.add_column("invoices", sa.Column("kind", sa.String(16), nullable=False, server_default="checkout"))
    op.add_column("invoices", sa.Column("failure_reason", sa.String(200), nullable=True))
    op.add_column("notifications", sa.Column("email_requested", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("notifications", sa.Column("emailed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_notifications_email_outbox", "notifications", ["email_requested", "emailed_at"])
    op.create_table(
        "payment_methods",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("authorization_code", sa.String(128), nullable=False),
        sa.Column("card_signature", sa.String(128), nullable=True),
        sa.Column("brand", sa.String(32), nullable=True),
        sa.Column("last4", sa.String(4), nullable=True),
        sa.Column("exp_month", sa.String(2), nullable=True),
        sa.Column("exp_year", sa.String(4), nullable=True),
        sa.Column("bank", sa.String(64), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_payment_methods_user", "payment_methods", ["user_id"])


def downgrade() -> None:
    op.drop_table("payment_methods")
    op.drop_index("ix_notifications_email_outbox", table_name="notifications")
    for col in ("emailed_at", "email_requested"):
        op.drop_column("notifications", col)
    for col in ("failure_reason", "kind"):
        op.drop_column("invoices", col)
    for col in ("past_due_since", "reminder_sent_for", "next_renewal_attempt_at", "renewal_attempts", "auto_renew"):
        op.drop_column("subscriptions", col)
