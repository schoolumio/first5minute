"""Deterministic MOCK provider data for tests (fictional teams, not real fixtures)."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.providers.football.base import (
    FINISHED,
    SCHEDULED,
    NormalizedCompetition,
    NormalizedEvent,
    NormalizedFixture,
    NormalizedTeam,
)

COMP = NormalizedCompetition(provider_id="mock-l1", name="Mock League", country="Testland", season_label="2026")


def team(i: int) -> NormalizedTeam:
    return NormalizedTeam(provider_id=f"mt{i}", name=f"Mock Team {i}")


def goal(minute: int, team_id: str, detail: str = "normal", extra: int | None = None, second: int | None = None,
         cancelled: bool = False) -> NormalizedEvent:
    return NormalizedEvent(type="goal", minute=minute, team_provider_id=team_id, detail=detail, extra_minute=extra,
                           second=second, period="1H" if minute <= 45 else "2H", is_cancelled=cancelled)


def fixture(fid: str, home: int, away: int, kickoff: datetime, events: list[NormalizedEvent] | None = None,
            status: str = FINISHED, score: tuple[int, int] | None = None, comp: NormalizedCompetition = COMP) -> NormalizedFixture:
    if score is None and events is not None and status == FINISHED:
        h = a = 0
        for e in events:
            if e.type != "goal" or e.is_cancelled:
                continue
            credited = e.team_provider_id
            if e.detail == "own_goal":
                credited = f"mt{away}" if e.team_provider_id == f"mt{home}" else f"mt{home}"
            if credited == f"mt{home}":
                h += 1
            else:
                a += 1
        score = (h, a)
    return NormalizedFixture(
        provider_id=fid, competition=comp, home_team=team(home), away_team=team(away), kickoff_at=kickoff,
        status=status, home_score_ft=score[0] if score else None, away_score_ft=score[1] if score else None,
        events=events if status == FINISHED else None, raw={"mock": True, "id": fid},
    )


def season_history(start: datetime, n_teams: int = 6, rounds: int = 12, early_goal_every: int = 7) -> list[NormalizedFixture]:
    """Round-robin history. Every ``early_goal_every``-th match has a goal in minute 3."""
    out = []
    k = 0
    for r in range(rounds):
        for i in range(n_teams // 2):
            h = (i + r) % n_teams + 1
            a = (n_teams - 1 - i + r) % n_teams + 1
            if h == a:
                continue
            k += 1
            ko = start + timedelta(days=r * 3, hours=i)
            events = [goal(30, f"mt{h}"), goal(70, f"mt{a}")]
            if k % early_goal_every == 0:
                events.append(goal(3, f"mt{h}"))
            out.append(fixture(f"m-{r}-{i}", h, a, ko, events))
    return out


def upcoming(fid: str, home: int, away: int, kickoff: datetime) -> NormalizedFixture:
    return fixture(fid, home, away, kickoff, status=SCHEDULED)
