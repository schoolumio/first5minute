"""Read/write admin-configurable platform settings and the default settlement rule."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine.settlement import Rule
from app.models import PlatformSetting, SettlementRule

DEFAULTS: dict[str, dict[str, Any]] = {
    "scanner.thresholds": {
        "MARKET_A": {"qualified_min_probability": 0.90, "watchlist_min_probability": 0.87},
        "MARKET_B": {"qualified_min_probability": 0.91, "watchlist_min_probability": 0.885},
        "qualified_min_team_sample": 10,
        "watchlist_min_team_sample": 5,
        "qualified_min_data_quality": "medium",
        "lookahead_hours": 72,
    },
    "model.baseline": {
        "prior_strength": 8.0,
        "max_history": 20,
        "half_life_matches": 10.0,
        "home_weight": 0.5,
        "competition_min_sample": 40,
    },
    "platform.flags": {"registrations_open": True, "maintenance_mode": False},
}


def get_setting(db: Session, key: str) -> dict[str, Any]:
    row = db.get(PlatformSetting, key)
    base = dict(DEFAULTS.get(key, {}))
    if row is not None and isinstance(row.value, dict):
        base.update(row.value)
    return base


def set_setting(db: Session, key: str, value: dict[str, Any], user_id: int | None) -> PlatformSetting:
    row = db.get(PlatformSetting, key)
    if row is None:
        row = PlatformSetting(key=key, value=value, updated_by_id=user_id)
        db.add(row)
    else:
        row.value = value
        row.updated_by_id = user_id
    db.flush()
    return row


def default_rule_row(db: Session) -> SettlementRule:
    row = db.scalar(select(SettlementRule).where(SettlementRule.is_default.is_(True)))
    if row is None:
        row = SettlementRule(code="STD_0459", description="Window 00:00-04:59", is_default=True)
        db.add(row)
        db.flush()
    return row


def rule_from_row(row: SettlementRule) -> Rule:
    return Rule(
        code=row.code,
        cutoff_seconds=row.cutoff_seconds,
        minute_convention=row.minute_convention,
        count_own_goals=row.count_own_goals,
        void_if_abandoned_before_cutoff=row.void_if_abandoned_before_cutoff,
    )
