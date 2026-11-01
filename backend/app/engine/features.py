"""Leak-free feature extraction from the database.

Every query is bounded by ``as_of`` (the fixture's scheduled kickoff): only
matches that kicked off strictly before it are used, so no post-kickoff
information can reach a pre-match prediction.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.engine.poisson import LeagueBaseline, TeamHistoryRecord, blend_league_baseline
from app.models import Fixture, TeamMatchStats

FEATURE_SET_VERSION = "fs-1"
LEAGUE_LOOKBACK_DAYS = 730


@dataclass(slots=True)
class TeamHistory:
    records: list[TeamHistoryRecord]
    fixture_versions: list[tuple[int, int]]  # (fixture_id, data_version) for input hashing


def team_history(db: Session, team_id: int, as_of: datetime, limit: int) -> TeamHistory:
    rows = db.execute(
        select(TeamMatchStats, Fixture.data_version)
        .join(Fixture, Fixture.id == TeamMatchStats.fixture_id)
        .where(TeamMatchStats.team_id == team_id, TeamMatchStats.kickoff_at < as_of)
        .order_by(TeamMatchStats.kickoff_at.desc())
        .limit(limit)
    ).all()
    return TeamHistory(
        records=[
            TeamHistoryRecord(
                is_home=r.is_home, early_for=r.early_goals_for, early_against=r.early_goals_against, reliable=r.reliable
            )
            for r, _ in rows
        ],
        fixture_versions=[(r.fixture_id, v) for r, v in rows],
    )


def league_baseline(db: Session, competition_id: int, as_of: datetime, min_sample: int) -> LeagueBaseline:
    since = as_of - timedelta(days=LEAGUE_LOOKBACK_DAYS)
    row = db.execute(
        select(
            func.count(TeamMatchStats.id),
            func.coalesce(func.sum(TeamMatchStats.early_goals_for), 0),
            func.coalesce(func.sum(TeamMatchStats.early_goals_against), 0),
            func.coalesce(
                func.sum(
                    case((TeamMatchStats.early_goals_for + TeamMatchStats.early_goals_against == 0, 1), else_=0)
                ),
                0,
            ),
        ).where(
            TeamMatchStats.competition_id == competition_id,
            TeamMatchStats.is_home.is_(True),
            TeamMatchStats.reliable.is_(True),
            TeamMatchStats.kickoff_at < as_of,
            TeamMatchStats.kickoff_at >= since,
        )
    ).one()
    n, home_goals, away_goals, clean = int(row[0]), int(row[1]), int(row[2]), int(row[3])
    base = blend_league_baseline(home_goals, away_goals, n, min_sample=min_sample)
    return LeagueBaseline(
        home_rate=base.home_rate, away_rate=base.away_rate, sample_size=n, clean_window_pct=(clean / n) if n else None
    )


def input_data_version(fixture: Fixture, home: TeamHistory, away: TeamHistory, league: LeagueBaseline, params: dict) -> str:
    """Deterministic hash of everything a prediction depends on."""
    basis = {
        "fs": FEATURE_SET_VERSION,
        "fixture": [fixture.id, fixture.kickoff_at.isoformat()],
        "home": home.fixture_versions,
        "away": away.fixture_versions,
        "league": [round(league.home_rate, 6), round(league.away_rate, 6), league.sample_size],
        "params": params,
    }
    return hashlib.sha256(json.dumps(basis, sort_keys=True).encode()).hexdigest()[:32]
