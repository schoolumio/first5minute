"""Allow re-predicting with a previously used model version (rollback / re-activation).

The original unique key (fixture, market, model, inputs) would reject a new
prediction when an operator rolls back to an earlier model whose inputs have
not changed. Adding ``predicted_at`` keeps duplicates impossible within one
instant while permitting a genuinely new prediction row later; the
"one current prediction" partial unique index still guarantees a single
current row per fixture and market.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-01
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = "uq_predictions_fixture_id_market_code_model_version_id__f214"
NEW = "fixture_market_model_inputs_at"


def upgrade() -> None:
    op.drop_constraint(OLD, "predictions", type_="unique")
    op.create_unique_constraint(NEW, "predictions",
                                ["fixture_id", "market_code", "model_version_id", "input_data_version", "predicted_at"])


def downgrade() -> None:
    op.drop_constraint(NEW, "predictions", type_="unique")
    op.create_unique_constraint(OLD, "predictions",
                                ["fixture_id", "market_code", "model_version_id", "input_data_version"])
