"""DEMO football data provider - synthetic, clearly labelled development data.

Used when no real provider credentials are configured. It generates a
deterministic (seeded) set of FICTIONAL competitions and teams - every name
carries a "Demo" marker and every row is stored with ``is_demo = true`` so
the UI can flag it. It never represents real fixtures, results or odds.

Goals are sampled from a Poisson process whose team strengths are hidden
random effects; the prediction engine never sees those parameters, only the
resulting match timelines - so demo backtests exercise the real pipeline,
but say nothing about real-world accuracy.

The schedule is anchored on ``anchor`` (UTC date of seeding). Fixtures
before ``now`` are reported finished with events; later ones scheduled.
A handful of edge cases are generated on purpose: own goals, VAR-cancelled
goals, goals in the 5th minute, an abandoned and a postponed match, and a
low-quality competition with missing event timelines.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from app.providers.football import base as b

DEMO_COMPETITIONS = [
    # (id, name, country, gender, teams, timeline_missing_rate, early_rate_multiplier)
    ("d-prem", "Demo Premier Division", "Demoland", "men", 12, 0.0, 1.0),
    ("d-champ", "Demo Championship", "Demoland", "men", 12, 0.02, 0.85),
    ("d-liga", "Demo Liga Norte", "Norteland", "men", 10, 0.0, 1.15),
    ("d-women", "Demo Women's Super League", "Demoland", "women", 10, 0.0, 1.1),
    ("d-regional", "Demo Regional Cup", "Southland", "men", 8, 0.45, 1.0),
]
TEAM_WORDS = [
    "Rovers", "Athletic", "United", "City", "Wanderers", "Rangers", "Albion", "Harbour", "Valley", "Forest",
    "Town", "Olympic", "Sporting", "Dynamo", "Union", "Racing",
]
PLACES = [
    "Ashford", "Brookmere", "Calder", "Dunmore", "Eastvale", "Fairhaven", "Glenrock", "Highmoor", "Ironbridge",
    "Kingsport", "Lakeside", "Millbrook", "Northgate", "Oakfield", "Pinecrest", "Queensway", "Redcliff", "Stonebury",
    "Thornton", "Westerly",
]
ROUND_SPACING_DAYS = 4
PLAYED_ROUNDS_BEFORE_ANCHOR = 17
HOURS = [12, 14, 16, 18, 19, 20]


@dataclass
class _TeamParams:
    team: b.NormalizedTeam
    attack: float
    defence: float
    early: float  # fast-starter factor for the opening minutes


def _round_robin(n: int) -> list[list[tuple[int, int]]]:
    teams = list(range(n))
    rounds = []
    for r in range(n - 1):
        pairs = []
        for i in range(n // 2):
            a, c = teams[i], teams[n - 1 - i]
            pairs.append((a, c) if r % 2 == 0 else (c, a))
        rounds.append(pairs)
        teams = [teams[0]] + [teams[-1]] + teams[1:-1]
    return rounds + [[(h2, h1) for h1, h2 in rnd] for rnd in rounds]


class DemoFootballProvider(b.FootballDataProvider):
    name = "demo"
    is_demo = True

    def __init__(self, anchor: date, now: datetime | None = None, seed: int = 5):
        self.anchor = anchor
        self.now = now or datetime.now(UTC)
        self.seed = seed
        self._fixtures: dict[str, b.NormalizedFixture] = {}
        self._build()

    # -- generation ----------------------------------------------------------
    def _build(self) -> None:
        rng = random.Random(self.seed)
        place_iter = iter(rng.sample(PLACES * 3, len(PLACES) * 3))
        start = datetime.combine(self.anchor, time(0), UTC) - timedelta(days=ROUND_SPACING_DAYS * PLAYED_ROUNDS_BEFORE_ANCHOR)
        for cid, cname, country, gender, n_teams, missing_rate, early_mult in DEMO_COMPETITIONS:
            comp = b.NormalizedCompetition(provider_id=cid, name=cname, country=country, gender=gender,
                                           type="cup" if "Cup" in cname else "league", season_label="Demo 2026")
            teams: list[_TeamParams] = []
            used: set[str] = set()
            while len(teams) < n_teams:
                name = f"{next(place_iter)} {rng.choice(TEAM_WORDS)}"
                if gender == "women":
                    name += " Women"
                if name in used:
                    continue
                used.add(name)
                tid = f"{cid}-t{len(teams) + 1}"
                teams.append(_TeamParams(
                    team=b.NormalizedTeam(provider_id=tid, name=name, short_name=name[:3].upper(), country=country,
                                          gender=gender),
                    attack=math.exp(rng.gauss(0, 0.25)), defence=math.exp(rng.gauss(0, 0.25)),
                    early=math.exp(rng.gauss(0, 0.45)) * early_mult,
                ))
            for r_idx, pairs in enumerate(_round_robin(n_teams)):
                round_start = start + timedelta(days=ROUND_SPACING_DAYS * r_idx)
                for m_idx, (hi, ai) in enumerate(pairs):
                    kickoff = round_start + timedelta(days=m_idx % 3, hours=HOURS[(m_idx + r_idx) % len(HOURS)])
                    fid = f"{cid}-r{r_idx + 1}-m{m_idx + 1}"
                    self._fixtures[fid] = self._make_fixture(rng, fid, comp, teams[hi], teams[ai], kickoff,
                                                             f"Round {r_idx + 1}", missing_rate)

    def _make_fixture(self, rng: random.Random, fid: str, comp: b.NormalizedCompetition, home: _TeamParams,
                      away: _TeamParams, kickoff: datetime, rnd: str, missing_rate: float) -> b.NormalizedFixture:
        # Hidden generative parameters (never exposed to the engine).
        base_home, base_away = 1.45, 1.15  # goals per 90'
        lam_h90 = base_home * home.attack * away.defence
        lam_a90 = base_away * away.attack * home.defence
        early_h = lam_h90 * 5 / 90 * home.early * (away.early ** 0.5)
        early_a = lam_a90 * 5 / 90 * away.early * (home.early ** 0.5)
        events: list[b.NormalizedEvent] = []

        def add_goals(side: _TeamParams, opp: _TeamParams, n: int, lo: int, hi: int) -> None:
            for _ in range(n):
                minute = rng.randint(lo, hi)
                extra = None
                if minute in (45, 90) and rng.random() < 0.4:
                    extra = rng.randint(1, 4)
                own = rng.random() < 0.04
                team = opp if own else side
                events.append(b.NormalizedEvent(
                    type="goal", minute=minute, extra_minute=extra, team_provider_id=team.team.provider_id,
                    detail="own_goal" if own else ("penalty" if rng.random() < 0.08 else "normal"),
                    period="1H" if minute <= 45 else "2H", player_name=f"Demo Player {rng.randint(2, 30)}",
                ))

        h_early, a_early = _poisson(rng, early_h), _poisson(rng, early_a)
        add_goals(home, away, h_early, 1, 5)
        add_goals(away, home, a_early, 1, 5)
        add_goals(home, away, _poisson(rng, max(lam_h90 - early_h, 0.05)), 6, 90)
        add_goals(away, home, _poisson(rng, max(lam_a90 - early_a, 0.05)), 6, 90)
        if rng.random() < 0.03:  # VAR-cancelled goal (does not count)
            minute = rng.randint(2, 88)
            events.append(b.NormalizedEvent(type="goal", minute=minute, team_provider_id=home.team.provider_id,
                                            detail="normal", period="1H" if minute <= 45 else "2H", is_cancelled=True,
                                            player_name="Demo Player 9"))
            events.append(b.NormalizedEvent(type="var", minute=minute, team_provider_id=home.team.provider_id,
                                            detail="goal_cancelled", period="1H" if minute <= 45 else "2H"))
        if rng.random() < 0.05:
            events.append(b.NormalizedEvent(type="card", minute=rng.randint(1, 90), detail="red",
                                            team_provider_id=away.team.provider_id, period="2H"))
        events.sort(key=lambda e: (e.minute, e.extra_minute or 0))
        # Own goals count for the opponent of the player's team.
        def credited(e: b.NormalizedEvent) -> str | None:
            if e.detail == "own_goal":
                return away.team.provider_id if e.team_provider_id == home.team.provider_id else home.team.provider_id
            return e.team_provider_id

        valid = [e for e in events if e.type == "goal" and not e.is_cancelled]
        hs = sum(1 for e in valid if credited(e) == home.team.provider_id)
        as_ = sum(1 for e in valid if credited(e) == away.team.provider_id)
        hht = sum(1 for e in valid if credited(e) == home.team.provider_id and e.period == "1H")
        aht = sum(1 for e in valid if credited(e) == away.team.provider_id and e.period == "1H")
        roll = rng.random()
        special = "abandoned" if roll < 0.006 else "postponed" if roll < 0.012 else None
        timeline_missing = rng.random() < missing_rate
        return b.NormalizedFixture(
            provider_id=fid, competition=comp, home_team=home.team, away_team=away.team, kickoff_at=kickoff,
            status=b.SCHEDULED, round=rnd, venue=f"{home.team.name.split()[0]} Demo Stadium",
            home_score_ft=hs, away_score_ft=as_, home_score_ht=hht, away_score_ht=aht,
            events=None if timeline_missing else events,
            raw={"demo": True, "special": special, "timeline_missing": timeline_missing},
        )

    # -- provider interface ---------------------------------------------------
    def _view(self, f: b.NormalizedFixture, include_events: bool) -> b.NormalizedFixture:
        """Reveal results only for fixtures whose kickoff + 2h is in the past."""
        special = f.raw.get("special")
        finished = f.kickoff_at + timedelta(hours=2) <= self.now
        started = f.kickoff_at <= self.now
        if special == "postponed":
            status = b.POSTPONED if f.kickoff_at - timedelta(days=2) <= self.now else b.SCHEDULED
        elif not started:
            status = b.SCHEDULED
        elif not finished:
            status = b.LIVE
        else:
            status = b.ABANDONED if special == "abandoned" else b.FINISHED
        show = status in (b.FINISHED, b.ABANDONED)
        return b.NormalizedFixture(
            provider_id=f.provider_id, competition=f.competition, home_team=f.home_team, away_team=f.away_team,
            kickoff_at=f.kickoff_at, status=status, provider_status=status.upper()[:16], round=f.round, venue=f.venue,
            actual_kickoff_at=f.kickoff_at if started else None,
            home_score_ft=f.home_score_ft if show and status == b.FINISHED else None,
            away_score_ft=f.away_score_ft if show and status == b.FINISHED else None,
            home_score_ht=f.home_score_ht if show else None, away_score_ht=f.away_score_ht if show else None,
            events=(list(f.events) if f.events is not None else []) if (include_events and show and f.events is not None) else None,
            raw={"demo": True, "provider_fixture_id": f.provider_id, "status": status},
        )

    def all_fixture_ids(self) -> list[str]:
        return list(self._fixtures)

    def fixtures_by_date(self, day: date) -> list[b.NormalizedFixture]:
        return [self._view(f, False) for f in self._fixtures.values() if f.kickoff_at.date() == day]

    def fixture_with_events(self, provider_fixture_id: str) -> b.NormalizedFixture:
        f = self._fixtures.get(provider_fixture_id)
        if f is None:
            raise b.ProviderError(f"demo fixture {provider_fixture_id} not found")
        return self._view(f, True)

    def team_recent_fixtures(self, provider_team_id: str, last: int = 20) -> list[b.NormalizedFixture]:
        mine = [f for f in self._fixtures.values()
                if provider_team_id in (f.home_team.provider_id, f.away_team.provider_id) and f.kickoff_at <= self.now]
        mine.sort(key=lambda f: f.kickoff_at, reverse=True)
        return [self._view(f, False) for f in mine[:last]]

    def health_check(self) -> dict:
        return {"provider": self.name, "ok": True, "demo": True, "fixtures": len(self._fixtures)}


def _poisson(rng: random.Random, lam: float) -> int:
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= L:
            return k
        k += 1
