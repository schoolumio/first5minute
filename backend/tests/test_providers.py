"""Provider adapters and resilient HTTP client with MOCK provider responses."""

from datetime import UTC, date, datetime

import httpx
import pytest

from app.providers.football import api_football, sportmonks
from app.providers.football.base import FINISHED, LIVE, SCHEDULED, ProviderError
from app.providers.football.demo import DemoFootballProvider
from app.providers.http import ProviderHttpClient
from app.providers.odds.base import ApiFootballOddsProvider

APIF_FIXTURE = {
    "fixture": {"id": 101, "date": "2026-10-03T14:00:00+00:00", "status": {"short": "FT"}, "venue": {"name": "Mock Park"},
                "periods": {"first": 1791036060}},
    "league": {"id": 39, "name": "Mock League Women", "country": "Testland", "season": 2026, "round": "R 7", "type": "League"},
    "teams": {"home": {"id": 1, "name": "Home FC"}, "away": {"id": 2, "name": "Away FC"}},
    "goals": {"home": 1, "away": 1},
    "score": {"halftime": {"home": 1, "away": 0}, "fulltime": {"home": 1, "away": 1}},
    "events": [
        {"time": {"elapsed": 3, "extra": None}, "team": {"id": 2}, "player": {"name": "D"}, "type": "Goal", "detail": "Own Goal"},
        {"time": {"elapsed": 30, "extra": None}, "team": {"id": 2}, "player": {"name": "X"}, "type": "Goal", "detail": "Normal Goal"},
        {"time": {"elapsed": 30, "extra": None}, "team": {"id": 2}, "player": {"name": "X"}, "type": "Var", "detail": "Goal cancelled"},
        {"time": {"elapsed": 45, "extra": 2}, "team": {"id": 1}, "player": {"name": "Y"}, "type": "Card", "detail": "Red Card"},
        {"time": {"elapsed": 88, "extra": None}, "team": {"id": 2}, "player": {"name": "Z"}, "type": "Goal", "detail": "Penalty"},
        {"time": {"elapsed": 90, "extra": None}, "team": {"id": 1}, "player": {"name": "Q"}, "type": "Goal", "detail": "Missed Penalty"},
    ],
}


def test_api_football_parse_fixture_and_events():
    nf = api_football.parse_fixture(APIF_FIXTURE, include_events=True)
    assert nf.provider_id == "101" and nf.status == FINISHED and nf.competition.gender == "women"
    assert nf.kickoff_at == datetime(2026, 10, 3, 14, tzinfo=UTC)
    assert (nf.home_score_ft, nf.away_score_ft) == (1, 1)
    own, cancelled, var, red, pen, missed = nf.events
    assert own.detail == "own_goal" and own.team_provider_id == "2" and own.minute == 3
    assert cancelled.is_cancelled and var.detail == "goal_cancelled"
    assert red.extra_minute == 2 and red.detail == "red" and red.period == "1H"
    assert pen.detail == "penalty" and missed.detail == "missed_penalty"


@pytest.mark.parametrize("short,expected", [("NS", SCHEDULED), ("2H", LIVE), ("AET", FINISHED), ("ABD", "abandoned"),
                                            ("PST", "postponed"), ("XYZ", SCHEDULED)])
def test_api_football_status_map(short, expected):
    item = {**APIF_FIXTURE, "fixture": {**APIF_FIXTURE["fixture"], "status": {"short": short}}}
    assert api_football.parse_fixture(item, False).status == expected


SPORTMONKS_FIXTURE = {
    "id": 900, "league_id": 8, "season_id": 2026, "starting_at": "2026-10-03 15:00:00", "starting_at_timestamp": 1791039600,
    "league": {"id": 8, "name": "Mock SM League"}, "state": {"developer_name": "FT"},
    "participants": [{"id": 11, "name": "SM Home", "meta": {"location": "home"}},
                     {"id": 12, "name": "SM Away", "meta": {"location": "away"}}],
    "scores": [{"description": "1ST_HALF", "score": {"goals": 1, "participant": "home"}},
               {"description": "1ST_HALF", "score": {"goals": 0, "participant": "away"}},
               {"description": "2ND_HALF", "score": {"goals": 2, "participant": "home"}},
               {"description": "2ND_HALF", "score": {"goals": 0, "participant": "away"}}],
    "events": [{"id": 1, "type_id": 14, "minute": 2, "participant_id": 11, "player_name": "A"},
               {"id": 2, "type_id": 15, "minute": 60, "participant_id": 12, "player_name": "B"},
               {"id": 3, "type_id": 20, "minute": 45, "extra_minute": 1, "participant_id": 12}],
}


def test_sportmonks_parse():
    nf = sportmonks.parse_fixture(SPORTMONKS_FIXTURE, include_events=True)
    assert nf.home_team.name == "SM Home" and (nf.home_score_ft, nf.away_score_ft) == (2, 0)
    assert nf.kickoff_at == datetime.fromtimestamp(1791039600, UTC)
    assert [e.detail for e in nf.events] == ["normal", "own_goal", "red"]
    assert nf.events[0].provider_event_id == "1" and nf.events[2].extra_minute == 1


def _client(handler, **kw) -> ProviderHttpClient:
    return ProviderHttpClient("mock", "https://mock.test", transport=httpx.MockTransport(handler), per_minute=6000,
                              sleep=lambda s: None, log_calls=False, **kw)


def test_http_client_retries_then_succeeds():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429 if calls["n"] == 1 else 503, headers={"Retry-After": "1"})
        return httpx.Response(200, json={"response": [APIF_FIXTURE]})

    provider = api_football.ApiFootballProvider(client=_client(handler))
    fixtures = provider.fixtures_by_date(date(2026, 10, 3))
    assert calls["n"] == 3 and len(fixtures) == 1 and fixtures[0].events is None


def test_http_client_gives_up_and_raises():
    client = _client(lambda r: httpx.Response(500), max_retries=2)
    with pytest.raises(ProviderError):
        client.get("/x")


def test_http_client_non_retryable_error():
    with pytest.raises(ProviderError):
        _client(lambda r: httpx.Response(403, text="forbidden")).get("/x")


def test_api_football_error_payload_raises():
    provider = api_football.ApiFootballProvider(client=_client(lambda r: httpx.Response(200, json={"errors": {"token": "bad"}, "response": []})))
    with pytest.raises(ProviderError):
        provider.fixtures_by_date(date(2026, 10, 3))


def test_unconfigured_real_provider_raises():
    from app.providers.football.base import ProviderNotConfigured

    with pytest.raises(ProviderNotConfigured):
        api_football.ApiFootballProvider()
    with pytest.raises(ProviderNotConfigured):
        sportmonks.SportmonksProvider()


def test_odds_mapping_is_conservative():
    payload = {"response": [{"update": "2026-10-03T10:00:00+00:00", "bookmakers": [
        {"id": 8, "name": "Mock Book", "bets": [
            {"name": "Goals In First 5 Minutes", "values": [{"value": "No", "odd": "1.12"}, {"value": "Yes", "odd": "6.5"}]},
            {"name": "Match Winner", "values": [{"value": "Home", "odd": "2.1"}]},
            {"name": "1x2 - 5 Minutes", "values": [{"value": "Draw", "odd": "bad"}]},
        ]}]}]}
    odds = ApiFootballOddsProvider(client=_client(lambda r: httpx.Response(200, json=payload))).odds_for_fixture("101")
    assert [(o.market_code, o.decimal_odds) for o in odds] == [("MARKET_A", 1.12)]


def test_demo_provider_is_labelled_and_hides_future_results():
    now = datetime(2026, 11, 1, 12, tzinfo=UTC)
    p = DemoFootballProvider(anchor=now.date(), now=now)
    assert p.is_demo
    views = [p.fixture_with_events(fid) for fid in p.all_fixture_ids()]
    assert all("Demo" in v.competition.name for v in views)
    future = [v for v in views if v.kickoff_at > now]
    assert future and all(v.home_score_ft is None and v.events is None and v.status in (SCHEDULED, "postponed") for v in future)
    past = [v for v in views if v.status == FINISHED]
    assert past and any(v.events for v in past)
