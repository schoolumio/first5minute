"""Global match scanner (plan-gated on the backend)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased

from app.api.deps import get_current_user, require_verified
from app.core.database import get_db, utcnow
from app.models import BettingMarket, Competition, Fixture, OddsSnapshot, Prediction, Team, User
from app.schemas.common import prediction_out
from app.services.entitlements import entitlements
from app.services.settings import get_setting

router = APIRouter(prefix="/scanner", tags=["scanner"])

DQ = ["insufficient", "low", "medium", "high"]


class ScannerFilters(BaseModel):
    date_from: date | None = None
    date_to: date | None = None
    country: str | None = Field(default=None, max_length=80)
    competition_id: int | None = None
    competition_type: str | None = Field(default=None, pattern="^(league|cup|international|continental)$")
    gender: str | None = Field(default=None, pattern="^(men|women)$")
    market: str | None = Field(default=None, pattern="^MARKET_[AB]$")
    categories: list[str] = Field(default_factory=lambda: ["qualified", "watchlist"])
    min_probability: float | None = Field(default=None, ge=0, le=1)
    min_sample: int | None = Field(default=None, ge=0, le=100)
    min_data_quality: str | None = Field(default=None, pattern="^(low|medium|high)$")
    team: str | None = Field(default=None, max_length=80)
    sort: str = Field(default="probability", pattern="^(probability|kickoff|competition|value)$")
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=25, ge=1, le=100)


ADVANCED = ("min_sample", "min_data_quality", "team", "country", "competition_type")


def _latest_best_odds(db: Session, fixture_ids: list[int]) -> dict[tuple[int, str], dict]:
    if not fixture_ids:
        return {}
    rows = db.execute(
        select(OddsSnapshot, BettingMarket.code)
        .join(BettingMarket, BettingMarket.id == OddsSnapshot.market_id)
        .where(OddsSnapshot.fixture_id.in_(fixture_ids), OddsSnapshot.is_available.is_(True))
        .order_by(OddsSnapshot.captured_at.desc())
    ).all()
    latest: dict[tuple[int, str, int], OddsSnapshot] = {}
    for snap, code in rows:
        latest.setdefault((snap.fixture_id, code, snap.bookmaker_id), snap)
    best: dict[tuple[int, str], dict] = {}
    for (fid, code, _), snap in latest.items():
        cur = best.get((fid, code))
        if cur is None or float(snap.decimal_odds) > cur["decimal_odds"]:
            best[(fid, code)] = {"decimal_odds": float(snap.decimal_odds), "bookmaker": snap.bookmaker.name,
                                 "captured_at": snap.captured_at.isoformat()}
    return best


def run_scanner(db: Session, user: User, f: ScannerFilters) -> dict:
    ent = entitlements(db, user)
    feats = ent["features"]
    used_advanced = [k for k in ADVANCED if getattr(f, k) not in (None, "")]
    if used_advanced and not feats.get("advanced_filters"):
        raise HTTPException(402, {"message": "Advanced filters require the Pro plan.", "feature": "advanced_filters",
                                  "required_plan": "pro", "filters": used_advanced})
    if f.sort == "value" and not feats.get("odds_comparison"):
        raise HTTPException(402, {"message": "Value sorting requires odds comparison (Pro).",
                                  "feature": "odds_comparison", "required_plan": "pro"})
    now = utcnow()
    lookahead = float(get_setting(db, "scanner.thresholds").get("lookahead_hours", 72))
    start = datetime.combine(f.date_from, time(0), UTC) if f.date_from else now
    end = datetime.combine(f.date_to, time(0), UTC) + timedelta(days=1) if f.date_to else max(start, now) + timedelta(hours=lookahead)
    start = max(start, now)  # the scanner only shows matches that have not kicked off

    home, away = aliased(Team), aliased(Team)
    q = (
        select(Prediction)
        .join(Fixture, Fixture.id == Prediction.fixture_id)
        .join(Competition, Competition.id == Fixture.competition_id)
        .join(home, home.id == Fixture.home_team_id)
        .join(away, away.id == Fixture.away_team_id)
        .where(Prediction.is_current.is_(True), Fixture.kickoff_at >= start, Fixture.kickoff_at < end,
               Fixture.status == "scheduled", Prediction.category.in_(f.categories or ["qualified"]))
    )
    if f.market:
        q = q.where(Prediction.market_code == f.market)
    if f.competition_id:
        q = q.where(Fixture.competition_id == f.competition_id)
    if f.competition_type:
        q = q.where(Competition.type == f.competition_type)
    if f.gender:
        q = q.where(Competition.gender == f.gender)
    if f.country:
        q = q.where(Competition.country.ilike(f.country))
    if f.min_probability is not None:
        q = q.where(Prediction.probability >= f.min_probability)
    if f.min_sample is not None:
        q = q.where(func.least(Prediction.sample_home, Prediction.sample_away) >= f.min_sample)
    if f.min_data_quality:
        q = q.where(Prediction.data_quality.in_(DQ[DQ.index(f.min_data_quality):]))
    if f.team:
        like = f"%{f.team}%"
        q = q.where(or_(home.name.ilike(like), away.name.ilike(like)))

    order = {
        "probability": [Prediction.probability.desc(), Fixture.kickoff_at],
        "kickoff": [Fixture.kickoff_at, Prediction.probability.desc()],
        "competition": [Competition.name, Fixture.kickoff_at],
        "value": [Prediction.probability.desc()],
    }[f.sort]
    preds = db.scalars(q.order_by(*order)).all()
    total = len(preds)
    limit = feats.get("scanner_daily_limit")
    locked = 0
    if limit is not None and not feats.get("scanner_full"):
        # Free plan: top-N qualified matches by probability only.
        preds = sorted(preds, key=lambda p: -p.probability)
        locked = max(0, total - limit)
        preds = preds[:limit]

    odds = _latest_best_odds(db, list({p.fixture_id for p in preds})) if feats.get("odds_comparison") else {}
    items = []
    for p in preds:
        item = prediction_out(p)
        o = odds.get((p.fixture_id, p.market_code))
        item["best_odds"] = o
        item["edge"] = round(p.probability * o["decimal_odds"] - 1, 4) if o else None
        items.append(item)
    if f.sort == "value":
        items.sort(key=lambda i: (i["edge"] is None, -(i["edge"] or 0)))
    page_items = items[(f.page - 1) * f.page_size: f.page * f.page_size]
    by_cat: dict[str, int] = {}
    for p in preds:
        by_cat[p.category] = by_cat.get(p.category, 0) + 1
    return {
        "items": page_items,
        "total": len(items),
        "page": f.page,
        "page_size": f.page_size,
        "pages": (len(items) + f.page_size - 1) // f.page_size,
        "locked_count": locked,
        "plan": ent["plan"],
        "window": {"from": start.isoformat(), "to": end.isoformat()},
        "counts": by_cat,
        "odds_included": bool(feats.get("odds_comparison")),
        "is_demo": any(i["is_demo"] for i in items),
    }


@router.get("")
def scanner_get(f: Annotated[ScannerFilters, Query()], user: User = Depends(require_verified), db: Session = Depends(get_db)) -> dict:
    return run_scanner(db, user, f)


@router.post("/filters")
def scanner_post(f: ScannerFilters, user: User = Depends(require_verified), db: Session = Depends(get_db)) -> dict:
    return run_scanner(db, user, f)


@router.get("/summary")
def scanner_summary(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Counts for the dashboard (not plan-limited: these are aggregate numbers)."""
    now = utcnow()
    day_start = datetime.combine(now.date(), time(0), UTC)
    lookahead = float(get_setting(db, "scanner.thresholds").get("lookahead_hours", 72))
    today_fx = db.scalar(select(func.count(Fixture.id)).where(Fixture.kickoff_at >= day_start,
                                                              Fixture.kickoff_at < day_start + timedelta(days=1))) or 0
    analysed_today = db.scalar(select(func.count(func.distinct(Prediction.fixture_id))).where(
        Prediction.kickoff_at >= day_start, Prediction.kickoff_at < day_start + timedelta(days=1))) or 0
    rows = db.execute(
        select(Prediction.market_code, Prediction.category, func.count())
        .where(Prediction.is_current.is_(True), Prediction.kickoff_at > now,
               Prediction.kickoff_at <= now + timedelta(hours=lookahead))
        .group_by(Prediction.market_code, Prediction.category)
    ).all()
    counts: dict[str, dict[str, int]] = {}
    for market, cat, n in rows:
        counts.setdefault(market, {})[cat] = n
    upcoming = db.scalar(select(func.count(Fixture.id)).where(Fixture.kickoff_at > now, Fixture.status == "scheduled",
                                                              Fixture.kickoff_at <= now + timedelta(hours=lookahead))) or 0
    return {
        "fixtures_today": today_fx,
        "fixtures_analysed_today": analysed_today,
        "upcoming_fixtures": upcoming,
        "lookahead_hours": lookahead,
        "by_market": counts,
        "qualified": sum(c.get("qualified", 0) for c in counts.values()),
        "watchlist": sum(c.get("watchlist", 0) for c in counts.values()),
        "excluded": sum(c.get("excluded", 0) for c in counts.values()),
    }
