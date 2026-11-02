"""Responsible-gambling limit status (user-defined stake limits and self-exclusion)."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import utcnow
from app.models import BetTracking, User


def _staked_since(db: Session, user_id: int, since: datetime) -> Decimal:
    return db.scalar(select(func.coalesce(func.sum(BetTracking.stake), 0)).where(
        BetTracking.user_id == user_id, BetTracking.placed_at >= since)) or Decimal(0)


def limit_status(db: Session, user: User, now: datetime | None = None) -> dict:
    now = now or utcnow()

    def window(limit: Decimal | None, days: int) -> dict:
        used = _staked_since(db, user.id, now - timedelta(days=days))
        return {"limit": float(limit) if limit is not None else None, "used": float(used),
                "reached": limit is not None and used >= limit}

    return {
        "daily": window(user.rg_daily_stake_limit, 1),
        "monthly": window(user.rg_monthly_stake_limit, 30),
        "self_excluded": bool(user.rg_self_excluded_until and user.rg_self_excluded_until > now),
        "self_excluded_until": user.rg_self_excluded_until.isoformat() if user.rg_self_excluded_until else None,
        "reality_check_minutes": user.rg_reality_check_minutes,
    }


def any_limit_reached(status: dict) -> bool:
    return bool(status["daily"]["reached"] or status["monthly"]["reached"])
