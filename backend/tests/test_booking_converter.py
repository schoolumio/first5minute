"""Booking Code Converter: canonical markets, team matching, the matching engine and the API workflow.

Mocked bookmakers appear ONLY here and in the clearly-labelled demo simulator (BOOKING_CONVERTER_DEMO, never production).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from app.booking_converter import matcher as mt
from app.booking_converter.adapters import registry
from app.booking_converter.adapters.base import BookmakerAdapter, Capabilities
from app.booking_converter.canonical import FT, H1, H2, canonicalize
from app.booking_converter.domain import (
    DecodedBetslip,
    DestEvent,
    DestMarket,
    DestOutcome,
    EventQuery,
    GeneratedBooking,
    Pick,
    Selection,
)
from app.booking_converter.errors import BookingCodeNotFound, IntegrationUnavailable, UpstreamError
from app.booking_converter.store import store
from app.booking_converter.teams import team_similarity
from app.core.config import get_settings
from app.core.database import utcnow
from app.models import BookingConversion
from tests.conftest import login

K = datetime(2030, 1, 1, 15, 0, tzinfo=UTC)


# ======================================================================================================== canonical markets


def c(market, outcome, spec=None, home="Arsenal", away="Chelsea"):
    return canonicalize(market, outcome, spec, home, away)


@pytest.mark.parametrize("market,outcome,spec,expected", [
    ("1X2", "1", None, ("1X2", FT, None, "HOME")),
    ("Match Result", "Arsenal", None, ("1X2", FT, None, "HOME")),
    ("Full Time Result", "Draw", None, ("1X2", FT, None, "DRAW")),
    ("1X2", "2", None, ("1X2", FT, None, "AWAY")),
    ("1st Half - 1X2", "X", None, ("1X2", H1, None, "DRAW")),
    ("Half Time Result", "Chelsea", None, ("1X2", H1, None, "AWAY")),
    ("Over/Under", "Over 2.5", "2.5", ("OVER_UNDER", FT, Decimal("2.5"), "OVER")),
    ("Over/Under", "Over 2.5", None, ("OVER_UNDER", FT, Decimal("2.5"), "OVER")),
    ("Total Goals", "Under", "total=3.5", ("OVER_UNDER", FT, Decimal("3.5"), "UNDER")),
    ("Goals Over/Under 1.5", "Over", None, ("OVER_UNDER", FT, Decimal("1.5"), "OVER")),
    ("2nd Half - Over/Under", "Under 0.5", None, ("OVER_UNDER", H2, Decimal("0.5"), "UNDER")),
    ("1st Half Over/Under", "O 0.5", None, ("OVER_UNDER", H1, Decimal("0.5"), "OVER")),
    ("GG/NG", "GG", None, ("BTTS", FT, None, "YES")),
    ("Both Teams To Score", "No", None, ("BTTS", FT, None, "NO")),
    ("1st Half - Both Teams To Score", "Yes", None, ("BTTS", H1, None, "YES")),
    ("Double Chance", "1X", None, ("DOUBLE_CHANCE", FT, None, "1X")),
    ("Double Chance", "Arsenal or Draw", None, ("DOUBLE_CHANCE", FT, None, "1X")),
    ("Double Chance", "Draw/Chelsea", None, ("DOUBLE_CHANCE", FT, None, "X2")),
    ("Double Chance", "Home or Away", None, ("DOUBLE_CHANCE", FT, None, "12")),
    ("Draw No Bet", "Arsenal", None, ("DRAW_NO_BET", FT, None, "HOME")),
    ("Draw No Bet", "2", None, ("DRAW_NO_BET", FT, None, "AWAY")),
    ("Half Time/Full Time", "1/2", None, ("HT_FT", FT, None, "1/2")),
    ("HT/FT", "Draw/Arsenal", None, ("HT_FT", FT, None, "X/1")),
])
def test_supported_markets_reduce_to_one_canonical_form(market, outcome, spec, expected):
    r = c(market, outcome, spec)
    assert r.canon is not None, r.reason
    assert (r.canon.market, r.canon.period, r.canon.line, r.canon.outcome) == expected


@pytest.mark.parametrize("market,outcome,spec", [
    ("Total Corners Over/Under", "Over 9.5", None),
    ("Asian Handicap", "Arsenal -1", None),
    ("Handicap 1X2", "1", None),
    ("Total Goals Odd/Even", "Odd", None),
    ("Match Result and Both Teams To Score", "Home & Yes", None),
    ("1X2 & Over/Under 2.5", "1 & Over", None),
    ("Home Team Over/Under", "Over 1.5", None),
    ("Over/Under", "Over 2.5/3", None),
    ("Over/Under", "Over", "2.5/3"),
    ("Over/Under", "Over 2.5", "3.5"),            # conflicting lines: never guess
    ("Over/Under", "Over", None),                 # no line at all
    ("Correct Score", "2:1", None),
    ("To Score Anytime", "Saka", None),
    ("Cards Over/Under", "Over 3.5", None),
    ("Mystery Market", "Yes", None),
    ("", "Yes", None),
])
def test_unsupported_or_ambiguous_markets_are_never_approximated(market, outcome, spec):
    r = c(market, outcome, spec)
    assert r.canon is None and r.reason


def test_first_half_is_never_confused_with_full_time_and_lines_never_blur():
    ft = c("1X2", "1").canon
    h1 = c("1st Half - 1X2", "1").canon
    assert ft != h1 and ft.market_key() != h1.market_key()
    assert c("Over/Under", "Over 2.5").canon != c("Over/Under", "Over 3.5").canon
    assert c("Over/Under", "Over 2.5").canon != c("Over/Under", "Under 2.5").canon
    assert c("Over/Under", "Over 2.5").canon != c("1st Half Over/Under", "Over 2.5").canon
    assert c("GG/NG", "GG").canon == c("Both Teams To Score", "Yes").canon
    assert c("GG/NG", "GG").canon != c("GG/NG", "NG").canon


# ============================================================================================================ team names


@pytest.mark.parametrize("a,b", [
    ("Man Utd", "Manchester United"), ("Manchester Utd", "Manchester United"), ("Spurs", "Tottenham Hotspur"),
    ("Bayern München", "Bayern Munich"), ("Atlético Madrid", "Atletico Madrid"), ("FC Barcelona", "Barcelona"),
    ("Kingsport Women", "Kingsport W"), ("AC Milan", "Milan"), ("Inter", "Inter Milan"), ("Paris SG", "PSG"),
    ("Ashford Rovers", "Ashford Rovers FC"),
])
def test_same_club_different_spelling_matches(a, b):
    assert team_similarity(a, b) >= 0.9


@pytest.mark.parametrize("a,b", [
    ("Arsenal", "Arsenal Women"), ("Arsenal", "Arsenal U21"), ("Real Madrid", "Real Betis"), ("AC Milan", "Inter Milan"),
    ("Manchester City", "Manchester United"), ("Sporting Gijon", "Sporting Lisbon"), ("Barcelona", "Barcelona B"),
    ("Chelsea", "Chelsea Women"), ("", "Arsenal"),
])
def test_different_clubs_never_match(a, b):
    assert team_similarity(a, b) < 0.9


def test_partial_names_only_count_as_weak_evidence():
    assert mt.SUBSET_MIN <= team_similarity("Madrid", "Real Madrid") < mt.TEAM_MATCH_MIN


# ==================================================================================================== event + market matching


def ev(eid, home, away, start=K, markets=None, **kw):
    return DestEvent(id=eid, home_team=home, away_team=away, start_time=start, markets=markets or [], **kw)


def sel(home="Arsenal", away="Chelsea", market="1X2", outcome="1", odds="2.00", start=K, spec=None, **kw):
    return Selection(home_team=home, away_team=away, market_name=market, outcome=outcome, odds=Decimal(odds) if odds else None,
                     start_time=start, specifier=spec, **kw)


def mk(mid, name, outs, spec=None):
    return DestMarket(id=mid, name=name, specifier=spec, outcomes=[DestOutcome(i, n, Decimal(o) if o else None, a) for i, n, o, a in outs])


def test_event_matching_rules():
    s = sel()
    good = ev("e1", "Arsenal FC", "Chelsea FC")
    assert mt.match_event(s, [good]).confidence == "high"
    assert mt.match_event(s, [ev("e1", "Arsenal", "Chelsea", K + timedelta(minutes=10))]).confidence == "medium"
    assert mt.match_event(s, [ev("e1", "Arsenal", "Chelsea", K + timedelta(hours=2))]).reason == "time_mismatch"
    assert mt.match_event(s, [ev("e1", "Chelsea", "Arsenal")]).reason == "teams_reversed"
    assert mt.match_event(s, [ev("e1", "Liverpool", "Everton")]).reason == "no_fixture"
    assert mt.match_event(s, []).reason == "no_fixture"
    assert mt.match_event(sel(start=None), [good]).reason == "start_time_missing"
    assert mt.match_event(s, [ev("e1", "Arsenal Women", "Chelsea Women")]).reason == "no_fixture"
    assert mt.match_event(s, [ev("e1", "Arsenal", "Chelsea", sport="basketball")]).reason == "no_fixture"
    assert mt.match_event(s, [ev("e1", "Arsenal", "Chelsea"), ev("e2", "Arsenal", "Chelsea", K + timedelta(minutes=3))]).reason \
        == "ambiguous_fixture"
    # one real match and an unrelated one: no ambiguity
    assert mt.match_event(s, [good, ev("e2", "Liverpool", "Everton")]).event.id == "e1"


def test_partial_team_name_needs_exact_opponent_and_close_kickoff():
    s = sel("Madrid", "Girona", start=K)
    assert mt.match_event(s, [ev("e1", "Real Madrid", "Girona", K)]).confidence == "medium"
    assert mt.match_event(s, [ev("e1", "Real Madrid", "Girona", K + timedelta(minutes=20))]).reason == "time_mismatch"


FULL_EVENT = ev("e1", "Arsenal", "Chelsea", K, [
    mk("m1", "Match Result", [("o1", "Arsenal", "2.00", True), ("o2", "Draw", "3.40", True), ("o3", "Chelsea", "3.80", True)]),
    mk("m2", "Total Goals", [("o4", "Over", "1.90", True), ("o5", "Under", "1.95", True)], spec="total=2.5"),
    mk("m3", "Both Teams To Score", [("o6", "Yes", "1.70", True), ("o7", "No", "2.10", False)]),
])
NOW = datetime(2029, 12, 1, tzinfo=UTC)


def test_selection_mapping_exactness_and_statuses():
    r = mt.map_selection(0, sel(), FULL_EVENT, "high", NOW)
    assert r.status == mt.MATCHED and r.pick.outcome_id == "o1" and r.odds_change == "same"
    r = mt.map_selection(0, sel(odds="2.20"), FULL_EVENT, "high", NOW)
    assert r.status == mt.ODDS_CHANGED and r.odds_change == "down" and r.matched
    r = mt.map_selection(0, sel(odds="1.80"), FULL_EVENT, "high", NOW)
    assert r.status == mt.ODDS_CHANGED and r.odds_change == "up"
    assert mt.map_selection(0, sel(market="Over/Under", outcome="Over 2.5", odds="1.90"), FULL_EVENT, "high", NOW).pick.outcome_id == "o4"
    assert mt.map_selection(0, sel(market="Over/Under", outcome="Under 2.5", odds="1.95"), FULL_EVENT, "high", NOW).pick.outcome_id == "o5"
    # exact line only: 3.5 is not offered, so Over 3.5 is UNAVAILABLE and never silently becomes Over 2.5
    r = mt.map_selection(0, sel(market="Over/Under", outcome="Over 3.5"), FULL_EVENT, "high", NOW)
    assert r.status == mt.UNAVAILABLE and r.reason_code == "line_unavailable" and r.pick is None
    # first-half market is not the full-time one
    r = mt.map_selection(0, sel(market="1st Half - 1X2", outcome="1"), FULL_EVENT, "high", NOW)
    assert r.reason_code == "market_unavailable" and r.pick is None
    # the other side of a market never substitutes
    assert mt.map_selection(0, sel(outcome="2", odds="3.80"), FULL_EVENT, "high", NOW).pick.outcome_id == "o3"
    r = mt.map_selection(0, sel(market="Double Chance", outcome="1X"), FULL_EVENT, "high", NOW)
    assert r.reason_code == "market_unavailable"
    r = mt.map_selection(0, sel(market="GG/NG", outcome="NG"), FULL_EVENT, "high", NOW)
    assert r.status == mt.UNAVAILABLE and r.reason_code == "suspended"
    r = mt.map_selection(0, sel(market="Total Corners", outcome="Over 9.5"), FULL_EVENT, "high", NOW)
    assert r.status == mt.UNMATCHED and r.reason_code == "market_unsupported"
    started = ev("e9", "Arsenal", "Chelsea", NOW - timedelta(hours=1), FULL_EVENT.markets)
    assert mt.map_selection(0, sel(), started, "high", NOW).reason_code == "event_started"
    dup = ev("e9", "Arsenal", "Chelsea", K, [mk("a", "Match Result", [("x1", "Arsenal", "2.0", True)]),
                                             mk("b", "1X2", [("x2", "1", "2.1", True)])])
    assert mt.map_selection(0, sel(), dup, "high", NOW).reason_code == "ambiguous_market"


def test_match_betslip_returns_one_result_per_selection_and_isolates_failures():
    calls = []

    def find(q: EventQuery):
        calls.append(q.home_team)
        if q.home_team == "Boom FC":
            raise UpstreamError()
        return [FULL_EVENT]

    sels = [sel(), sel(market="GG/NG", outcome="GG", odds="1.70"), sel("Boom FC", "Other", ), sel("Nobody", "Missing"),
            sel(start=None), Selection("A", "B", "1X2", "1", sport="basketball", start_time=K)]
    res = mt.match_betslip(sels, find, now=NOW)
    assert [r.index for r in res] == list(range(6))
    assert [r.status for r in res] == [mt.MATCHED, mt.MATCHED, mt.UNAVAILABLE, mt.UNMATCHED, mt.UNMATCHED, mt.UNMATCHED]
    assert res[2].reason_code == "lookup_failed" and res[3].reason_code == "no_fixture"
    assert res[4].reason_code == "start_time_missing" and res[5].reason_code == "sport_unsupported"
    assert calls.count("Arsenal") == 1            # selections of the same fixture share one lookup


def test_integration_unavailable_stops_the_whole_conversion():
    def find(q):
        raise IntegrationUnavailable()

    with pytest.raises(IntegrationUnavailable):
        mt.match_betslip([sel()], find, now=NOW)


def test_matching_deadline_marks_remaining_selections_instead_of_hanging():
    res = mt.match_betslip([sel(), sel("A", "B")], lambda q: [FULL_EVENT], deadline_seconds=-1, now=NOW)
    assert {r.reason_code for r in res} == {"lookup_timeout"} and all(r.status == mt.UNAVAILABLE for r in res)


# ========================================================================================================= API: fixtures


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    store.reset()
    registry.clear_extra_adapters()
    s = get_settings()
    monkeypatch.setattr(s, "booking_converter_enabled", True)
    monkeypatch.setattr(s, "booking_converter_demo", False)
    yield
    registry.clear_extra_adapters()
    store.reset()


@pytest.fixture
def demo(monkeypatch):
    monkeypatch.setattr(get_settings(), "booking_converter_demo", True)


@pytest.fixture
def signed_in(client, user_factory):
    user = user_factory(email="conv@example.com")
    login(client, "conv@example.com")
    return user


B = "/api/v1/booking-converter"


def run(client, code, src, dst, proceed=None):
    d = client.post(f"{B}/decode", json={"code": code, "source": src, "destination": dst})
    assert d.status_code == 200, d.text
    cid = d.json()["id"]
    m = client.post(f"{B}/{cid}/match")
    assert m.status_code == 200, m.text
    return d.json(), m.json()


def by_index(view):
    return {s["index"]: s for s in view["selections"]}


# ====================================================================================================== API: registry/access


def test_requires_sign_in_and_verified_email(client, user_factory):
    assert client.get(f"{B}/bookmakers").status_code == 401
    user_factory(email="unverified@example.com", verified=False)
    login(client, "unverified@example.com")
    assert client.get(f"{B}/bookmakers").status_code == 403


def test_the_seven_bookmakers_are_listed_but_not_connected_and_demo_is_hidden_by_default(client, signed_in):
    data = client.get(f"{B}/bookmakers").json()
    assert data["enabled"] is True
    names = {b["code"]: b for b in data["bookmakers"]}
    assert set(names) == {"bet9ja", "sportybet", "betking", "msport", "1xbet", "betway", "betpawa"}
    for b in names.values():
        assert b["available"] is False and not b["can_decode"] and not b["can_generate"] and b["message"]
        assert "setup" not in b                                   # setup details are for administrators only


def test_admin_sees_what_is_needed_to_connect_a_bookmaker(client, user_factory):
    user_factory(email="boss@example.com", role="admin")
    login(client, "boss@example.com")
    b9 = next(b for b in client.get(f"{B}/bookmakers").json()["bookmakers"] if b["code"] == "bet9ja")
    assert "partner" in b9["setup"] and "BET9JA" in b9["setup"]


def test_demo_bookmakers_appear_only_when_enabled(client, signed_in, demo):
    codes = {b["code"]: b for b in client.get(f"{B}/bookmakers").json()["bookmakers"]}
    assert {"demo_alpha", "demo_beta", "demo_gamma"} <= set(codes) and all(codes[k]["is_demo"] for k in ("demo_alpha", "demo_beta"))
    assert codes["demo_alpha"]["can_generate"] and not codes["demo_gamma"]["can_generate"]


def test_demo_simulator_is_refused_in_production(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "booking_converter_demo", True)
    monkeypatch.setattr(s, "environment", "production")
    with pytest.raises(RuntimeError, match="BOOKING_CONVERTER_DEMO"):
        s.validate_production()
    assert "demo_alpha" not in registry.all_adapters()           # never registered in production, even if the flag leaks


def test_feature_switch_and_self_exclusion(client, signed_in, db, monkeypatch, demo):
    monkeypatch.setattr(get_settings(), "booking_converter_enabled", False)
    assert client.post(f"{B}/decode", json={"code": "DEMOALL", "source": "demo_alpha", "destination": "demo_beta"}).status_code == 503
    monkeypatch.setattr(get_settings(), "booking_converter_enabled", True)
    signed_in.rg_self_excluded_until = utcnow() + timedelta(days=3)
    db.commit()
    r = client.post(f"{B}/decode", json={"code": "DEMOALL", "source": "demo_alpha", "destination": "demo_beta"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "self_excluded"


# ============================================================================================ scenarios from the brief (1-9, 12)


def test_1_valid_code_all_selections_matched_and_a_code_is_generated(client, signed_in, demo):
    d, m = run(client, "demoall", "demo_alpha", "demo_beta")        # lower case and spacing are normalised
    assert d["state"] == "decoded" and d["counts"]["original"] == 3 and all(s["status"] == "pending" for s in d["selections"])
    assert d["is_demo"] is True
    assert m["state"] == "matched"
    assert m["counts"] == {"original": 3, "matched": 3, "unmatched": 0, "unavailable": 0, "odds_changed": 1}
    s = by_index(m)
    assert s[0]["status"] == "matched" and s[0]["odds"]["change"] == "same"
    assert s[0]["destination"]["home_team"] == "Ashford Rovers FC" and s[0]["destination"]["market_name"] == "Match Result"
    # Over 2.5 stays Over 2.5 even though the destination names the market differently
    assert s[1]["interpreted_as"].endswith("OVER") and "2.5" in s[1]["interpreted_as"]
    assert s[1]["destination"]["market_name"] == "Total Goals" and s[1]["destination"]["outcome"] == "Over"
    assert s[1]["status"] == "odds_changed" and s[1]["odds"] == {"original": "1.90", "destination": "1.85", "change": "down"}
    assert s[2]["destination"]["outcome"] == "Yes" and s[2]["confidence"] == "medium"      # kickoff differs by 10 minutes
    assert m["needs_decision"] is False and m["betslip_text"].startswith("Demo Book Beta betslip (3 selections)")
    g = client.post(f"{B}/{m['id']}/generate", json={})
    assert g.status_code == 200
    booking = g.json()["booking"]
    assert booking["status"] == "generated" and booking["code"].startswith("DEMO-") and booking["is_demo"] is True
    assert g.json()["state"] == "generated"


def test_2_invalid_codes(client, signed_in, demo):
    assert client.post(f"{B}/decode", json={"code": "ab", "source": "demo_alpha", "destination": "demo_beta"}).status_code == 422
    bad = client.post(f"{B}/decode", json={"code": "BAD CODE!!", "source": "demo_alpha", "destination": "demo_beta"})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "invalid_code"
    nf = client.post(f"{B}/decode", json={"code": "DEMOEXPIRED", "source": "demo_alpha", "destination": "demo_beta"})
    assert nf.status_code == 404 and nf.json()["detail"]["code"] == "code_not_found"
    inj = client.post(f"{B}/decode", json={"code": "ABCD1234", "source": "demo_alpha; drop table", "destination": "demo_beta"})
    assert inj.status_code == 422


def test_3_and_4_unsupported_or_unconnected_bookmakers(client, signed_in, demo, db):
    r = client.post(f"{B}/decode", json={"code": "ABC123", "source": "nosuchbook", "destination": "demo_beta"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "unsupported_bookmaker"
    r = client.post(f"{B}/decode", json={"code": "ABC123", "source": "demo_alpha", "destination": "nosuchbook"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "unsupported_bookmaker"
    r = client.post(f"{B}/decode", json={"code": "ABC123", "source": "bet9ja", "destination": "demo_beta"})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "integration_unavailable"
    assert "Bet9ja" in r.json()["detail"]["message"] and "no official integration" in r.json()["detail"]["message"]
    r = client.post(f"{B}/decode", json={"code": "DEMOALL", "source": "demo_alpha", "destination": "sportybet"})
    assert r.status_code == 503 and "SportyBet" in r.json()["detail"]["message"]
    same = client.post(f"{B}/decode", json={"code": "DEMOALL", "source": "demo_alpha", "destination": "demo_alpha"})
    assert same.status_code == 422 and same.json()["detail"]["code"] == "same_bookmaker"
    rows = db.scalars(select(BookingConversion).where(BookingConversion.status == "failed")).all()
    assert {r.error_code for r in rows} >= {"unsupported_bookmaker", "integration_unavailable"}


def test_5_7_8_some_selections_unavailable_unmatched_or_unmappable_nothing_is_dropped(client, signed_in, demo):
    d, m = run(client, "DEMOPART", "demo_alpha", "demo_beta")
    assert m["counts"] == {"original": 5, "matched": 1, "unmatched": 1, "unavailable": 3, "odds_changed": 0}
    s = by_index(m)
    assert len(m["selections"]) == 5                                    # never silently removed
    assert s[0]["status"] == "matched"
    assert s[1]["status"] == "unmatched" and s[1]["reason_code"] == "no_fixture" and "No matching fixture" in s[1]["reason"]
    assert s[2]["status"] == "unavailable" and s[2]["reason_code"] == "market_unavailable"   # 2nd-half total: not offered
    assert s[3]["status"] == "unavailable" and s[3]["reason_code"] == "suspended"
    assert s[4]["status"] == "unavailable" and s[4]["reason_code"] == "line_unavailable"     # Under 3.5 is not Under 2.5
    assert all(s[i]["destination"] is None or s[i]["odds"]["destination"] is None for i in (2, 3, 4))
    assert m["needs_decision"] is True and m["totals"]["destination_covers_all"] is False
    # the user must decide: without confirmation no code is generated
    blocked = client.post(f"{B}/{m['id']}/generate", json={})
    assert blocked.status_code == 409 and blocked.json()["detail"]["code"] == "needs_decision"
    ok = client.post(f"{B}/{m['id']}/generate", json={"proceed_with_partial": True})
    assert ok.status_code == 200 and ok.json()["booking"]["status"] == "generated"
    assert len(ok.json()["selections"]) == 5 and ok.json()["counts"]["matched"] == 1


def test_8_unsupported_market_is_reported_with_a_reason(client, signed_in, demo):
    _, m = run(client, "DEMOMARKET", "demo_alpha", "demo_beta")
    s = by_index(m)
    assert s[1]["status"] == "unmatched" and s[1]["reason_code"] == "market_unsupported" and "not supported" in s[1]["reason"]
    assert m["counts"]["matched"] == 1


def test_womens_fixture_never_matches_the_mens(client, signed_in, demo):
    _, m = run(client, "DEMOWOMEN", "demo_alpha", "demo_beta")
    s = by_index(m)[0]
    assert s["status"] == "matched" and s["destination"]["home_team"] == "Kingsport W"
    assert s["source"]["outcome"] == "2" and s["destination"]["outcome"] == "Lakeside W"


def test_9_destination_code_generation_failure_is_reported_honestly(client, signed_in, demo):
    _, m = run(client, "DEMOGENFAIL", "demo_alpha", "demo_beta")
    assert m["counts"]["matched"] == 2
    g = client.post(f"{B}/{m['id']}/generate", json={})
    assert g.status_code == 200
    body = g.json()
    assert body["booking"]["status"] == "failed" and body["booking"]["code"] is None and body["booking"]["message"]
    assert body["state"] == "matched" and len(body["selections"]) == 2          # the recreated slip is still available
    for _ in range(2):                                                        # retries are allowed, but capped
        assert client.post(f"{B}/{m['id']}/generate", json={}).json()["booking"]["status"] == "failed"
    capped = client.post(f"{B}/{m['id']}/generate", json={})
    assert capped.status_code == 502


class FakeBook(BookmakerAdapter):
    """Mock integration used only by tests."""

    capabilities = Capabilities(True, True, True)

    def __init__(self, code, name, events=None, selections=None, gen=None):
        self.code, self.name = code, name
        self._events, self._sels, self._gen = events or [], selections or [], gen
        self.created: list[list[Pick]] = []
        self.finds = 0

    def available(self):
        return True

    def decode(self, code):
        if code == "GONE1234":
            raise BookingCodeNotFound()
        return DecodedBetslip(self.code, self._sels)

    def find_events(self, query):
        self.finds += 1
        return self._events

    def create_booking(self, picks):
        self.created.append(picks)
        if self._gen is None:
            return GeneratedBooking(code="REAL12345")
        return self._gen(picks)


def fake_pair(**dest_kw):
    src = FakeBook("fake_src", "Fake Source", selections=[sel(), sel(market="GG/NG", outcome="GG", odds="1.70",
                                                              start=datetime.now(UTC) + timedelta(days=2))])
    start = datetime.now(UTC) + timedelta(days=2)
    event = ev("e1", "Arsenal", "Chelsea", start, FULL_EVENT.markets)
    src._sels = [sel(start=start), sel(market="GG/NG", outcome="GG", odds="1.70", start=start)]
    dst = FakeBook("fake_dst", "Fake Destination", events=[event], **dest_kw)
    registry.register_adapter(src)
    registry.register_adapter(dst)
    return src, dst


def test_a_genuine_code_is_only_shown_when_the_bookmaker_returned_one(client, signed_in):
    _, dst = fake_pair()
    _, m = run(client, "REALCODE1", "fake_src", "fake_dst")
    assert m["counts"]["matched"] == 2 and m["is_demo"] is False
    g = client.post(f"{B}/{m['id']}/generate", json={}).json()
    assert g["booking"] == {"status": "generated", "code": "REAL12345", "share_url": None, "is_demo": False, "message": None}
    assert len(dst.created) == 1 and [p.outcome_id for p in dst.created[0]] == ["o1", "o6"]


@pytest.mark.parametrize("bad", ["", None, "no spaces allowed", "x" * 80, "ab"])
def test_invalid_codes_from_the_destination_are_treated_as_failures_never_displayed(client, signed_in, bad):
    fake_pair(gen=lambda picks: GeneratedBooking(code=bad))
    _, m = run(client, "REALCODE1", "fake_src", "fake_dst")
    g = client.post(f"{B}/{m['id']}/generate", json={}).json()
    assert g["booking"]["status"] == "failed" and g["booking"]["code"] is None and "valid booking code" in g["booking"]["message"]


def test_adapter_errors_become_clear_failure_states_without_leaking_details(client, signed_in):
    def boom(picks):
        raise RuntimeError("secret-token=abc123 connection string")

    fake_pair(gen=boom)
    _, m = run(client, "REALCODE1", "fake_src", "fake_dst")
    g = client.post(f"{B}/{m['id']}/generate", json={})
    assert g.status_code == 200 and g.json()["booking"]["status"] == "failed"
    assert "abc123" not in g.text and "secret" not in g.text


def test_unknown_code_and_unexpected_decode_errors(client, signed_in):
    fake_pair()
    assert client.post(f"{B}/decode", json={"code": "GONE1234", "source": "fake_src", "destination": "fake_dst"}).status_code == 404

    class Exploding(FakeBook):
        def decode(self, code):
            raise ValueError("internal detail that must not leak")

    registry.register_adapter(Exploding("fake_boom", "Fake Boom"))
    r = client.post(f"{B}/decode", json={"code": "ABCD1234", "source": "fake_boom", "destination": "fake_dst"})
    assert r.status_code == 502 and "internal detail" not in r.text


def test_destination_lookup_failures_degrade_per_fixture(client, signed_in):
    src, dst = fake_pair()

    def failing(q):
        raise UpstreamError()

    dst.find_events = failing
    _, m = run(client, "REALCODE1", "fake_src", "fake_dst")
    assert m["counts"]["matched"] == 0 and {s["reason_code"] for s in m["selections"]} == {"lookup_failed"}
    nothing = client.post(f"{B}/{m['id']}/generate", json={"proceed_with_partial": True})
    assert nothing.status_code == 422 and nothing.json()["detail"]["code"] == "nothing_to_convert"


def test_manual_continuation_when_destination_cannot_create_codes(client, signed_in, demo):
    _, m = run(client, "DEMOALL", "demo_alpha", "demo_gamma")
    g = client.post(f"{B}/{m['id']}/generate", json={}).json()
    assert g["booking"]["status"] == "manual" and g["booking"]["code"] is None and "recreated" in g["booking"]["message"]
    assert "1." in g["betslip_text"] and "Demo Book Gamma" in g["betslip_text"] and g["destination"]["can_generate"] is False


def test_12_duplicate_requests_are_deduplicated_and_never_generate_two_codes(client, signed_in, demo, monkeypatch):
    first = client.post(f"{B}/decode", json={"code": "DEMOALL", "source": "demo_alpha", "destination": "demo_beta"}).json()
    again = client.post(f"{B}/decode", json={"code": "demoall", "source": "demo_alpha", "destination": "demo_beta"}).json()
    assert again["id"] == first["id"] and again["deduplicated"] is True and first["deduplicated"] is False
    # an identical request arriving while the first is still running is refused
    from app.booking_converter.service import hashlib as _h  # noqa: F401  (same hashing as the service)

    key = _h.sha256(f"{signed_in.id}|demo_alpha|demo_beta|DEMOPART".encode()).hexdigest()[:32]
    assert store.claim(f"lock:{key}", 30)
    busy = client.post(f"{B}/decode", json={"code": "DEMOPART", "source": "demo_alpha", "destination": "demo_beta"})
    assert busy.status_code == 409 and busy.json()["detail"]["code"] == "conversion_in_progress"
    store.release(f"lock:{key}")
    # matching twice is idempotent, generating twice returns the same single code
    m1 = client.post(f"{B}/{first['id']}/match").json()
    m2 = client.post(f"{B}/{first['id']}/match").json()
    assert m1["selections"] == m2["selections"]
    g1 = client.post(f"{B}/{first['id']}/generate", json={}).json()
    g2 = client.post(f"{B}/{first['id']}/generate", json={}).json()
    assert g1["booking"]["code"] == g2["booking"]["code"] and g1["booking"]["status"] == "generated"


def test_generation_is_called_exactly_once_for_repeated_requests(client, signed_in):
    _, dst = fake_pair()
    _, m = run(client, "REALCODE1", "fake_src", "fake_dst")
    for _ in range(3):
        assert client.post(f"{B}/{m['id']}/generate", json={}).json()["booking"]["code"] == "REAL12345"
    assert len(dst.created) == 1


def test_steps_must_follow_the_order(client, signed_in, demo):
    d = client.post(f"{B}/decode", json={"code": "DEMOALL", "source": "demo_alpha", "destination": "demo_beta"}).json()
    early = client.post(f"{B}/{d['id']}/generate", json={})
    assert early.status_code == 409 and early.json()["detail"]["code"] == "wrong_state"
    assert client.post(f"{B}/doesnotexist/match").status_code == 404


def test_a_conversion_belongs_to_its_owner(client, signed_in, demo, user_factory):
    d = client.post(f"{B}/decode", json={"code": "DEMOALL", "source": "demo_alpha", "destination": "demo_beta"}).json()
    client.cookies.clear()
    user_factory(email="other@example.com")
    login(client, "other@example.com")
    assert client.post(f"{B}/{d['id']}/match").status_code == 404
    assert client.post(f"{B}/{d['id']}/generate", json={}).status_code == 404


def test_rate_limit(client, signed_in, demo, monkeypatch):
    monkeypatch.setattr(get_settings(), "rate_limit_enabled", True)
    monkeypatch.setattr(get_settings(), "booking_converter_per_minute", 2)
    codes = ["DEMOALL", "DEMOPART", "DEMOMARKET"]
    statuses = [client.post(f"{B}/decode", json={"code": c_, "source": "demo_alpha", "destination": "demo_beta"}).status_code for c_ in codes]
    assert statuses == [200, 200, 429]


def test_history_keeps_counts_not_codes(client, signed_in, demo, db):
    _, m = run(client, "DEMOPART", "demo_alpha", "demo_beta")
    g = client.post(f"{B}/{m['id']}/generate", json={"proceed_with_partial": True}).json()
    h = client.get(f"{B}/history")
    assert h.status_code == 200
    item = h.json()["items"][0]
    assert item["source"] == "Demo Book Alpha" and item["selections"] == 5 and item["matched"] == 1 and item["code_generated"] is True
    assert item["status"] == "generated" and item["is_demo"] is True
    blob = h.text + json.dumps([{c.name: str(getattr(r, c.name)) for c in BookingConversion.__table__.columns}
                                for r in db.scalars(select(BookingConversion))])
    assert "DEMOPART" not in blob and g["booking"]["code"] not in blob
    assert client.get(f"{B}/history").status_code == 200


def test_logs_do_not_contain_codes(client, signed_in, demo, capsys):
    run(client, "DEMOALL", "demo_alpha", "demo_beta")
    out = capsys.readouterr().out
    assert "DEMOALL" not in out and "conv@example.com" not in out


# ===================================================================== ticket flow: scanner picks -> bookmaker -> booking code


from app.core.database import utcnow as _now  # noqa: E402
from app.engine.settlement import Rule  # noqa: E402
from app.ingestion.service import Ingestor  # noqa: E402
from app.models import Fixture, Prediction  # noqa: E402
from app.scanner.service import run_scan  # noqa: E402
from tests import factories as fx  # noqa: E402


@pytest.fixture
def pro_user(client, user_factory):
    user = user_factory(email="pro@example.com", plan="pro")
    login(client, "pro@example.com")
    return user


@pytest.fixture
def scanner_world(db):
    """League history plus upcoming fixtures with current predictions, as the scanner produces them."""
    now = _now()
    ing = Ingestor(db, "mock", False, Rule())
    for nf in fx.season_history(now - timedelta(days=60), n_teams=6, rounds=14, early_goal_every=50):
        ing.ingest_fixture(nf)
    ing.ingest_fixture(fx.upcoming("u1", 1, 2, now + timedelta(hours=20)))
    ing.ingest_fixture(fx.upcoming("u2", 3, 4, now + timedelta(hours=22)))
    ing.ingest_fixture(fx.upcoming("u3", 5, 6, now + timedelta(hours=26)))
    ing.ingest_fixture(fx.upcoming("u4", 7, 8, now + timedelta(hours=28)))          # teams with no history -> excluded
    db.commit()
    run_scan(db, now=now, notify=False)
    db.commit()
    fixtures = {x.provider_id: x for x in db.scalars(select(Fixture).where(Fixture.provider_id.in_(["u1", "u2", "u3", "u4"])))}
    return fixtures


def pid(db, fixture, market="MARKET_A"):
    return db.scalar(select(Prediction.id).where(Prediction.fixture_id == fixture.id, Prediction.market_code == market,
                                                 Prediction.is_current.is_(True)))


def tk(client, bookie, ids):
    return client.post(f"{B}/ticket", json={"destination": bookie, "prediction_ids": ids})


def test_preview_returns_the_model_analysis_for_each_pick(client, pro_user, scanner_world, db):
    ids = [pid(db, scanner_world["u1"]), pid(db, scanner_world["u2"], "MARKET_B")]
    items = client.post(f"{B}/ticket/preview", json={"prediction_ids": ids}).json()["items"]
    a, b = items
    assert a["available"] is True and a["market_label"] == "No goal in the first 5 minutes" and 0.5 < a["probability"] < 1
    assert a["fair_odds"] == round(1 / a["probability"], 3) and a["category"] and a["data_quality"] and a["model"]
    assert a["calibration_status"] and a["fixture"]["home_team"] == "Mock Team 1"
    assert b["market_label"] == "Level at 5 minutes"
    gone = client.post(f"{B}/ticket/preview", json={"prediction_ids": [999999]}).json()["items"][0]
    assert gone["available"] is False and "no longer exists" in gone["reason"]


def test_scanner_ticket_converts_five_minute_picks_and_shows_analysis_with_bookmaker_odds(client, pro_user, scanner_world, db, demo):
    ids = [pid(db, scanner_world["u1"]), pid(db, scanner_world["u2"], "MARKET_B"), pid(db, scanner_world["u3"])]
    r = tk(client, "demo_alpha", ids)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["source"]["name"] == "First5Minute ticket" and d["counts"]["original"] == 3 and d["state"] == "decoded"
    assert all(s["analysis"]["probability"] for s in d["selections"])                      # analysis is there from the start
    m = client.post(f"{B}/{d['id']}/match").json()
    assert m["counts"]["matched"] == 3, [s["reason_code"] for s in m["selections"]]
    s = by_index(m)
    assert s[0]["interpreted_as"] == "Total goals over/under (First 5 minutes) 0.5: UNDER"
    assert s[0]["destination"]["market_name"] == "First 5 Minutes - Over/Under" and s[0]["destination"]["outcome"] == "Under 0.5"
    assert s[1]["interpreted_as"] == "1X2 (First 5 minutes): DRAW" and s[1]["destination"]["outcome"] == "X"
    a0 = s[0]["analysis"]
    assert a0["bookmaker_odds"] == s[0]["destination"]["odds"]
    assert a0["edge"] == round(a0["probability"] * float(a0["bookmaker_odds"]) - 1, 4)     # estimate x price - 1, a statistic not advice
    assert any("first 5 minutes" in w.lower() for w in m["warnings"]) and any("not guarantees" in w for w in m["warnings"])
    g = client.post(f"{B}/{d['id']}/generate", json={}).json()
    assert g["booking"]["status"] == "generated" and g["booking"]["code"].startswith("DEMO-") and g["booking"]["is_demo"] is True
    assert client.get(f"{B}/history").json()["items"][0]["source"] == "First5Minute ticket"


def test_five_minute_market_missing_at_the_bookmaker_is_reported_not_substituted(client, pro_user, scanner_world, db, demo):
    # try every fixture at demo_beta: whatever its deterministic gaps, no result may be a different market or fixture
    ids = [pid(db, scanner_world[k], m) for k in ("u1", "u2", "u3") for m in ("MARKET_A",)]
    d = tk(client, "demo_beta", ids).json()
    m = client.post(f"{B}/{d['id']}/match").json()
    for sel_ in m["selections"]:
        if sel_["status"] in ("matched", "odds_changed"):
            assert sel_["destination"]["market_name"] == "5 Min Total Goals" and sel_["destination"]["outcome"] == "Under"
        else:
            assert sel_["reason_code"] in {"no_fixture", "market_unavailable", "suspended", "time_mismatch"} and sel_["destination"] is None \
                or sel_["reason_code"] in {"market_unavailable", "suspended"}


def test_ticket_rules_one_pick_per_game_and_only_current_upcoming_picks(client, pro_user, scanner_world, db, demo):
    both = [pid(db, scanner_world["u1"], "MARKET_A"), pid(db, scanner_world["u1"], "MARKET_B")]
    r = tk(client, "demo_alpha", both)
    assert r.status_code == 422 and "one pick per game" in r.json()["detail"]["message"]
    # kicked off
    u3 = scanner_world["u3"]
    u3.kickoff_at = _now() - timedelta(minutes=5)
    db.commit()
    started = tk(client, "demo_alpha", [pid(db, scanner_world["u2"]), db.scalar(select(Prediction.id).where(Prediction.fixture_id == u3.id))])
    assert started.status_code == 422 and "already started" in started.json()["detail"]["message"]
    assert tk(client, "demo_alpha", [424242]).status_code == 422
    assert tk(client, "demo_alpha", []).status_code == 422
    assert tk(client, "demo_alpha", list(range(1, 22))).status_code == 422


def test_excluded_picks_cannot_be_put_on_a_ticket(client, pro_user, scanner_world, db, demo):
    p = db.scalar(select(Prediction).where(Prediction.fixture_id == scanner_world["u4"].id, Prediction.market_code == "MARKET_A"))
    assert p is not None and p.category == "excluded"
    r = tk(client, "demo_alpha", [p.id])
    assert r.status_code == 422 and "excluded" in r.json()["detail"]["message"]


def test_a_rescan_supersedes_old_picks_and_the_preview_points_to_the_current_one(client, pro_user, scanner_world, db):
    old = pid(db, scanner_world["u1"])
    run_scan(db, now=_now() + timedelta(minutes=1), notify=False, replay=False)
    db.commit()
    cur = pid(db, scanner_world["u1"])
    if cur != old:                                                     # only when the re-scan produced a new row
        item = client.post(f"{B}/ticket/preview", json={"prediction_ids": [old]}).json()["items"][0]
        assert item["available"] is False and item["replaced_by"] == cur and "re-run" in item["reason"]


def test_free_plan_can_only_use_picks_its_scanner_view_shows(client, user_factory, scanner_world, db, demo, monkeypatch):
    from app.models import Plan

    user_factory(email="free@example.com")
    login(client, "free@example.com")
    free = db.scalar(select(Plan).where(Plan.code == "free"))
    free.features = {**free.features, "scanner_full": False, "scanner_daily_limit": 1}
    db.commit()
    ids = [pid(db, scanner_world[k]) for k in ("u1", "u2", "u3")]
    items = client.post(f"{B}/ticket/preview", json={"prediction_ids": ids}).json()["items"]
    allowed = [i for i in items if i["available"]]
    assert len(allowed) <= 1 and any("plan" in (i["reason"] or "") for i in items if not i["available"])
    blocked = tk(client, "demo_alpha", ids)
    assert blocked.status_code == 422


def test_ticket_input_validation_and_bookmaker_rules(client, pro_user, scanner_world, db, demo):
    one = [pid(db, scanner_world["u1"])]
    assert tk(client, "bet9ja", one).json()["detail"]["code"] == "integration_unavailable"
    internal = tk(client, "first5minute", one)
    assert internal.status_code == 422 and internal.json()["detail"]["code"] == "unsupported_bookmaker"
    assert client.post(f"{B}/ticket", json={"destination": "demo_alpha", "prediction_ids": ["x"]}).status_code == 422
    assert "first5minute" not in {b["code"] for b in client.get(f"{B}/bookmakers").json()["bookmakers"]}


def test_ticket_requires_sign_in_and_respects_the_switch(client, user_factory, monkeypatch):
    assert client.post(f"{B}/ticket/preview", json={"prediction_ids": [1]}).status_code == 401
    user_factory(email="tk@example.com")
    login(client, "tk@example.com")
    monkeypatch.setattr(get_settings(), "booking_converter_enabled", False)
    assert client.post(f"{B}/ticket/preview", json={"prediction_ids": [1]}).status_code == 503


def test_manual_ticket_to_a_bookmaker_without_code_creation(client, pro_user, scanner_world, db, demo):
    d = tk(client, "demo_gamma", [pid(db, scanner_world["u1"])]).json()
    m = client.post(f"{B}/{d['id']}/match").json()
    assert m["counts"]["matched"] == 1
    g = client.post(f"{B}/{d['id']}/generate", json={}).json()
    assert g["booking"]["status"] == "manual" and g["booking"]["code"] is None and "Demo Book Gamma" in g["betslip_text"]


def test_self_excluded_users_cannot_build_tickets(client, pro_user, scanner_world, db, demo):
    pro_user.rg_self_excluded_until = utcnow() + timedelta(days=2)
    db.commit()
    r = tk(client, "demo_alpha", [pid(db, scanner_world["u1"])])
    assert r.status_code == 403 and r.json()["detail"]["code"] == "self_excluded"


def test_five_minute_market_names_from_bookmakers_reduce_to_the_same_canonical_market():
    same = c("First 5 Minutes - Total Goals", "Under 0.5", "0.5").canon
    for name, out, spec in [("5 Min Total Goals", "Under", "total=0.5"), ("0-5 Min Over/Under", "Under 0.5", None),
                            ("Goal in first 5 minutes", "No", None), ("1st 5 minutes - Over/Under", "U 0.5", None)]:
        assert c(name, out, spec).canon == same, name
    assert same.period == "5M"
    draw = c("First 5 Minutes - 1X2", "Draw").canon
    assert c("5 Min Result", "X").canon == draw and draw.market == "1X2" and draw.period == "5M"
    # never confused with full time, other windows, or other markets that mention minutes
    assert same != c("Total Goals", "Under 0.5", "0.5").canon and draw != c("1X2", "Draw").canon
    for name in ("Total Corners first 5 minutes", "Booking in first 5 minutes", "1X2 15 minutes", "Next goal 5 minutes"):
        assert c(name, "Over 0.5", "0.5").canon is None, name


# ================================================================================================== go-live readiness (doctor)


def _settings(**kw):
    s = get_settings().model_copy(update=kw)
    return s


def by_area(checks):
    return {c.area: c for c in checks}


def test_doctor_flags_an_unsafe_production_configuration():
    from app.ops import doctor as d

    s = _settings(environment="production", cookie_secure=False, email_backend="console", frontend_url="http://localhost:3000",
                  booking_converter_demo=True, football_provider="demo")
    c = by_area(d.run_all(s, with_io=False))
    assert c["Secret key"].status == d.FAIL and c["Cookies"].status == d.FAIL and c["Email"].status == d.FAIL
    assert c["Public address"].status == d.FAIL and c["Converter demo"].status == d.FAIL
    assert c["Football data"].status == d.WARN and "NOT live" in c["Football data"].detail
    assert "Fix every FAIL" in d.render(d.run_all(s, with_io=False))


def test_doctor_is_honest_that_conversion_is_not_live_until_a_bookmaker_is_connected():
    from app.ops import doctor as d

    c = by_area(d.converter_checks(_settings(football_provider="api_football")))
    assert c["Booking converter"].status == d.WARN and "NOT live" in c["Booking converter"].detail
    assert c["Ticket games"].status == d.PASS
    registry.register_adapter(FakeBook("fake_live", "Fake Live"))
    live = by_area(d.converter_checks(_settings(football_provider="api_football")))
    assert live["Booking converter"].status == d.PASS and "Fake Live" in live["Booking converter"].detail


def test_doctor_passes_a_safe_config_and_never_prints_secrets():
    from app.ops import doctor as d

    s = _settings(environment="production", secret_key="x" * 40, cookie_secure=True, email_backend="smtp", smtp_host="smtp.example.com",
                  frontend_url="https://app.example.com", football_provider="api_football", api_football_key="SECRETKEY123",
                  football_league_ids=["39"], payment_provider="paystack", paystack_secret_key="sk_live_SECRET", booking_converter_demo=False)
    checks = d.config_checks(s)
    assert all(c.status in (d.PASS, d.INFO) for c in checks), [c for c in checks if c.status in (d.WARN, d.FAIL)]
    text_out = d.render(d.run_all(s, with_io=False))
    assert "SECRETKEY123" not in text_out and "sk_live_SECRET" not in text_out and "xxxxxxxx" not in text_out


def test_doctor_with_database_checks_runs_against_the_test_database():
    from app.ops import doctor as d

    c = by_area(d.io_checks(get_settings()))
    assert c["Database"].status == d.PASS and "0007" in c["Database"].detail


def test_create_user_makes_a_verified_normal_user(db):
    from app.cli import create_user
    from app.models import Subscription, User

    create_user("teammate@example.com", "TeamPass123x", "pro")
    u = db.scalar(select(User).where(User.email == "teammate@example.com"))
    assert u.is_verified and not u.is_admin
    assert db.scalar(select(Subscription).where(Subscription.user_id == u.id)).status == "active"
    with pytest.raises(SystemExit):
        create_user("teammate@example.com", "TeamPass123x", "free")
    with pytest.raises(SystemExit):
        create_user("weak@example.com", "short", "free")


# ---------------------------------------------------------------------------------------------------------------------
# Cloud deployment helpers
# ---------------------------------------------------------------------------------------------------------------------
def test_database_url_from_hosting_providers_gets_the_psycopg_driver():
    from app.core.config import Settings

    for given in ("postgres://u:p@h:5432/d", "postgresql://u:p@h:5432/d", "postgresql+psycopg://u:p@h:5432/d"):
        assert Settings(database_url=given).database_url == "postgresql+psycopg://u:p@h:5432/d"


def test_bootstrap_creates_admin_once_and_never_resets_it(db, monkeypatch):
    from app.cli import bootstrap
    from app.core.security import verify_password
    from app.models import User

    s = get_settings()
    monkeypatch.setattr(s, "football_provider", "none")      # no demo data in this test
    monkeypatch.setattr(s, "bootstrap_admin_email", "Boss@Example.com")
    monkeypatch.setattr(s, "bootstrap_admin_password", "FirstPass123x")
    assert bootstrap()["admin"] == "created"
    u = db.scalar(select(User).where(User.email == "boss@example.com"))
    assert u.is_admin and u.is_verified
    monkeypatch.setattr(s, "bootstrap_admin_password", "ChangedPass123x")
    assert bootstrap()["admin"] == "already exists"
    db.expire_all()
    assert verify_password("FirstPass123x", db.scalar(select(User).where(User.email == "boss@example.com")).password_hash)


def test_bootstrap_without_settings_does_nothing(monkeypatch):
    from app.cli import bootstrap

    s = get_settings()
    monkeypatch.setattr(s, "football_provider", "none")
    monkeypatch.setattr(s, "bootstrap_admin_email", None)
    monkeypatch.setattr(s, "bootstrap_admin_password", None)
    assert bootstrap() == {"admin": "not configured", "demo_data": "not needed"}


def test_bootstrap_rejects_a_weak_admin_password(monkeypatch):
    from app.cli import bootstrap

    s = get_settings()
    monkeypatch.setattr(s, "football_provider", "none")
    monkeypatch.setattr(s, "bootstrap_admin_email", "weak@example.com")
    monkeypatch.setattr(s, "bootstrap_admin_password", "short")
    with pytest.raises(SystemExit):
        bootstrap()


def test_admin_can_mark_a_teammates_email_verified(client, db, user_factory):
    from app.models import User
    from tests.conftest import login

    admin = user_factory(email="boss2@example.com", role="admin")
    mate = user_factory(email="mate@example.com", verified=False)
    assert not mate.is_verified
    login(client, admin.email)
    r = client.patch(f"/api/v1/admin/users/{mate.id}", json={"email_verified": True})
    assert r.status_code == 200
    db.expire_all()
    assert db.get(User, mate.id).is_verified


def test_demo_staleness_rule():
    from app.cli import demo_is_stale

    now = datetime(2026, 11, 10, 12, tzinfo=UTC)
    assert demo_is_stale("2026-11-10", 0, now) is False            # 0 = never refresh
    assert demo_is_stale("2026-11-10", 20, now) is False           # loaded today (anchor midnight, 12h ago)
    assert demo_is_stale("2026-11-08", 20, now) is True
    assert demo_is_stale(None, 20, now) is True                    # unknown age counts as stale
    assert demo_is_stale("garbage", 20, now) is True


def test_bootstrap_loads_demo_data_on_first_start_without_reset(db, monkeypatch):
    import app.cli as cli

    s = get_settings()
    monkeypatch.setattr(s, "football_provider", "demo")
    monkeypatch.setattr(s, "bootstrap_admin_email", None)
    calls: list[bool] = []
    monkeypatch.setattr(cli, "seed_demo", lambda reset, days: calls.append(reset))
    db.execute(text("DELETE FROM fixtures WHERE is_demo"))
    db.commit()
    assert cli.bootstrap()["demo_data"] == "loaded" and calls == [False]
