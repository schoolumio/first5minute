"""Odds comparison (Pro+) and assisted sportsbook links.

Only odds recorded from a configured source are shown (never invented). Users see active, administrator-approved
bookmakers permitted in their country. Opening a sportsbook is a plain link-out: First5Minute never places bets,
holds funds or asks for sportsbook credentials.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Pagination, client_ip, page_response, rate_limit, require_feature
from app.core.config import get_settings
from app.core.database import get_db, utcnow
from app.models import BettingMarket, Bookmaker, Competition, Fixture, Prediction, User
from app.schemas.common import fixture_out
from app.services import odds as odds_svc
from app.services.audit import audit
from app.services.responsible import any_limit_reached, limit_status
from app.services.settings import default_rule_row, get_setting

router = APIRouter(prefix="/odds", tags=["odds"])

DISCLAIMER = ("18+. Odds change quickly and can be withdrawn at any time; check the price on the sportsbook before you act. "
              "Edge is a statistical estimate, not a guarantee. First5Minute does not accept bets or hold funds.")


def _max_age(db: Session) -> float:
    return float(get_setting(db, "odds.settings")["max_age_minutes"])


def _edge(prob: float | None, odds: float | None) -> float | None:
    return round(prob * odds - 1, 4) if prob is not None and odds is not None else None


@router.get("")
def odds_board(
    p: Pagination = Depends(),
    market: str | None = Query(default=None, pattern="^MARKET_[AB]$"),
    categories: list[str] = Query(default=["qualified", "watchlist"]),
    min_edge: float | None = Query(default=None, ge=-1, le=10),
    sort: str = Query(default="edge", pattern="^(edge|kickoff|probability)$"),
    user: User = Depends(require_feature("odds_comparison")),
    db: Session = Depends(get_db),
) -> dict:
    """Upcoming scanner predictions with the best fresh price across visible bookmakers."""
    now = utcnow()
    horizon = float(get_setting(db, "scanner.thresholds").get("lookahead_hours", 72))
    q = (select(Prediction).join(Fixture, Fixture.id == Prediction.fixture_id).join(Competition, Competition.id == Fixture.competition_id)
         .where(Prediction.is_current.is_(True), Fixture.status == "scheduled", Fixture.kickoff_at > now,
                Prediction.category.in_(categories)))
    if market:
        q = q.where(Prediction.market_code == market)
    preds = [pr for pr in db.scalars(q) if (pr.kickoff_at - now).total_seconds() <= horizon * 3600]
    best = odds_svc.best_fresh(db, list({pr.fixture_id for pr in preds}), user.country, now)
    items = []
    for pr in preds:
        b = best.get((pr.fixture_id, pr.market_code))
        if b is None:
            continue
        edge = _edge(pr.probability, b["decimal_odds"])
        if min_edge is not None and (edge is None or edge < min_edge):
            continue
        items.append({"prediction_id": pr.id, "fixture": fixture_out(pr.fixture), "market": pr.market_code,
                      "probability": round(pr.probability, 5), "category": pr.category, "data_quality": pr.data_quality,
                      "confidence": pr.confidence, "fair_odds": round(1 / pr.probability, 3), "best": b, "edge": edge,
                      "calibration_status": pr.model_version.calibration_status, "is_demo": pr.is_demo or b["is_demo"]})
    keys = {"edge": lambda i: -(i["edge"] if i["edge"] is not None else -9), "kickoff": lambda i: i["fixture"]["kickoff_at"],
            "probability": lambda i: -i["probability"]}
    items.sort(key=keys[sort])
    total = len(items)
    page = items[p.offset:p.offset + p.page_size]
    body = page_response(page, total, p)
    body.update({"max_age_minutes": _max_age(db), "provider": get_settings().odds_provider,
                 "provider_configured": get_settings().odds_provider != "none", "notice": DISCLAIMER,
                 "message": None if total else (
                     "No odds provider is configured." if get_settings().odds_provider == "none"
                     else "No fresh odds from approved bookmakers match your filters right now.")})
    return body


@router.get("/{fixture_id}")
def fixture_odds(fixture_id: int, user: User = Depends(require_feature("odds_comparison")), db: Session = Depends(get_db)) -> dict:
    fx = db.get(Fixture, fixture_id)
    if fx is None:
        raise HTTPException(404, "Fixture not found")
    now = utcnow()
    max_age = _max_age(db)
    default_rule = default_rule_row(db)
    status = limit_status(db, user, now)
    current = select(Prediction).where(Prediction.fixture_id == fx.id, Prediction.is_current.is_(True))
    preds = {pr.market_code: pr for pr in db.scalars(current)}
    snaps = odds_svc.visible_snapshots(db, [fx.id], user.country)
    rows = []
    for s in snaps:
        pr = preds.get(s.market.code)
        prob = pr.probability if pr and pr.category != "excluded" else None
        fresh = odds_svc.is_fresh(s, now, max_age)
        rule = s.bookmaker.settlement_rule_id
        mismatch = rule is not None and rule != default_rule.id
        can_link = bool(s.bookmaker.deep_link_template) and fresh and not status["self_excluded"]
        rows.append({
            "bookmaker": {"id": s.bookmaker.id, "code": s.bookmaker.code, "name": s.bookmaker.name, "is_demo": s.bookmaker.is_demo},
            "market": s.market.code, "selection": s.selection, "decimal_odds": float(s.decimal_odds),
            "implied_probability": round(1 / float(s.decimal_odds), 4),
            "fair_odds": round(1 / prob, 3) if prob else None,
            "edge": _edge(prob, float(s.decimal_odds)) if fresh else None,
            "is_available": s.is_available, "is_stale": not odds_svc.age_minutes(s, now) <= max_age,
            "age_minutes": round(odds_svc.age_minutes(s, now), 1),
            "last_updated": (s.provider_updated_at or s.captured_at).isoformat(), "checked_at": s.captured_at.isoformat(),
            "rule_mismatch": mismatch,
            "rule_note": ("This sportsbook settles the five-minute window differently from the model's default rule; "
                          "the estimate may not apply exactly.") if mismatch else None,
            "can_open": can_link, "is_demo": s.is_demo,
        })
    rows.sort(key=lambda r: (r["market"], r["is_stale"], not r["is_available"], -r["decimal_odds"]))
    markets = {m.code: m for m in db.scalars(select(BettingMarket))}
    best = odds_svc.best_fresh(db, [fx.id], user.country, now)
    summary = {}
    for code, pr in preds.items():
        b = best.get((fx.id, code))
        summary[code] = {"probability": round(pr.probability, 5), "category": pr.category,
                         "fair_odds": round(1 / pr.probability, 3) if pr.category != "excluded" else None,
                         "best": b, "edge": _edge(pr.probability, b["decimal_odds"]) if b and pr.category != "excluded" else None}
    provider = get_settings().odds_provider
    return {
        "fixture_id": fx.id, "kickoff_at": fx.kickoff_at.isoformat(), "odds_provider": provider,
        "provider_configured": provider != "none", "max_age_minutes": max_age, "odds": rows, "markets": summary,
        "best_history": {code: odds_svc.best_series(db, fx.id, m.id, user.country) for code, m in markets.items()},
        "responsible_gambling": status, "self_excluded": status["self_excluded"],
        "message": None if rows else (
            "No odds available. No odds provider is configured." if provider == "none"
            else "No approved sportsbook currently prices these markets for this fixture."),
        "notice": DISCLAIMER,
    }


class OpenIn(BaseModel):
    bookmaker_code: str = Field(min_length=2, max_length=48)
    market: str = Field(pattern="^MARKET_[AB]$")
    acknowledge_limits: bool = False


@router.post("/{fixture_id}/open", dependencies=[Depends(rate_limit("odds_open", 30))])
def open_sportsbook(fixture_id: int, body: OpenIn, request: Request, user: User = Depends(require_feature("odds_comparison")),
                    db: Session = Depends(get_db)) -> dict:
    """Validate and return an authorised sportsbook link. Nothing is placed or submitted on the user's behalf."""
    now = utcnow()
    status = limit_status(db, user, now)
    if status["self_excluded"]:
        raise HTTPException(403, "You are self-excluded. Sportsbook links are disabled until your exclusion ends.")
    fx = db.get(Fixture, fixture_id)
    bm = db.scalar(select(Bookmaker).where(Bookmaker.code == body.bookmaker_code))
    if fx is None or bm is None or not bm.is_active:
        raise HTTPException(404, "Sportsbook or fixture not found")
    if not odds_svc.country_allowed(bm, user.country):
        raise HTTPException(403, "This sportsbook is not available in your country.")
    if fx.status != "scheduled" or fx.kickoff_at <= now:
        raise HTTPException(409, {"message": "This match has already started or is no longer open."})
    mk = db.scalar(select(BettingMarket).where(BettingMarket.code == body.market))
    snap = next((s for s in odds_svc.latest_snapshots(db, [fx.id])
                 if s.bookmaker_id == bm.id and s.market_id == (mk.id if mk else -1)), None)
    if snap is None or not odds_svc.is_fresh(snap, now, _max_age(db)):
        raise HTTPException(409, {"message": "These odds are unavailable or out of date. Refresh the odds and try again."})
    if any_limit_reached(status) and not body.acknowledge_limits:
        raise HTTPException(409, {"message": "You have reached a stake limit you set. Confirm to continue anyway.",
                                  "code": "limit_reached", "limits": status})
    try:
        url = odds_svc.build_link(bm.deep_link_template, snap.event_ref)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    audit(db, "odds.link_opened", user.id, "fixture", fx.id,
          {"bookmaker": bm.code, "market": body.market, "odds": float(snap.decimal_odds), "demo": snap.is_demo,
           "limit_override": any_limit_reached(status)}, client_ip(request))
    db.commit()
    return {
        "url": url, "bookmaker": {"code": bm.code, "name": bm.name}, "market": body.market, "decimal_odds": float(snap.decimal_odds),
        "is_demo": snap.is_demo, "responsible_gambling": status,
        "bet_prefill": {"fixture_id": fx.id, "market": body.market, "decimal_odds": float(snap.decimal_odds), "bookmaker_id": bm.id},
        "notice": ("You are leaving First5Minute. Place any bet yourself on the sportsbook, check the price there, "
                   "and only stake what you can afford to lose."),
    }


