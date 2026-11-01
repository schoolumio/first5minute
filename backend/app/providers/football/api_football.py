"""API-Football (api-sports.io, v3) adapter.

Docs: https://www.api-football.com/documentation-v3
Requires ``API_FOOTBALL_KEY``. Endpoints used:
  GET /fixtures?date=YYYY-MM-DD           fixtures for a day
  GET /fixtures?id={id}                   fixture incl. events
  GET /fixtures?team={id}&last={n}        recent fixtures of a team
  GET /status                             account / quota health

Event minutes: ``time.elapsed`` + ``time.extra`` (stoppage). API-Football
reports minutes using the football (ordinal) convention; confirm against
your bookmaker's settlement rule (configurable in ``settlement_rules``).
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.core.config import get_settings
from app.providers.football import base as b
from app.providers.http import ProviderHttpClient

STATUS_MAP = {
    "TBD": b.SCHEDULED, "NS": b.SCHEDULED,
    "1H": b.LIVE, "HT": b.LIVE, "2H": b.LIVE, "ET": b.LIVE, "BT": b.LIVE, "P": b.LIVE, "LIVE": b.LIVE, "INT": b.SUSPENDED,
    "FT": b.FINISHED, "AET": b.FINISHED, "PEN": b.FINISHED,
    "PST": b.POSTPONED, "CANC": b.CANCELLED, "ABD": b.ABANDONED, "SUSP": b.SUSPENDED,
    "AWD": b.AWARDED, "WO": b.AWARDED,
}

EVENT_TYPE = {"goal": "goal", "card": "card", "subst": "subst", "var": "var"}
GOAL_DETAIL = {"normal goal": "normal", "own goal": "own_goal", "penalty": "penalty", "missed penalty": "missed_penalty"}
CARD_DETAIL = {"yellow card": "yellow", "red card": "red", "second yellow card": "red"}


def _period(elapsed: int, extra: int | None) -> str:
    if elapsed <= 45:
        return "1H"
    if elapsed <= 90:
        return "2H"
    if elapsed <= 120:
        return "ET"
    return "PEN"


def parse_events(raw_events: list[dict]) -> list[b.NormalizedEvent]:
    events: list[b.NormalizedEvent] = []
    for e in raw_events or []:
        t = (e.get("type") or "").lower()
        detail_raw = (e.get("detail") or "").lower()
        elapsed = int((e.get("time") or {}).get("elapsed") or 0)
        extra = (e.get("time") or {}).get("extra")
        team_id = str((e.get("team") or {}).get("id")) if (e.get("team") or {}).get("id") is not None else None
        if t == "goal":
            detail = GOAL_DETAIL.get(detail_raw, "normal")
        elif t == "card":
            detail = CARD_DETAIL.get(detail_raw, detail_raw or None)
        elif t == "var":
            detail = "goal_cancelled" if "goal cancelled" in detail_raw or "goal disallowed" in detail_raw else detail_raw
        else:
            detail = detail_raw or None
        period = "PEN" if (e.get("comments") or "").lower() == "penalty shootout" else _period(elapsed, extra)
        events.append(
            b.NormalizedEvent(
                type=EVENT_TYPE.get(t, "other"), minute=elapsed, extra_minute=int(extra) if extra else None,
                team_provider_id=team_id, detail=detail, period=period,
                player_name=(e.get("player") or {}).get("name"),
            )
        )
    # VAR "goal cancelled" events refer back to an earlier goal at the same minute for the same team.
    for var in (ev for ev in events if ev.type == "var" and ev.detail == "goal_cancelled"):
        for g in events:
            if g.type == "goal" and not g.is_cancelled and g.team_provider_id == var.team_provider_id and g.minute == var.minute:
                g.is_cancelled = True
                break
    return events


def parse_fixture(item: dict, include_events: bool) -> b.NormalizedFixture:
    fx, league, teams = item["fixture"], item["league"], item["teams"]
    score = item.get("score") or {}
    league_name = league.get("name") or "Unknown"
    gender = "women" if "women" in league_name.lower() or "feminine" in league_name.lower() else "men"
    ltype = (league.get("type") or "league").lower()
    country = league.get("country")
    comp_type = "international" if country == "World" else ("cup" if ltype == "cup" else "league")
    kickoff = datetime.fromisoformat(fx["date"].replace("Z", "+00:00")).astimezone(UTC)
    first_period = (fx.get("periods") or {}).get("first")
    status_short = (fx.get("status") or {}).get("short") or "NS"
    ht, ft = score.get("halftime") or {}, score.get("fulltime") or {}
    return b.NormalizedFixture(
        provider_id=str(fx["id"]),
        competition=b.NormalizedCompetition(
            provider_id=str(league["id"]), name=league_name, country=country, type=comp_type, gender=gender,
            logo_url=league.get("logo"), season_label=str(league.get("season")) if league.get("season") else None,
        ),
        home_team=b.NormalizedTeam(provider_id=str(teams["home"]["id"]), name=teams["home"]["name"],
                                   logo_url=teams["home"].get("logo"), gender=gender),
        away_team=b.NormalizedTeam(provider_id=str(teams["away"]["id"]), name=teams["away"]["name"],
                                   logo_url=teams["away"].get("logo"), gender=gender),
        kickoff_at=kickoff,
        actual_kickoff_at=datetime.fromtimestamp(first_period, UTC) if first_period else None,
        status=STATUS_MAP.get(status_short, b.SCHEDULED),
        provider_status=status_short,
        round=league.get("round"),
        venue=(fx.get("venue") or {}).get("name"),
        # API-Football "fulltime" is the 90-minute score; extra time is reported separately.
        home_score_ft=ft.get("home"), away_score_ft=ft.get("away"),
        home_score_ht=ht.get("home"), away_score_ht=ht.get("away"),
        events=parse_events(item.get("events") or []) if include_events else None,
        raw=item,
    )


class ApiFootballProvider(b.FootballDataProvider):
    name = "api_football"

    def __init__(self, client: ProviderHttpClient | None = None):
        settings = get_settings()
        if client is None:
            if not settings.api_football_key:
                raise b.ProviderNotConfigured("API_FOOTBALL_KEY is not set")
            client = ProviderHttpClient(
                self.name, settings.api_football_base_url, headers={"x-apisports-key": settings.api_football_key},
                per_minute=settings.api_football_requests_per_minute,
            )
        self.client = client

    def _response(self, data: dict) -> list:
        errors = data.get("errors")
        if errors and (isinstance(errors, dict) and errors or isinstance(errors, list) and len(errors)):
            raise b.ProviderError(f"api_football error: {errors}")
        return data.get("response") or []

    def fixtures_by_date(self, day: date) -> list[b.NormalizedFixture]:
        data = self.client.get("/fixtures", {"date": day.isoformat(), "timezone": "UTC"}, "fixtures_by_date")
        return [parse_fixture(i, include_events=False) for i in self._response(data)]

    def fixture_with_events(self, provider_fixture_id: str) -> b.NormalizedFixture:
        data = self.client.get("/fixtures", {"id": provider_fixture_id}, "fixture_with_events")
        items = self._response(data)
        if not items:
            raise b.ProviderError(f"fixture {provider_fixture_id} not found")
        return parse_fixture(items[0], include_events=True)

    def team_recent_fixtures(self, provider_team_id: str, last: int = 20) -> list[b.NormalizedFixture]:
        data = self.client.get("/fixtures", {"team": provider_team_id, "last": last}, "team_recent_fixtures")
        return [parse_fixture(i, include_events=False) for i in self._response(data)]

    def health_check(self) -> dict:
        data = self.client.get("/status", operation="status")
        resp = data.get("response") or {}
        return {"provider": self.name, "ok": bool(resp), "requests": resp.get("requests") if isinstance(resp, dict) else None}
