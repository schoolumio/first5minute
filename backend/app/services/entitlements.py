"""Plan-based feature entitlements. Always enforced server-side."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import utcnow
from app.models import Plan, Subscription, User

FEATURE_LABELS = {
    "scanner_full": "Full daily match scanner",
    "historical_analysis": "Historical analysis",
    "advanced_filters": "Advanced scanner filters",
    "odds_comparison": "Odds comparison",
    "notifications": "Match notifications",
    "performance_analytics": "Model performance analytics",
    "advanced_reports": "Advanced reports",
    "api_access": "API access",
}

MIN_PLAN_FOR = {
    "scanner_full": "starter",
    "historical_analysis": "starter",
    "advanced_filters": "pro",
    "odds_comparison": "pro",
    "notifications": "pro",
    "performance_analytics": "pro",
    "advanced_reports": "elite",
    "api_access": "elite",
}


def active_subscription(db: Session, user: User, now: datetime | None = None) -> Subscription | None:
    now = now or utcnow()
    subs = db.scalars(
        select(Subscription)
        .where(Subscription.user_id == user.id, Subscription.status.in_(["active", "cancelled"]))
        .order_by(Subscription.current_period_end.desc().nullslast())
    ).all()
    for s in subs:
        # Cancelled subscriptions keep access until the paid period ends.
        if s.current_period_end is None or s.current_period_end > now:
            return s
    return None


def effective_plan(db: Session, user: User) -> Plan:
    sub = active_subscription(db, user)
    if sub is not None:
        return sub.plan
    plan = db.scalar(select(Plan).where(Plan.code == "free"))
    if plan is None:  # pragma: no cover - seeded by migration
        raise RuntimeError("free plan missing")
    return plan


def entitlements(db: Session, user: User) -> dict:
    plan = effective_plan(db, user)
    features = dict(plan.features or {})
    if user.is_admin:
        # Admins can see everything for support purposes.
        features.update({k: True for k in MIN_PLAN_FOR})
        features["scanner_daily_limit"] = None
    return {"plan": plan.code, "plan_name": plan.name, "features": features}


def has_feature(db: Session, user: User, feature: str) -> bool:
    return bool(entitlements(db, user)["features"].get(feature))


def users_with_feature(db: Session, feature: str) -> list[User]:
    users = db.scalars(select(User).where(User.is_active.is_(True), User.email_verified_at.isnot(None))).all()
    return [u for u in users if has_feature(db, u, feature)]
