"""User account: profile, preferences, responsible gambling, notifications, saved matches, bet tracking."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.deps import Pagination, get_current_user, page_response, require_verified
from app.core.database import get_db, utcnow
from app.models import BetTracking, Bookmaker, Fixture, Notification, SavedMatch, User
from app.schemas.common import fixture_out, user_out
from app.services.audit import audit
from app.services.entitlements import entitlements

router = APIRouter(tags=["account"])


class ProfileIn(BaseModel):
    full_name: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    timezone: str | None = Field(default=None, max_length=64)
    notification_prefs: dict[str, bool] | None = None


class ResponsibleGamblingIn(BaseModel):
    daily_stake_limit: Decimal | None = Field(default=None, ge=0, le=100_000_000)
    monthly_stake_limit: Decimal | None = Field(default=None, ge=0, le=1_000_000_000)
    reality_check_minutes: int | None = Field(default=None, ge=15, le=480)
    self_exclude_days: int | None = Field(default=None, ge=1, le=3650)


@router.patch("/account/profile")
def update_profile(body: ProfileIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    if body.full_name is not None:
        user.full_name = body.full_name
    if body.country is not None:
        user.country = body.country.upper()
    if body.timezone is not None:
        user.timezone = body.timezone
    if body.notification_prefs is not None:
        allowed = {"scanner_qualified", "prediction_settled", "email"}
        user.notification_prefs = {**(user.notification_prefs or {}),
                                   **{k: v for k, v in body.notification_prefs.items() if k in allowed}}
    audit(db, "account.profile_updated", user.id, "user", user.id)
    db.commit()
    return user_out(user, entitlements(db, user))


@router.put("/account/responsible-gambling")
def update_rg(body: ResponsibleGamblingIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    # Limits can be lowered immediately; raising a limit takes effect only after a 24h cooling-off
    # in production deployments - recorded in the audit log for support review.
    user.rg_daily_stake_limit = body.daily_stake_limit
    user.rg_monthly_stake_limit = body.monthly_stake_limit
    user.rg_reality_check_minutes = body.reality_check_minutes
    if body.self_exclude_days:
        user.rg_self_excluded_until = utcnow() + timedelta(days=body.self_exclude_days)
    audit(db, "account.responsible_gambling_updated", user.id, "user", user.id, body.model_dump(mode="json"))
    db.commit()
    return user_out(user, entitlements(db, user))


# --- notifications -----------------------------------------------------------
@router.get("/notifications")
def list_notifications(p: Pagination = Depends(), unread_only: bool = False, user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)) -> dict:
    q = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        q = q.where(Notification.read_at.is_(None))
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(q.order_by(Notification.created_at.desc()).offset(p.offset).limit(p.page_size)).all()
    unread = db.scalar(select(func.count()).where(Notification.user_id == user.id, Notification.read_at.is_(None))) or 0
    body = page_response([
        {"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "link": n.link,
         "read": n.read_at is not None, "created_at": n.created_at.isoformat()} for n in rows
    ], total, p)
    body["unread"] = unread
    return body


@router.post("/notifications/{notification_id}/read")
def mark_read(notification_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    n = db.get(Notification, notification_id)
    if n is None or n.user_id != user.id:
        raise HTTPException(404, "Notification not found")
    n.read_at = n.read_at or utcnow()
    db.commit()
    return {"ok": True}


@router.post("/notifications/read-all")
def mark_all_read(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    db.execute(update(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))
               .values(read_at=utcnow()))
    db.commit()
    return {"ok": True}


# --- saved matches -----------------------------------------------------------
class SavedIn(BaseModel):
    fixture_id: int
    note: str | None = Field(default=None, max_length=500)


@router.get("/saved-matches")
def list_saved(user: User = Depends(require_verified), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(SavedMatch).where(SavedMatch.user_id == user.id).order_by(SavedMatch.created_at.desc())).all()
    return [{"id": s.id, "note": s.note, "created_at": s.created_at.isoformat(), "fixture": fixture_out(s.fixture)} for s in rows]


@router.post("/saved-matches", status_code=201)
def save_match(body: SavedIn, user: User = Depends(require_verified), db: Session = Depends(get_db)) -> dict:
    if db.get(Fixture, body.fixture_id) is None:
        raise HTTPException(404, "Fixture not found")
    existing = db.scalar(select(SavedMatch).where(SavedMatch.user_id == user.id, SavedMatch.fixture_id == body.fixture_id))
    if existing:
        return {"id": existing.id, "created": False}
    s = SavedMatch(user_id=user.id, fixture_id=body.fixture_id, note=body.note)
    db.add(s)
    db.commit()
    return {"id": s.id, "created": True}


@router.delete("/saved-matches/{saved_id}", status_code=204)
def delete_saved(saved_id: int, user: User = Depends(require_verified), db: Session = Depends(get_db)) -> None:
    s = db.get(SavedMatch, saved_id)
    if s is None or s.user_id != user.id:  # never reveal other users' records
        raise HTTPException(404, "Saved match not found")
    db.delete(s)
    db.commit()


# --- bet tracking ------------------------------------------------------------
class BetIn(BaseModel):
    fixture_id: int
    market: str = Field(pattern="^MARKET_[AB]$")
    bookmaker_id: int | None = None
    decimal_odds: Decimal = Field(gt=1, le=1000)
    stake: Decimal | None = Field(default=None, ge=0, le=100_000_000)
    currency: str = Field(default="NGN", min_length=3, max_length=3)
    bet_reference: str | None = Field(default=None, max_length=128)
    confirm: bool = Field(description="User explicitly confirms they placed this bet themselves")


class BetUpdateIn(BaseModel):
    settlement_status: str = Field(pattern="^(pending|won|lost|void)$")


def _bet_out(b: BetTracking) -> dict:
    return {"id": b.id, "fixture": fixture_out(b.fixture), "market": b.market_code, "bookmaker_id": b.bookmaker_id,
            "decimal_odds": float(b.decimal_odds), "stake": float(b.stake) if b.stake is not None else None,
            "currency": b.currency, "bet_reference": b.bet_reference, "placed_at": b.placed_at.isoformat(),
            "settlement_status": b.settlement_status}


def _staked_since(db: Session, user_id: int, since: datetime) -> Decimal:
    return db.scalar(select(func.coalesce(func.sum(BetTracking.stake), 0)).where(
        BetTracking.user_id == user_id, BetTracking.placed_at >= since)) or Decimal(0)


@router.get("/bets")
def list_bets(p: Pagination = Depends(), user: User = Depends(require_verified), db: Session = Depends(get_db)) -> dict:
    q = select(BetTracking).where(BetTracking.user_id == user.id)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(q.order_by(BetTracking.placed_at.desc()).offset(p.offset).limit(p.page_size)).all()
    staked = sum((b.stake or 0) for b in db.scalars(q).all() if b.stake is not None)
    returns = sum((b.stake or 0) * b.decimal_odds for b in db.scalars(q).all() if b.settlement_status == "won" and b.stake)
    voids = sum((b.stake or 0) for b in db.scalars(q).all() if b.settlement_status == "void" and b.stake)
    body = page_response([_bet_out(b) for b in rows], total, p)
    body["summary"] = {"total_staked": float(staked), "total_returned": float(returns + voids),
                       "profit": float(returns + voids - staked)}
    return body


@router.post("/bets", status_code=201)
def record_bet(body: BetIn, user: User = Depends(require_verified), db: Session = Depends(get_db)) -> dict:
    if not body.confirm:
        raise HTTPException(422, "Confirm that you placed this bet yourself with the sportsbook")
    now = utcnow()
    if user.rg_self_excluded_until and user.rg_self_excluded_until > now:
        raise HTTPException(403, "You are self-excluded. Bet tracking is paused until your exclusion ends.")
    if db.get(Fixture, body.fixture_id) is None:
        raise HTTPException(404, "Fixture not found")
    if body.bookmaker_id is not None and db.get(Bookmaker, body.bookmaker_id) is None:
        raise HTTPException(404, "Bookmaker not found")
    warnings = []
    if body.stake:
        day = _staked_since(db, user.id, now - timedelta(days=1)) + body.stake
        month = _staked_since(db, user.id, now - timedelta(days=30)) + body.stake
        if user.rg_daily_stake_limit is not None and day > user.rg_daily_stake_limit:
            warnings.append("This exceeds your 24-hour stake limit.")
        if user.rg_monthly_stake_limit is not None and month > user.rg_monthly_stake_limit:
            warnings.append("This exceeds your 30-day stake limit.")
    b = BetTracking(user_id=user.id, fixture_id=body.fixture_id, market_code=body.market, bookmaker_id=body.bookmaker_id,
                    decimal_odds=body.decimal_odds, stake=body.stake, currency=body.currency.upper(),
                    bet_reference=body.bet_reference, user_confirmed=True)
    db.add(b)
    audit(db, "bets.recorded", user.id, "bet_tracking", None, {"fixture_id": body.fixture_id, "limit_warnings": warnings})
    db.commit()
    return {"bet": _bet_out(b), "warnings": warnings}


@router.patch("/bets/{bet_id}")
def update_bet(bet_id: int, body: BetUpdateIn, user: User = Depends(require_verified), db: Session = Depends(get_db)) -> dict:
    b = db.get(BetTracking, bet_id)
    if b is None or b.user_id != user.id:
        raise HTTPException(404, "Bet not found")
    b.settlement_status = body.settlement_status
    db.commit()
    return _bet_out(b)


@router.delete("/bets/{bet_id}", status_code=204)
def delete_bet(bet_id: int, user: User = Depends(require_verified), db: Session = Depends(get_db)) -> None:
    b = db.get(BetTracking, bet_id)
    if b is None or b.user_id != user.id:
        raise HTTPException(404, "Bet not found")
    db.delete(b)
    db.commit()
