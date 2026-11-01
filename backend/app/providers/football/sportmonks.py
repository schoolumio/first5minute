"""Sportmonks Football API v3 adapter.

Docs: https://docs.sportmonks.com/football
Requires ``SPORTMONKS_TOKEN``. Endpoints used:
  GET /fixtures/date/{YYYY-MM-DD}?include=participants;league;state;scores
  GET /fixtures/{id}?include=participants;league;state;scores;events
  GET /teams/{id}?include=latest  (recent fixtures)

Event type ids (v3 core types): 14 goal, 15 own goal, 16 penalty,
17 missed penalty, 18 substitution, 19 yellow, 20 red, 21 yellow/red,
10 VAR. Verify against /core/types for your subscription; the mapping is
data-driven and can be extended without code changes elsewhere.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.core.config import get_settings
from app.providers.football import base as b
from app.providers.http import ProviderHttpClient

STATE_MAP = {
    "NS": b.SCHEDULED, "TBA": b.SCHEDULED, "DELAYED": b.SCHEDULED,
    "INPLAY_1ST_HALF": b.LIVE, "HT": b.LIVE, "INPLAY_2ND_HALF": b.LIVE, "BREAK": b.LIVE, "EXTRA_TIME_BREAK": b.LIVE,
    "INPLAY_ET": b.LIVE, "INPLAY_PENALTIES": b.LIVE, "PEN_BREAK": b.LIVE,
    "FT": b.FINISHED, "AET": b.FINISHED, "FT_PEN": b.FINISHED,
    "POSTPONED": b.POSTPONED, "CANCELLED": b.CANCELLED, "ABANDONED": b.ABANDONED, "SUSPENDED": b.SUSPENDED,
    "INTERRUPTED": b.SUSPENDED, "AWARDED": b.AWARDED, "WO": b.AWARDED,
}
EVENT_TYPES = {
    14: ("goal", "normal"), 15: ("goal", "own_goal"), 16: ("goal", "penalty"), 17: ("goal", "missed_penalty"),
    18: ("subst", None), 19: ("card", "yellow"), 20: ("card", "red"), 21: ("card", "red"), 10: ("var", None),
}


def _participants(item: dict) -> tuple[dict, dict]:
    parts = item.get("participants") or []
    home = next(p for p in parts if (p.get("meta") or {}).get("location") == "home")
    away = next(p for p in parts if (p.get("meta") or {}).get("location") == "away")
    return home, away


def _score(item: dict, description: str) -> tuple[int | None, int | None]:
    h = a = None
    for s in item.get("scores") or []:
        if s.get("description") == description:
            sc = s.get("score") or {}
            if sc.get("participant") == "home":
                h = sc.get("goals")
            elif sc.get("participant") == "away":
                a = sc.get("goals")
    return h, a


def parse_events(raw: list[dict]) -> list[b.NormalizedEvent]:
    out = []
    for e in raw or []:
        etype, detail = EVENT_TYPES.get(e.get("type_id"), ("other", None))
        minute = int(e.get("minute") or 0)
        extra = e.get("extra_minute")
        if etype == "var" and "goal" in (e.get("addition") or "").lower() and "disallowed" in (e.get("addition") or "").lower():
            detail = "goal_cancelled"
        period = "1H" if minute <= 45 else "2H" if minute <= 90 else "ET"
        if e.get("section") == "shootout":
            period = "PEN"
        out.append(
            b.NormalizedEvent(
                type=etype, detail=detail, minute=minute, extra_minute=int(extra) if extra else None,
                period=period, team_provider_id=str(e["participant_id"]) if e.get("participant_id") else None,
                player_name=e.get("player_name"), provider_event_id=str(e["id"]) if e.get("id") else None,
                is_cancelled=bool(e.get("rescinded")),
            )
        )
    return out


def parse_fixture(item: dict, include_events: bool) -> b.NormalizedFixture:
    home, away = _participants(item)
    league = item.get("league") or {}
    state = (item.get("state") or {}).get("developer_name") or "NS"
    kickoff = datetime.fromisoformat(str(item["starting_at"]).replace(" ", "T")).replace(tzinfo=UTC)
    if item.get("starting_at_timestamp"):
        kickoff = datetime.fromtimestamp(int(item["starting_at_timestamp"]), UTC)
    name = league.get("name") or "Unknown"
    # Sportmonks "2ND_HALF" is the cumulative 90-minute score (excludes extra
    # time); fall back to "CURRENT" when it is not present.
    ft = _score(item, "2ND_HALF")
    if None in ft:
        ft = _score(item, "CURRENT")
    ht = _score(item, "1ST_HALF")
    gender = "women" if "women" in name.lower() else "men"
    return b.NormalizedFixture(
        provider_id=str(item["id"]),
        competition=b.NormalizedCompetition(
            provider_id=str(item.get("league_id") or league.get("id")), name=name,
            type="cup" if league.get("sub_type") in ("cup_international", "domestic_cup") else "league",
            gender=gender, logo_url=league.get("image_path"),
            season_label=str(item.get("season_id")) if item.get("season_id") else None,
            season_provider_id=str(item.get("season_id")) if item.get("season_id") else None,
        ),
        home_team=b.NormalizedTeam(provider_id=str(home["id"]), name=home["name"], short_name=home.get("short_code"),
                                   logo_url=home.get("image_path"), gender=gender),
        away_team=b.NormalizedTeam(provider_id=str(away["id"]), name=away["name"], short_name=away.get("short_code"),
                                   logo_url=away.get("image_path"), gender=gender),
        kickoff_at=kickoff,
        status=STATE_MAP.get(state, b.SCHEDULED),
        provider_status=state,
        venue=None,
        home_score_ft=ft[0], away_score_ft=ft[1], home_score_ht=ht[0], away_score_ht=ht[1],
        events=parse_events(item.get("events") or []) if include_events else None,
        raw=item,
    )


class SportmonksProvider(b.FootballDataProvider):
    name = "sportmonks"
    BASE_INCLUDE = "participants;league;state;scores"

    def __init__(self, client: ProviderHttpClient | None = None):
        settings = get_settings()
        if client is None:
            if not settings.sportmonks_token:
                raise b.ProviderNotConfigured("SPORTMONKS_TOKEN is not set")
            client = ProviderHttpClient(
                self.name, settings.sportmonks_base_url, params={"api_token": settings.sportmonks_token},
                per_minute=settings.sportmonks_requests_per_minute,
            )
        self.client = client

    def fixtures_by_date(self, day: date) -> list[b.NormalizedFixture]:
        out: list[b.NormalizedFixture] = []
        page = 1
        while True:
            data = self.client.get(f"/fixtures/date/{day.isoformat()}",
                                   {"include": self.BASE_INCLUDE, "page": page}, "fixtures_by_date")
            out.extend(parse_fixture(i, include_events=False) for i in data.get("data") or [])
            if not (data.get("pagination") or {}).get("has_more"):
                return out
            page += 1

    def fixture_with_events(self, provider_fixture_id: str) -> b.NormalizedFixture:
        data = self.client.get(f"/fixtures/{provider_fixture_id}", {"include": self.BASE_INCLUDE + ";events"},
                               "fixture_with_events")
        if not data.get("data"):
            raise b.ProviderError(f"fixture {provider_fixture_id} not found")
        return parse_fixture(data["data"], include_events=True)

    def team_recent_fixtures(self, provider_team_id: str, last: int = 20) -> list[b.NormalizedFixture]:
        data = self.client.get(f"/teams/{provider_team_id}", {"include": "latest.participants;latest.state;latest.scores;latest.league"},
                               "team_recent_fixtures")
        latest = ((data.get("data") or {}).get("latest") or [])[:last]
        return [parse_fixture(i, include_events=False) for i in latest]
