"""Prediction immutability trigger and reference data (roles, plans, markets, rules, settings).

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PREDICTION_GUARD = """
CREATE OR REPLACE FUNCTION predictions_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.is_demo OR current_setting('projectfive.allow_prediction_delete', true) = 'on' THEN
            RETURN OLD;
        END IF;
        RAISE EXCEPTION 'predictions are immutable: delete of prediction % rejected', OLD.id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.fixture_id IS DISTINCT FROM OLD.fixture_id
       OR NEW.market_code IS DISTINCT FROM OLD.market_code
       OR NEW.model_version_id IS DISTINCT FROM OLD.model_version_id
       OR NEW.settlement_rule_id IS DISTINCT FROM OLD.settlement_rule_id
       OR NEW.predicted_at IS DISTINCT FROM OLD.predicted_at
       OR NEW.kickoff_at IS DISTINCT FROM OLD.kickoff_at
       OR NEW.input_data_version IS DISTINCT FROM OLD.input_data_version
       OR NEW.probability IS DISTINCT FROM OLD.probability
       OR NEW.lambda_home IS DISTINCT FROM OLD.lambda_home
       OR NEW.lambda_away IS DISTINCT FROM OLD.lambda_away
       OR NEW.components::text IS DISTINCT FROM OLD.components::text
       OR NEW.confidence IS DISTINCT FROM OLD.confidence
       OR NEW.data_quality IS DISTINCT FROM OLD.data_quality
       OR NEW.sample_home IS DISTINCT FROM OLD.sample_home
       OR NEW.sample_away IS DISTINCT FROM OLD.sample_away
       OR NEW.category IS DISTINCT FROM OLD.category
       OR NEW.is_demo IS DISTINCT FROM OLD.is_demo THEN
        RAISE EXCEPTION 'predictions are immutable: only is_current/superseded_at may change (prediction %)', OLD.id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_predictions_guard
BEFORE UPDATE OR DELETE ON predictions
FOR EACH ROW EXECUTE FUNCTION predictions_guard();
"""

ONE_CURRENT_PREDICTION = (
    "CREATE UNIQUE INDEX uq_predictions_one_current ON predictions (fixture_id, market_code) WHERE is_current"
)

FREE = {
    "scanner_daily_limit": 3,
    "scanner_full": False,
    "historical_analysis": False,
    "advanced_filters": False,
    "odds_comparison": False,
    "notifications": False,
    "performance_analytics": False,
    "advanced_reports": False,
    "api_access": False,
    "api_daily_limit": 0,
}
STARTER = {**FREE, "scanner_daily_limit": None, "scanner_full": True, "historical_analysis": True}
PRO = {
    **STARTER,
    "advanced_filters": True,
    "odds_comparison": True,
    "notifications": True,
    "performance_analytics": True,
}
ELITE = {**PRO, "advanced_reports": True, "api_access": True, "api_daily_limit": 5000}


def upgrade() -> None:
    op.execute(PREDICTION_GUARD)
    op.execute(ONE_CURRENT_PREDICTION)

    roles = sa.table("roles", sa.column("name", sa.String), sa.column("description", sa.String))
    op.bulk_insert(
        roles,
        [
            {"name": "admin", "description": "Platform administrator"},
            {"name": "user", "description": "Standard user"},
        ],
    )

    plans = sa.table(
        "plans",
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.String),
        sa.column("price_minor", sa.Integer),
        sa.column("currency", sa.String),
        sa.column("interval", sa.String),
        sa.column("rank", sa.Integer),
        sa.column("features", sa.JSON),
        sa.column("is_active", sa.Boolean),
    )
    op.bulk_insert(
        plans,
        [
            {"code": "free", "name": "Free", "description": "Limited daily insights.", "price_minor": 0,
             "currency": "NGN", "interval": "month", "rank": 0, "features": FREE, "is_active": True},
            {"code": "starter", "name": "Starter", "description": "Full daily scanner and historical analysis.",
             "price_minor": 500_000, "currency": "NGN", "interval": "month", "rank": 1, "features": STARTER,
             "is_active": True},
            {"code": "pro", "name": "Pro",
             "description": "Advanced filtering, odds comparison, notifications and performance analytics.",
             "price_minor": 1_200_000, "currency": "NGN", "interval": "month", "rank": 2, "features": PRO,
             "is_active": True},
            {"code": "elite", "name": "Elite",
             "description": "Advanced reports, extended API allowance and premium features.",
             "price_minor": 2_500_000, "currency": "NGN", "interval": "month", "rank": 3, "features": ELITE,
             "is_active": True},
        ],
    )

    markets = sa.table(
        "betting_markets",
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("selection", sa.String),
        sa.column("is_active", sa.Boolean),
    )
    op.bulk_insert(
        markets,
        [
            {"code": "MARKET_A", "name": "No goal in the first five minutes",
             "description": "Score remains 0-0 at the bookmaker-defined five-minute settlement cutoff.",
             "selection": "No goal 00:00-04:59", "is_active": True},
            {"code": "MARKET_B", "name": "Level at five minutes",
             "description": "Scores are level at the five-minute cutoff (0-0, 1-1, 2-2 ...).",
             "selection": "Draw at 04:59", "is_active": True},
        ],
    )

    rules = sa.table(
        "settlement_rules",
        sa.column("code", sa.String),
        sa.column("description", sa.String),
        sa.column("cutoff_seconds", sa.Integer),
        sa.column("minute_convention", sa.String),
        sa.column("count_own_goals", sa.Boolean),
        sa.column("void_if_abandoned_before_cutoff", sa.Boolean),
        sa.column("is_default", sa.Boolean),
    )
    op.bulk_insert(
        rules,
        [
            {"code": "STD_0459", "description": "Window 00:00-04:59; provider minutes are ordinal (minute 5 = 04:xx)",
             "cutoff_seconds": 300, "minute_convention": "ordinal", "count_own_goals": True,
             "void_if_abandoned_before_cutoff": True, "is_default": True},
            {"code": "STD_0500", "description": "Window 00:00-05:00 inclusive of the 05:00 mark",
             "cutoff_seconds": 301, "minute_convention": "ordinal", "count_own_goals": True,
             "void_if_abandoned_before_cutoff": True, "is_default": False},
        ],
    )

    settings = sa.table(
        "platform_settings",
        sa.column("key", sa.String),
        sa.column("value", sa.JSON),
        sa.column("description", sa.String),
    )
    op.bulk_insert(
        settings,
        [
            {"key": "scanner.thresholds", "description": "Scanner qualification thresholds",
             "value": {
                 "MARKET_A": {"qualified_min_probability": 0.90, "watchlist_min_probability": 0.87},
                 "MARKET_B": {"qualified_min_probability": 0.91, "watchlist_min_probability": 0.885},
                 "qualified_min_team_sample": 10,
                 "watchlist_min_team_sample": 5,
                 "qualified_min_data_quality": "medium",
                 "lookahead_hours": 72,
             }},
            {"key": "model.baseline", "description": "Baseline Poisson model hyper-parameters",
             "value": {"prior_strength": 8.0, "max_history": 20, "half_life_matches": 10.0,
                       "home_weight": 0.5, "competition_min_sample": 40}},
            {"key": "platform.flags", "description": "Feature flags",
             "value": {"registrations_open": True, "maintenance_mode": False}},
        ],
    )


def downgrade() -> None:
    op.execute("DELETE FROM platform_settings")
    op.execute("DELETE FROM settlement_rules")
    op.execute("DELETE FROM betting_markets")
    op.execute("DELETE FROM plans")
    op.execute("DELETE FROM roles")
    op.execute("DROP INDEX IF EXISTS uq_predictions_one_current")
    op.execute("DROP TRIGGER IF EXISTS trg_predictions_guard ON predictions")
    op.execute("DROP FUNCTION IF EXISTS predictions_guard()")
