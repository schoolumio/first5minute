"""Fixtures, match details analysis, team and competition statistics."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import Pagination, get_current_user, page_response
from app.core.database import get_db
from app.engine.features import league_baseline
from app.models import Competition, Fixture, MatchEvent, Prediction, Team, TeamMatchStats, User
from app.schemas.common import competition_out, fixture_out, prediction_out, team_out
from app.services.entitlements import entitlements
from app.services.settings import get_setting

router = APIRouter(tags=["fixtures"])

TIMING_BUCKETS = [(1, 5, "1-5"), (6, 15, "6-15"), (16, 30, "16-30"), (31, 45, "31-45"), (46, 60, "46-60"),
                  (61, 75, "61-75"), (76, 200, "76-90+")]


@router.get("/fixtures")
def list_fixtures(
    p: Pagination = Depends(),
    day: date | None = Query(default=None, alias="date"),
    competition_id: int | None = None,
    status: str | None = None,
    team_id: int | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    q = select(Fixture)
    if day:
        start = datetime.combine(day, time(0), UTC)
        q = q.where(Fixture.kickoff_at >= start, Fixture.kickoff_at < start + timedelta(days=1))
    if competition_id:
        q = q.where(Fixture.competition_id == competition_id)
    if status:
        q = q.where(Fixture.status == status)
    if team_id:
        q = q.where(or_(Fixture.home_team_id == team_id, Fixture.away_team_id == team_id))
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(q.order_by(Fixture.kickoff_at).offset(p.offset).limit(p.page_size)).all()
    return page_response([fixture_out(f) for f in rows], total, p)


def _get_fixture(db: Session, fixture_id: int) -> Fixture:
    fx = db.get(Fixture, fixture_id)
    if fx is None:
        raise HTTPException(404, "Fixture not found")
    return fx


@router.get("/fixtures/{fixture_id}")
def get_fixture(fixture_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return fixture_out(_get_fixture(db, fixture_id))


@router.get("/fixtures/{fixture_id}/events")
def fixture_events(fixture_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    fx = _get_fixture(db, fixture_id)
    events = db.scalars(select(MatchEvent).where(MatchEvent.fixture_id == fx.id).order_by(MatchEvent.sort_key)).all()
    return {
        "fixture_id": fx.id,
        "timeline_status": fx.timeline_status,
        "timeline_precision": fx.timeline_precision,
        "events_synced_at": fx.events_synced_at.isoformat() if fx.events_synced_at else None,
        "events": [
            {"id": e.id, "type": e.type, "detail": e.detail, "team_id": e.team_id, "scoring_team_id": e.scoring_team_id,
             "player_name": e.player_name, "period": e.period, "minute": e.minute, "extra_minute": e.extra_minute,
             "second": e.second, "is_cancelled": e.is_cancelled} for e in events
        ],
    }


def _team_rows(db: Session, team_id: int, as_of: datetime, limit: int, is_home: bool | None = None) -> list:
    q = (select(TeamMatchStats, Fixture).join(Fixture, Fixture.id == TeamMatchStats.fixture_id)
         .where(TeamMatchStats.team_id == team_id, TeamMatchStats.kickoff_at < as_of))
    if is_home is not None:
        q = q.where(TeamMatchStats.is_home.is_(is_home))
    return db.execute(q.order_by(TeamMatchStats.kickoff_at.desc()).limit(limit)).all()


def _window_stats(rows: list) -> dict:
    reliable = [r for r, _ in rows if r.reliable]
    n = len(reliable)

    def pct(cond) -> float | None:
        return round(sum(1 for r in reliable if cond(r)) / n, 4) if n else None

    return {
        "matches": len(rows),
        "reliable_matches": n,
        "scored_early_pct": pct(lambda r: r.early_goals_for > 0),
        "conceded_early_pct": pct(lambda r: r.early_goals_against > 0),
        "clean_window_pct": pct(lambda r: r.early_goals_for == 0 and r.early_goals_against == 0),
        "level_at_cutoff_pct": pct(lambda r: r.early_goals_for == r.early_goals_against),
        "early_goals_for": sum(r.early_goals_for for r in reliable),
        "early_goals_against": sum(r.early_goals_against for r in reliable),
        "avg_goals_for": round(sum(r.goals_for for r, _ in rows) / len(rows), 3) if rows else None,
        "avg_goals_against": round(sum(r.goals_against for r, _ in rows) / len(rows), 3) if rows else None,
    }


def _timing_distribution(rows: list) -> list[dict]:
    counts = {label: 0 for *_, label in TIMING_BUCKETS}
    counts["no_goal"] = 0
    for r, _ in rows:
        if not r.reliable:
            continue
        m = r.first_goal_minute
        if m is None:
            counts["no_goal"] += 1
            continue
        for lo, hi, label in TIMING_BUCKETS:
            if lo <= m <= hi:
                counts[label] += 1
                break
    return [{"bucket": k, "count": v} for k, v in counts.items()]


def team_profile(db: Session, team: Team, as_of: datetime, venue_home: bool, full: bool) -> dict:
    last20 = _team_rows(db, team.id, as_of, 20)
    venue = _team_rows(db, team.id, as_of, 10, is_home=venue_home)
    teams = {t.id: t for t in db.scalars(select(Team).where(Team.id.in_([r.opponent_id for r, _ in last20] or [0])))}
    recent = [
        {
            "fixture_id": fx.id, "kickoff_at": fx.kickoff_at.isoformat(), "is_home": r.is_home,
            "opponent": teams[r.opponent_id].name if r.opponent_id in teams else None,
            "goals_for": r.goals_for, "goals_against": r.goals_against,
            "early_for": r.early_goals_for if r.reliable else None, "early_against": r.early_goals_against if r.reliable else None,
            "first_goal_minute": r.first_goal_minute if r.reliable else None, "reliable": r.reliable,
        }
        for r, fx in (last20 if full else last20[:5])
    ]
    windows = {"last5": _window_stats(last20[:5])}
    if full:
        windows["last10"] = _window_stats(last20[:10])
        windows["last20"] = _window_stats(last20)
    return {
        "team": team_out(team),
        "windows": windows,
        "venue": {"label": "home" if venue_home else "away", **_window_stats(venue)} if full else None,
        "first_goal_timing": _timing_distribution(last20) if full else None,
        "recent_matches": recent,
    }


@router.get("/fixtures/{fixture_id}/analysis")
def fixture_analysis(fixture_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    fx = _get_fixture(db, fixture_id)
    ent = entitlements(db, user)
    full = bool(ent["features"].get("historical_analysis"))
    as_of = fx.kickoff_at
    params = get_setting(db, "model.baseline")
    league = league_baseline(db, fx.competition_id, as_of, int(params.get("competition_min_sample", 40)))
    h2h = []
    if full:
        rows = db.scalars(
            select(Fixture).where(
                Fixture.kickoff_at < as_of, Fixture.status == "finished",
                or_(and_(Fixture.home_team_id == fx.home_team_id, Fixture.away_team_id == fx.away_team_id),
                    and_(Fixture.home_team_id == fx.away_team_id, Fixture.away_team_id == fx.home_team_id)),
            ).order_by(Fixture.kickoff_at.desc()).limit(10)
        ).all()
        for h in rows:
            st = db.scalar(select(TeamMatchStats).where(TeamMatchStats.fixture_id == h.id, TeamMatchStats.is_home.is_(True)))
            h2h.append({
                "fixture_id": h.id, "kickoff_at": h.kickoff_at.isoformat(), "home": h.home_team.name, "away": h.away_team.name,
                "score": [h.home_score_ft, h.away_score_ft],
                "score_at_cutoff": [st.early_goals_for, st.early_goals_against] if st and st.reliable else None,
            })
    preds = db.scalars(select(Prediction).where(Prediction.fixture_id == fx.id).order_by(Prediction.predicted_at.desc())).all()
    current = {p.market_code: prediction_out(p, include_fixture=False) for p in preds if p.is_current}
    return {
        "fixture": fixture_out(fx),
        "locked": {"extended_history": not full, "head_to_head": not full, "odds": not ent["features"].get("odds_comparison")},
        "home": team_profile(db, fx.home_team, as_of, True, full),
        "away": team_profile(db, fx.away_team, as_of, False, full),
        "head_to_head": h2h,
        "competition": {
            **competition_out(fx.competition),
            "baseline_home_rate": round(league.home_rate, 5),
            "baseline_away_rate": round(league.away_rate, 5),
            "baseline_sample": league.sample_size,
            "clean_window_pct": round(league.clean_window_pct, 4) if league.clean_window_pct is not None else None,
        },
        "predictions": current,
        "prediction_history": [prediction_out(p, include_fixture=False) for p in preds],
    }


@router.get("/teams/{team_id}/early-goal-stats")
def team_early_stats(team_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    team = db.get(Team, team_id)
    if team is None:
        raise HTTPException(404, "Team not found")
    full = bool(entitlements(db, user)["features"].get("historical_analysis"))
    now = datetime.now(UTC)
    prof = team_profile(db, team, now, True, full)
    prof["away_venue"] = {"label": "away", **_window_stats(_team_rows(db, team.id, now, 10, is_home=False))} if full else None
    return prof


@router.get("/competitions")
def list_competitions(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(Competition).order_by(Competition.country, Competition.name)).all()
    return [competition_out(c) for c in rows]


@router.get("/competitions/{competition_id}/statistics")
def competition_stats(competition_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    comp = db.get(Competition, competition_id)
    if comp is None:
        raise HTTPException(404, "Competition not found")
    now = datetime.now(UTC)
    params = get_setting(db, "model.baseline")
    league = league_baseline(db, comp.id, now, int(params.get("competition_min_sample", 40)))
    total = db.scalar(select(func.count(Fixture.id)).where(Fixture.competition_id == comp.id, Fixture.status == "finished")) or 0
    by_timeline = dict(db.execute(
        select(Fixture.timeline_status, func.count()).where(Fixture.competition_id == comp.id, Fixture.status == "finished")
        .group_by(Fixture.timeline_status)).all())
    rows = db.execute(select(TeamMatchStats, Fixture).join(Fixture, Fixture.id == TeamMatchStats.fixture_id)
                      .where(TeamMatchStats.competition_id == comp.id, TeamMatchStats.is_home.is_(True))).all()
    return {
        **competition_out(comp),
        "finished_fixtures": total,
        "timeline_coverage": {k: v for k, v in by_timeline.items()},
        "timeline_coverage_pct": round(by_timeline.get("complete", 0) / total, 4) if total else None,
        "baseline_home_rate": round(league.home_rate, 5),
        "baseline_away_rate": round(league.away_rate, 5),
        "baseline_sample": league.sample_size,
        "clean_window_pct": league.clean_window_pct,
        "first_goal_timing": _timing_distribution(rows),
    }
