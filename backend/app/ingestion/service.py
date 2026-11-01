"""Persist normalised provider data idempotently.

* Entities are upserted on (provider, provider_id) - re-ingesting is safe.
* Raw payloads are stored once per distinct content hash for audit/replay.
* Event timelines are replaced atomically when the provider corrects them;
  the fixture ``data_version`` is bumped so downstream features, predictions
  and settlements can detect and record the correction.
* Team match stats (early goals for/against at the cutoff) are derived only
  for final fixtures whose goal events reconcile with the final score.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.database import utcnow
from app.engine.settlement import GoalTiming, Rule, score_at_cutoff, timeline_consistent
from app.models import (
    Competition,
    Fixture,
    MatchEvent,
    ProviderPayload,
    Season,
    Team,
    TeamMatchStats,
)
from app.providers.football.base import (
    FINAL_STATUSES,
    NormalizedCompetition,
    NormalizedEvent,
    NormalizedFixture,
    NormalizedTeam,
)

EVENT_COLUMNS = (
    "type",
    "detail",
    "team_id",
    "scoring_team_id",
    "player_name",
    "period",
    "minute",
    "extra_minute",
    "second",
    "is_cancelled",
)


@dataclass
class IngestStats:
    fixtures_created: int = 0
    fixtures_updated: int = 0
    events_replaced: int = 0
    stats_derived: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


def _hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def store_raw_payload(db: Session, provider: str, entity_type: str, entity_id: str, payload: dict) -> bool:
    """Store payload if this exact content was not stored before. Returns True if new."""
    if not payload:
        return False
    h = _hash(payload)
    exists = db.scalar(
        select(ProviderPayload.id).where(
            ProviderPayload.provider == provider,
            ProviderPayload.entity_type == entity_type,
            ProviderPayload.provider_entity_id == entity_id,
            ProviderPayload.payload_hash == h,
        )
    )
    if exists:
        return False
    db.add(
        ProviderPayload(
            provider=provider, entity_type=entity_type, provider_entity_id=entity_id, payload_hash=h, payload=payload
        )
    )
    return True


class Ingestor:
    def __init__(self, db: Session, provider: str, is_demo: bool, rule: Rule):
        self.db = db
        self.provider = provider
        self.is_demo = is_demo
        self.rule = rule
        self.stats = IngestStats()

    # -- entity upserts ----------------------------------------------------
    def upsert_competition(self, c: NormalizedCompetition) -> tuple[Competition, Season | None]:
        row = self.db.scalar(
            select(Competition).where(Competition.provider == self.provider, Competition.provider_id == c.provider_id)
        )
        if row is None:
            row = Competition(provider=self.provider, provider_id=c.provider_id, is_demo=self.is_demo, name=c.name)
            self.db.add(row)
        row.name, row.country, row.type, row.gender = c.name, c.country, c.type, c.gender
        row.logo_url = c.logo_url or row.logo_url
        self.db.flush()
        season = None
        if c.season_label:
            season = self.db.scalar(
                select(Season).where(Season.competition_id == row.id, Season.label == c.season_label)
            )
            if season is None:
                season = Season(
                    competition_id=row.id, label=c.season_label, provider_id=c.season_provider_id, is_current=True
                )
                self.db.add(season)
                self.db.flush()
        return row, season

    def upsert_team(self, t: NormalizedTeam) -> Team:
        row = self.db.scalar(select(Team).where(Team.provider == self.provider, Team.provider_id == t.provider_id))
        if row is None:
            row = Team(provider=self.provider, provider_id=t.provider_id, is_demo=self.is_demo, name=t.name)
            self.db.add(row)
        row.name, row.short_name, row.country = t.name, t.short_name, t.country
        row.gender, row.is_national = t.gender, t.is_national
        row.logo_url = t.logo_url or row.logo_url
        self.db.flush()
        return row

    # -- fixtures -----------------------------------------------------------
    def ingest_fixture(self, nf: NormalizedFixture) -> Fixture:
        if nf.home_team.provider_id == nf.away_team.provider_id:
            self.stats.skipped += 1
            raise ValueError(f"fixture {nf.provider_id}: home and away team identical")
        if nf.kickoff_at.tzinfo is None:
            raise ValueError(f"fixture {nf.provider_id}: kickoff must be timezone-aware UTC")
        if nf.raw:
            store_raw_payload(self.db, self.provider, "fixture", nf.provider_id, nf.raw)

        comp, season = self.upsert_competition(nf.competition)
        home, away = self.upsert_team(nf.home_team), self.upsert_team(nf.away_team)
        fx = self.db.scalar(
            select(Fixture).where(Fixture.provider == self.provider, Fixture.provider_id == nf.provider_id)
        )
        created = fx is None
        if created:
            fx = Fixture(
                provider=self.provider,
                provider_id=nf.provider_id,
                is_demo=self.is_demo,
                competition_id=comp.id,
                home_team_id=home.id,
                away_team_id=away.id,
                kickoff_at=nf.kickoff_at,
            )
            self.db.add(fx)
        assert fx is not None
        score_changed = (fx.home_score_ft, fx.away_score_ft) != (nf.home_score_ft, nf.away_score_ft)
        fx.competition_id, fx.season_id = comp.id, season.id if season else fx.season_id
        fx.home_team_id, fx.away_team_id = home.id, away.id
        fx.kickoff_at, fx.actual_kickoff_at = nf.kickoff_at, nf.actual_kickoff_at
        fx.status, fx.provider_status = nf.status, nf.provider_status
        fx.round, fx.venue, fx.neutral_venue = nf.round, nf.venue, nf.neutral_venue
        fx.home_score_ft, fx.away_score_ft = nf.home_score_ft, nf.away_score_ft
        fx.home_score_ht, fx.away_score_ht = nf.home_score_ht, nf.away_score_ht
        if not created and score_changed:
            fx.data_version += 1
        self.db.flush()

        if nf.events is not None:
            self._replace_events(fx, nf, home, away)
        if created:
            self.stats.fixtures_created += 1
        else:
            self.stats.fixtures_updated += 1
        if fx.status in FINAL_STATUSES:
            self.derive_team_stats(fx)
        return fx

    @staticmethod
    def _event_key(e: NormalizedEvent) -> str:
        if e.provider_event_id:
            return f"p:{e.provider_event_id}"
        basis = f"{e.type}|{e.detail}|{e.period}|{e.minute}|{e.extra_minute}|{e.second}|{e.team_provider_id}|{e.player_name}"
        return "h:" + hashlib.sha1(basis.encode()).hexdigest()  # noqa: S324 - dedup key, not security

    def _replace_events(self, fx: Fixture, nf: NormalizedFixture, home: Team, away: Team) -> None:
        assert nf.events is not None
        team_map = {home.provider_id: home.id, away.provider_id: away.id}
        new_rows: dict[str, dict] = {}
        for i, e in enumerate(nf.events):
            key = self._event_key(e)
            if key in new_rows:  # provider duplicate
                continue
            team_id = team_map.get(e.team_provider_id or "")
            scoring = None
            if e.type == "goal" and team_id is not None:
                if e.detail == "own_goal":
                    scoring = away.id if team_id == home.id else home.id
                else:
                    scoring = team_id
            new_rows[key] = dict(
                event_key=key,
                type=e.type,
                detail=e.detail,
                team_id=team_id,
                scoring_team_id=scoring,
                player_name=e.player_name,
                period=e.period,
                minute=e.minute,
                extra_minute=e.extra_minute,
                second=e.second,
                is_cancelled=e.is_cancelled or e.detail in ("goal_cancelled", "missed_penalty"),
                sort_key=i,
            )
        existing = {
            ev.event_key: ev for ev in self.db.scalars(select(MatchEvent).where(MatchEvent.fixture_id == fx.id))
        }

        old_sigs = {k: tuple(getattr(v, c) for c in EVENT_COLUMNS) for k, v in existing.items()}
        new_sigs = {k: tuple(v[c] for c in EVENT_COLUMNS) for k, v in new_rows.items()}
        changed = old_sigs != new_sigs
        if changed:
            if nf.raw:
                store_raw_payload(self.db, self.provider, "events", nf.provider_id, {"events": nf.raw.get("events", [])})
            self.db.execute(delete(MatchEvent).where(MatchEvent.fixture_id == fx.id))
            for row in new_rows.values():
                self.db.add(MatchEvent(fixture_id=fx.id, **row))
            if existing:  # a correction, not first sync
                fx.data_version += 1
            self.stats.events_replaced += 1
        fx.events_synced_at = utcnow()
        precision = (
            "second" if new_rows and all(r["second"] is not None for r in new_rows.values() if r["type"] == "goal") else "minute"
        )
        goals = self.goal_timings(fx, list(new_rows.values()))
        fx.timeline_precision = precision
        if fx.status in FINAL_STATUSES:
            fx.timeline_status = (
                "complete" if timeline_consistent(goals, fx.home_score_ft, fx.away_score_ft) else "inconsistent"
            )
        else:
            fx.timeline_status = "partial" if new_rows else "missing"
        self.db.flush()

    @staticmethod
    def goal_timings(fx: Fixture, events: list[dict] | list[MatchEvent]) -> list[GoalTiming]:
        out = []
        for ev in events:
            get = ev.get if isinstance(ev, dict) else lambda k, _e=ev: getattr(_e, k)
            if get("type") != "goal" or get("scoring_team_id") is None:
                continue
            out.append(
                GoalTiming(
                    scoring_side="home" if get("scoring_team_id") == fx.home_team_id else "away",
                    period=get("period"),
                    minute=get("minute"),
                    extra_minute=get("extra_minute"),
                    second=get("second"),
                    is_cancelled=get("is_cancelled"),
                    is_own_goal=get("detail") == "own_goal",
                )
            )
        return out

    def derive_team_stats(self, fx: Fixture) -> None:
        """(Re)compute early-goal stats for both sides of a final fixture."""
        events = list(self.db.scalars(select(MatchEvent).where(MatchEvent.fixture_id == fx.id)))
        goals = self.goal_timings(fx, events)
        reliable = fx.timeline_status == "complete"
        cut = score_at_cutoff(goals, self.rule) if reliable else None
        if cut is not None and not cut.resolved:
            reliable = False
        eh = cut.home if (cut and cut.resolved) else 0
        ea = cut.away if (cut and cut.resolved) else 0
        valid_goals = sorted(
            (g for g in goals if not g.is_cancelled and g.period in ("1H", "2H")),
            key=lambda g: (g.period, g.minute, g.extra_minute or 0),
        )
        # Providers report absolute match minutes (2H goals are 46'+).
        first_minute = valid_goals[0].minute if valid_goals else None
        early_red = any(
            ev.type == "card" and ev.detail == "red" and ev.period == "1H" and not ev.extra_minute and ev.minute <= 5
            for ev in events
        )
        for team_id, opp_id, is_home, gf, ga, ef, ea_ in (
            (fx.home_team_id, fx.away_team_id, True, fx.home_score_ft, fx.away_score_ft, eh, ea),
            (fx.away_team_id, fx.home_team_id, False, fx.away_score_ft, fx.home_score_ft, ea, eh),
        ):
            row = self.db.scalar(
                select(TeamMatchStats).where(TeamMatchStats.fixture_id == fx.id, TeamMatchStats.team_id == team_id)
            )
            if row is None:
                row = TeamMatchStats(fixture_id=fx.id, team_id=team_id)
                self.db.add(row)
            row.opponent_id, row.competition_id, row.kickoff_at, row.is_home = opp_id, fx.competition_id, fx.kickoff_at, is_home
            row.goals_for, row.goals_against = gf or 0, ga or 0
            row.early_goals_for, row.early_goals_against = ef or 0, ea_ or 0
            row.first_goal_minute = first_minute
            row.red_card_early = early_red
            row.settlement_rule_code = self.rule.code
            row.reliable = reliable
            row.source_data_version = fx.data_version
        self.stats.stats_derived += 1
        self.db.flush()
