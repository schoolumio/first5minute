"""Phase 5: odds ingestion, comparison, approval, safe links, demo provider, backtest integrity."""

import json
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.database import utcnow
from app.engine.backtest import _best_pre_kickoff_odds
from app.engine.settlement import Rule
from app.ingestion.service import Ingestor
from app.models import AuditLog, BettingMarket, Bookmaker, Fixture, OddsSnapshot, Prediction, SettlementRule, SyncRun, User
from app.providers.football.base import ProviderError
from app.providers.odds.base import (
    ExecutionNotEnabled,
    NormalizedOdds,
    OddsProvider,
    get_execution_adapter,
)
from app.providers.odds.demo import DEMO_BOOKS, DemoOddsProvider
from app.scanner.service import run_scan
from app.services.odds import best_fresh, build_link, country_allowed, import_odds, sync_odds, validate_link_template
from tests import factories as f
from tests.conftest import login


class FakeOdds(OddsProvider):
    name, fixture_provider, is_demo = "fake", "mock", False

    def __init__(self):
        self.data: dict[str, list[NormalizedOdds]] = {}
        self.calls: list[str] = []
        self.fail: set[str] = set()

    def odds_for_fixture(self, provider_fixture_id):
        self.calls.append(provider_fixture_id)
        if provider_fixture_id in self.fail:
            raise ProviderError("boom")
        return self.data.get(provider_fixture_id, [])


def o(book="book-a", market="MARKET_A", odds=1.20, available=True, ref="evt-1", name=None):
    return NormalizedOdds(bookmaker_code=book, bookmaker_name=name or book.upper(), market_code=market, selection="No" if market == "MARKET_A" else "Draw",
                          decimal_odds=odds, is_available=available, event_ref=ref)


@pytest.fixture
def world(db):
    """Predicted league: fixtures u1,u2 upcoming with current predictions; returns (now, fixtures dict, provider)."""
    now = utcnow()
    ing = Ingestor(db, "mock", False, Rule())
    for nf in f.season_history(now - timedelta(days=60), n_teams=6, rounds=14, early_goal_every=50):
        ing.ingest_fixture(nf)
    ing.ingest_fixture(f.upcoming("u1", 1, 2, now + timedelta(hours=20)))
    ing.ingest_fixture(f.upcoming("u2", 3, 4, now + timedelta(hours=22)))
    db.commit()
    run_scan(db, now=now, notify=False)
    db.commit()
    fx = {x.provider_id: x for x in db.scalars(select(Fixture).where(Fixture.provider_id.in_(["u1", "u2"])))}
    return now, fx, FakeOdds()


def approve(db, code="book-a", template="https://book.example/event/{event_ref}?ref=f5m", countries=None, rule=None):
    bm = db.scalar(select(Bookmaker).where(Bookmaker.code == code))
    bm.is_active, bm.deep_link_template, bm.countries, bm.settlement_rule_id = True, template, countries or [], rule
    db.commit()
    return bm


def prob(db, fx, market="MARKET_A"):
    return db.scalar(select(Prediction.probability).where(Prediction.fixture_id == fx.id, Prediction.market_code == market, Prediction.is_current))


# ------------------------------------------------------------------ sync
def test_sync_creates_pending_bookmakers_and_dedupes(db, world):
    now, fx, prov = world
    prov.data["u1"] = [o("book-a", odds=1.20), o("book-a", "MARKET_B", 1.18), o("book-b", odds=1.25)]
    s = sync_odds(db, prov, now)
    db.commit()
    assert s.snapshots_added == 3 and s.new_bookmakers_pending == 2 and s.fixtures_polled == 2 and s.empty_responses == 1
    assert all(not b.is_active and b.source == "provider" for b in db.scalars(select(Bookmaker)))
    assert sync_odds(db, prov, now + timedelta(minutes=5)).snapshots_added == 0            # unchanged: not re-stored
    prov.data["u1"][0] = o("book-a", odds=1.22)
    assert sync_odds(db, prov, now + timedelta(minutes=10)).snapshots_added == 1           # changed
    assert db.scalar(select(SyncRun).where(SyncRun.job == "odds_sync").limit(1)) is not None


def test_heartbeat_refreshes_unchanged_odds_only_when_due(db, world):
    now, fx, prov = world
    prov.data["u1"] = [o("book-a")]
    sync_odds(db, prov, now)
    db.commit()
    assert sync_odds(db, prov, now + timedelta(minutes=30)).snapshots_added == 0
    assert sync_odds(db, prov, now + timedelta(minutes=61)).snapshots_added == 1


def test_withdrawn_prices_are_marked_unavailable_but_empty_responses_are_ignored(db, world):
    now, fx, prov = world
    prov.data["u1"] = [o("book-a"), o("book-b", odds=1.3)]
    sync_odds(db, prov, now)
    db.commit()
    prov.data["u1"] = [o("book-a")]                                                         # book-b withdrew its price
    s = sync_odds(db, prov, now + timedelta(minutes=5))
    db.commit()
    assert s.marked_unavailable == 1
    latest = {x.bookmaker.code: x for x in db.scalars(select(OddsSnapshot).order_by(OddsSnapshot.id))}
    assert latest["book-b"].is_available is False and float(latest["book-b"].decimal_odds) == 1.3
    prov.data["u1"] = []                                                                    # transient empty response: no mass withdrawal
    assert sync_odds(db, prov, now + timedelta(minutes=9)).marked_unavailable == 0


def test_sync_skips_invalid_odds_records_errors_and_respects_budget(db, world):
    now, fx, prov = world
    prov.data["u1"] = [o("book-a", odds=1.0), o("book-a", odds=5000), o("book-a", market="MARKET_Z", odds=1.2), o("book-a", odds=1.4)]
    prov.fail.add("u2")
    s = sync_odds(db, prov, now)
    db.commit()
    assert s.snapshots_added == 1 and s.skipped_invalid == 3 and any("u2" in e for e in s.errors)
    assert db.scalar(select(SyncRun.status).where(SyncRun.job == "odds_sync")) == "partial"
    from app.services.settings import set_setting

    set_setting(db, "odds.settings", {"max_fixtures_per_run": 1}, None)
    prov.calls.clear()
    sync_odds(db, prov, now + timedelta(minutes=1))
    assert prov.calls == ["u1"]                                                             # nearest kick-off first


def test_sync_ignores_fixtures_from_other_providers(db, world):
    now, fx, prov = world
    other = FakeOdds()
    other.fixture_provider = "somewhere-else"
    other.data["u1"] = [o("book-a")]
    assert sync_odds(db, other, now).fixtures_polled == 0


# ------------------------------------------------------------------ visibility / math
def test_pending_bookmakers_are_hidden_until_approved(client, db, world, user_factory):
    now, fx, prov = world
    prov.data["u1"] = [o("book-a", odds=1.20)]
    sync_odds(db, prov, now)
    db.commit()
    user_factory(email="pro1@example.com", plan="pro")
    login(client, "pro1@example.com")
    assert client.get(f"/api/v1/odds/{fx['u1'].id}").json()["odds"] == []
    approve(db)
    rows = client.get(f"/api/v1/odds/{fx['u1'].id}").json()["odds"]
    assert [r["bookmaker"]["code"] for r in rows] == ["book-a"]


def test_fair_odds_edge_staleness_and_best_price(client, db, world, user_factory):
    now, fx, prov = world
    p = prob(db, fx["u1"])
    prov.data["u1"] = [o("book-a", odds=1.30), o("book-b", odds=1.10)]
    sync_odds(db, prov, utcnow())
    db.commit()
    approve(db, "book-a")
    approve(db, "book-b", template=None)
    user_factory(email="pro2@example.com", plan="pro")
    login(client, "pro2@example.com")
    body = client.get(f"/api/v1/odds/{fx['u1'].id}").json()
    a = next(r for r in body["odds"] if r["bookmaker"]["code"] == "book-a")
    assert a["fair_odds"] == pytest.approx(1 / p, abs=1e-3) and a["edge"] == pytest.approx(p * 1.30 - 1, abs=1e-3)
    assert a["implied_probability"] == pytest.approx(1 / 1.30, abs=1e-3) and a["can_open"] is True
    assert next(r for r in body["odds"] if r["bookmaker"]["code"] == "book-b")["can_open"] is False      # no link template yet
    m = body["markets"]["MARKET_A"]
    assert m["best"]["bookmaker_code"] == "book-a" and m["edge"] == pytest.approx(p * 1.30 - 1, abs=1e-3)
    assert body["best_history"]["MARKET_A"] and body["responsible_gambling"]["self_excluded"] is False
    # Make everything stale: edge disappears, best price disappears, link cannot be opened.
    for s in db.scalars(select(OddsSnapshot)):
        s.captured_at = utcnow() - timedelta(minutes=500)
    db.commit()
    stale = client.get(f"/api/v1/odds/{fx['u1'].id}").json()
    assert all(r["is_stale"] and r["edge"] is None and not r["can_open"] for r in stale["odds"])
    assert stale["markets"]["MARKET_A"]["best"] is None
    assert best_fresh(db, [fx["u1"].id], None) == {}


def test_settlement_rule_mismatch_is_flagged(client, db, world, user_factory):
    now, fx, prov = world
    prov.data["u1"] = [o("book-a")]
    sync_odds(db, prov, utcnow())
    db.commit()
    other_rule = db.scalar(select(SettlementRule).where(SettlementRule.is_default.is_(False)))
    approve(db, rule=other_rule.id)
    user_factory(email="pro3@example.com", plan="pro")
    login(client, "pro3@example.com")
    row = client.get(f"/api/v1/odds/{fx['u1'].id}").json()["odds"][0]
    assert row["rule_mismatch"] is True and "differently" in row["rule_note"]


def test_country_restrictions(client, db, world, user_factory):
    now, fx, prov = world
    prov.data["u1"] = [o("book-a")]
    sync_odds(db, prov, utcnow())
    approve(db, countries=["NG", "GH"])
    ng = user_factory(email="ng@example.com", plan="pro")
    ng.country = "ng"
    user_factory(email="nocountry@example.com", plan="pro")
    gb = user_factory(email="gb@example.com", plan="pro")
    gb.country = "GB"
    db.commit()
    for email, expected in (("ng@example.com", 1), ("nocountry@example.com", 0), ("gb@example.com", 0)):
        client.cookies.clear()
        login(client, email)
        assert len(client.get(f"/api/v1/odds/{fx['u1'].id}").json()["odds"]) == expected, email
    bm = db.scalar(select(Bookmaker))
    assert country_allowed(bm, "NG") and not country_allowed(bm, None) and country_allowed(Bookmaker(countries=[]), None)


def test_odds_board_sorting_filtering_and_gating(client, db, world, user_factory):
    now, fx, prov = world
    pa = prob(db, fx["u1"])
    prov.data["u1"] = [o("book-a", odds=round(1 / pa * 1.10, 2)), o("book-a", "MARKET_B", 1.05)]      # value on A, none on B
    prov.data["u2"] = [o("book-a", odds=1.01)]
    sync_odds(db, prov, utcnow())
    approve(db)
    user_factory(email="free-board@example.com")
    user_factory(email="pro-board@example.com", plan="pro")
    login(client, "free-board@example.com")
    assert client.get("/api/v1/odds").status_code == 402
    client.cookies.clear()
    login(client, "pro-board@example.com")
    body = client.get("/api/v1/odds").json()
    assert body["total"] == 3 and body["items"][0]["edge"] > 0.05 and body["items"][0]["market"] == "MARKET_A"
    assert [i["edge"] for i in body["items"]] == sorted((i["edge"] for i in body["items"]), reverse=True)
    value_only = client.get("/api/v1/odds", params={"min_edge": 0.06}).json()
    assert value_only["total"] == 1
    assert client.get("/api/v1/odds", params={"sort": "kickoff"}).json()["items"][0]["fixture"]["id"] == fx["u1"].id
    assert client.get("/api/v1/odds", params={"market": "X"}).status_code == 422


# ------------------------------------------------------------------ links
@pytest.mark.parametrize("bad", ["http://book.example/{event_ref}", "https://user:pw@book.example/x", "javascript:alert(1)",
                                 "https://book.example/{other}", "https://{event_ref}.evil.example/x", "ftp://x.example", "https://"])
def test_unsafe_link_templates_are_rejected(bad):
    with pytest.raises(ValueError):
        validate_link_template(bad)


def test_link_building_quotes_event_reference():
    assert build_link("https://book.example/e/{event_ref}?r=1", "a b/c?d") == "https://book.example/e/a%20b%2Fc%3Fd?r=1"
    assert build_link("https://book.example/home", None) == "https://book.example/home"
    with pytest.raises(ValueError):
        build_link("https://book.example/e/{event_ref}", None)
    with pytest.raises(ValueError):
        build_link(None, "x")


def _open(client, fx, code="book-a", market="MARKET_A", **kw):
    return client.post(f"/api/v1/odds/{fx.id}/open", json={"bookmaker_code": code, "market": market, **kw})


def test_open_link_success_is_audited_and_prefills_bet(client, db, world, user_factory):
    now, fx, prov = world
    prov.data["u1"] = [o("book-a", odds=1.25, ref="evt 7/x")]
    sync_odds(db, prov, utcnow())
    approve(db)
    user_factory(email="opener@example.com", plan="pro")
    login(client, "opener@example.com")
    r = _open(client, fx["u1"])
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["url"] == "https://book.example/event/evt%207%2Fx?ref=f5m" and "leaving First5Minute" in b["notice"]
    assert b["bet_prefill"] == {"fixture_id": fx["u1"].id, "market": "MARKET_A", "decimal_odds": 1.25, "bookmaker_id": b["bet_prefill"]["bookmaker_id"]}
    log = db.scalar(select(AuditLog).where(AuditLog.action == "odds.link_opened"))
    assert log.details["bookmaker"] == "book-a" and log.details["odds"] == 1.25


def test_open_link_guards(client, db, world, user_factory):
    now, fx, prov = world
    prov.data["u1"] = [o("book-a", odds=1.25), o("book-b", odds=1.3, ref=None)]
    sync_odds(db, prov, utcnow())
    approve(db)
    approve(db, "book-b", template="https://b.example/{event_ref}")
    u = user_factory(email="guard@example.com", plan="pro")
    login(client, "guard@example.com")
    assert _open(client, fx["u1"], code="nope").status_code == 404
    assert _open(client, fx["u1"], code="book-b").status_code == 422                      # template needs an event ref the feed lacks
    assert _open(client, fx["u1"], market="MARKET_B").status_code == 409                  # no price for that market
    # stake limit reached -> needs explicit acknowledgement
    client.put("/api/v1/account/responsible-gambling", json={"daily_stake_limit": 100})
    client.post("/api/v1/bets", json={"fixture_id": fx["u1"].id, "market": "MARKET_A", "decimal_odds": 1.2, "stake": 100, "confirm": True})
    limited = _open(client, fx["u1"])
    assert limited.status_code == 409 and limited.json()["detail"]["code"] == "limit_reached"
    ok = _open(client, fx["u1"], acknowledge_limits=True)
    assert ok.status_code == 200 and ok.json()["responsible_gambling"]["daily"]["reached"] is True
    assert db.scalar(select(AuditLog).where(AuditLog.action == "odds.link_opened").order_by(AuditLog.id.desc())).details["limit_override"] is True
    # self-exclusion blocks links entirely
    client.put("/api/v1/account/responsible-gambling", json={"self_exclude_days": 7})
    assert _open(client, fx["u1"], acknowledge_limits=True).status_code == 403
    assert client.get(f"/api/v1/odds/{fx['u1'].id}").json()["odds"][0]["can_open"] is False
    assert u.id


def test_open_link_blocked_for_started_match_stale_odds_and_free_plan(client, db, world, user_factory):
    now, fx, prov = world
    prov.data["u1"] = [o("book-a")]
    sync_odds(db, prov, utcnow())
    approve(db)
    user_factory(email="free-open@example.com")
    login(client, "free-open@example.com")
    assert _open(client, fx["u1"]).status_code == 402
    client.cookies.clear()
    user_factory(email="late@example.com", plan="pro")
    login(client, "late@example.com")
    for s in db.scalars(select(OddsSnapshot)):
        s.captured_at = utcnow() - timedelta(hours=9)
    db.commit()
    assert _open(client, fx["u1"]).status_code == 409
    fx["u1"].kickoff_at = utcnow() - timedelta(minutes=1)
    db.commit()
    assert _open(client, fx["u1"]).status_code == 409


def test_no_bet_placing_capability_exists(client):
    paths = " ".join(client.get("/api/openapi.json").json()["paths"]).lower()
    for word in ("place", "execute", "submit-bet", "stake"):
        assert word not in paths
    with pytest.raises(ExecutionNotEnabled):
        get_execution_adapter("anything")


# ------------------------------------------------------------------ demo provider
def test_demo_odds_are_labelled_deterministic_and_never_for_real_fixtures(db, world):
    now, fx, _ = world
    real = DemoOddsProvider(db, now)
    assert real.odds_for_fixture("u1") == []                                                  # mock (non-demo) fixture: nothing fabricated
    for x in fx.values():
        x.is_demo, x.provider = True, "demo"
    db.commit()
    demo = DemoOddsProvider(db, now)
    rows = demo.odds_for_fixture("u1")
    assert {r.bookmaker_code for r in rows} == set(DEMO_BOOKS) and rows == DemoOddsProvider(db, now).odds_for_fixture("u1")
    for r in rows:
        p = prob(db, fx["u1"], r.market_code)
        assert p * r.decimal_odds - 1 < 0                                                      # no value by construction
    d = demo.bookmaker_defaults("demo-a")
    assert d["is_demo"] and d["is_active"] and d["deep_link_template"].startswith("https://example.com/")
    assert demo.bookmaker_defaults("other") == {}
    demo.fixture_provider = "demo"
    s = sync_odds(db, demo, now)
    db.commit()
    assert s.snapshots_added == len(rows) + len(demo.odds_for_fixture("u2"))
    assert all(sn.is_demo for sn in db.scalars(select(OddsSnapshot))) and all(b.is_demo and b.is_active for b in db.scalars(select(Bookmaker)))
    assert db.scalar(select(Bookmaker.settlement_rule_id).where(Bookmaker.code == "demo-c")) is not None


# ------------------------------------------------------------------ backtest integrity
def test_backtest_uses_only_real_active_compatible_last_prices(db, world):
    now, fx, prov = world
    target = fx["u1"]
    default_rule = db.scalar(select(SettlementRule).where(SettlementRule.is_default.is_(True)))
    other_rule = db.scalar(select(SettlementRule).where(SettlementRule.is_default.is_(False)))
    mk = db.scalar(select(BettingMarket).where(BettingMarket.code == "MARKET_A"))

    def book(code, active=True, demo=False, rule=None):
        b = Bookmaker(code=code, name=code, is_active=active, is_demo=demo, settlement_rule_id=rule)
        db.add(b)
        db.flush()
        return b

    def snap(b, odds, minutes_before, available=True, demo=False):
        db.add(OddsSnapshot(fixture_id=target.id, bookmaker_id=b.id, market_id=mk.id, selection="No", decimal_odds=odds, is_available=available,
                            source_provider="t", is_demo=demo, captured_at=target.kickoff_at - timedelta(minutes=minutes_before)))

    real, inactive, demo_b, mismatch = book("real"), book("inact", active=False), book("dem", demo=True), book("mis", rule=other_rule.id)
    snap(real, 2.0, 600)
    snap(real, 1.5, 30)                      # price fell before kick-off: the last price is what was takeable
    snap(inactive, 9.0, 20)
    snap(demo_b, 9.0, 20, demo=True)
    snap(mismatch, 9.0, 20)
    snap(real, 1.4, -5)                      # after kick-off: ignored
    db.commit()
    assert _best_pre_kickoff_odds(db, target, "MARKET_A", default_rule.id) == 1.5
    other = book("other", rule=default_rule.id)
    snap(other, 1.7, 10)
    snap(other, 2.2, 5, available=False)     # withdrawn at the end: not takeable
    db.commit()
    assert _best_pre_kickoff_odds(db, target, "MARKET_A", default_rule.id) == 1.5
    assert _best_pre_kickoff_odds(db, target, "MARKET_B", default_rule.id) is None


# ------------------------------------------------------------------ admin
def test_admin_bookmaker_review_validation_and_import(client, db, world, user_factory, tmp_path):
    now, fx, prov = world
    prov.data["u1"] = [o("book-z", name="Book Z")]
    sync_odds(db, prov, utcnow())
    db.commit()
    user_factory(email="oddsadmin@example.com", role="admin")
    user_factory(email="oddsplain@example.com", role="user", plan="elite")
    login(client, "oddsplain@example.com")
    assert client.get("/api/v1/admin/bookmakers").status_code == 403
    client.cookies.clear()
    login(client, "oddsadmin@example.com")
    books = client.get("/api/v1/admin/bookmakers").json()
    z = next(b for b in books if b["code"] == "book-z")
    assert z["pending_review"] is True and z["is_active"] is False and z["supports_execution_api"] is False
    bid = z["id"]
    assert client.patch(f"/api/v1/admin/bookmakers/{bid}", json={"deep_link_template": "http://insecure.example/x"}).status_code == 422
    assert client.patch(f"/api/v1/admin/bookmakers/{bid}", json={"countries": ["Nigeria"]}).status_code == 422
    assert client.patch(f"/api/v1/admin/bookmakers/{bid}", json={"settlement_rule_id": 9999}).status_code == 422
    r = client.patch(f"/api/v1/admin/bookmakers/{bid}", json={"is_active": True, "countries": ["ng", "gh", "ng"],
                                                              "deep_link_template": "https://z.example/e/{event_ref}", "settlement_rule_id": 1})
    assert r.status_code == 200 and r.json()["countries"] == ["GH", "NG"] and r.json()["pending_review"] is False and r.json()["settlement_rule_code"]
    cleared = client.patch(f"/api/v1/admin/bookmakers/{bid}", json={"deep_link_template": None, "settlement_rule_id": None}).json()
    assert cleared["deep_link_template"] is None and cleared["settlement_rule_id"] is None
    assert client.post("/api/v1/admin/bookmakers", json={"code": "new-book", "name": "N", "deep_link_template": "https://n.example/{event_ref}"}).status_code == 201

    rows = [{"fixture_id": fx["u2"].id, "bookmaker_code": "imp-book", "market": "MARKET_A", "decimal_odds": 1.33},
            {"fixture_id": fx["u2"].id, "bookmaker_code": "imp-book", "market": "MARKET_B", "decimal_odds": 1.30, "is_available": False}]
    first = client.post("/api/v1/admin/odds/import", json={"rows": rows}).json()
    assert first["inserted"] == 2 and first["new_bookmakers_pending"] == 1 and not first["errors"]
    assert db.scalar(select(Bookmaker.is_active).where(Bookmaker.code == "imp-book")) is False
    assert client.post("/api/v1/admin/odds/import", json={"rows": [{**rows[0], "decimal_odds": 1.0}]}).status_code == 422
    assert client.post("/api/v1/admin/odds/import", json={"rows": []}).status_code == 422
    late = client.post("/api/v1/admin/odds/import", json={"rows": [{**rows[0], "captured_at": (utcnow() + timedelta(days=3)).isoformat()}]}).json()
    assert late["inserted"] == 0 and "kick-off" in late["errors"][0]
    ghost = client.post("/api/v1/admin/odds/import", json={"rows": [{**rows[0], "fixture_id": 99999}]}).json()
    assert ghost["inserted"] == 0 and "unknown" in ghost["errors"][0]
    stamped = {**rows[0], "captured_at": (utcnow() - timedelta(hours=2)).isoformat()}
    assert client.post("/api/v1/admin/odds/import", json={"rows": [stamped]}).json()["inserted"] == 1
    assert client.post("/api/v1/admin/odds/import", json={"rows": [stamped]}).json()["duplicates"] == 1

    # CLI import path (same validation, same service)
    from app.cli import main as cli_main

    path = tmp_path / "odds.json"
    path.write_text(json.dumps({"rows": [{**rows[0], "bookmaker_code": "cli-book"}]}))
    cli_main(["odds-import", str(path)])
    assert db.scalar(select(Bookmaker.id).where(Bookmaker.code == "cli-book")) is not None


def test_odds_job_is_a_noop_without_provider_and_settings_are_validated(client, db, user_factory):
    from app.workers.jobs import job_odds

    assert "skipped" in job_odds(db)
    user_factory(email="oddscfg@example.com", role="admin")
    login(client, "oddscfg@example.com")
    assert client.put("/api/v1/admin/settings/odds.settings", json={"max_age_minutes": 1, "max_fixtures_per_run": 10, "lookahead_hours": 48,
                                                                    "heartbeat_minutes": 60}).status_code == 422
    ok = client.put("/api/v1/admin/settings/odds.settings", json={"max_age_minutes": 90, "max_fixtures_per_run": 10, "lookahead_hours": 48,
                                                                  "heartbeat_minutes": 30})
    assert ok.status_code == 200 and client.get("/api/v1/admin/settings").json()["odds.settings"]["max_age_minutes"] == 90
    assert client.post("/api/v1/admin/jobs", json={"job": "odds"}).json()["result"]["skipped"]


def test_import_service_rejects_naive_timestamps(db, world):
    from datetime import datetime

    now, fx, _ = world
    out = import_odds(db, [{"fixture_id": fx["u1"].id, "bookmaker_code": "x-book", "market": "MARKET_A", "decimal_odds": 1.2,
                            "captured_at": datetime(2020, 1, 1)}])
    assert out["inserted"] == 0 and "timezone" in out["errors"][0] and User
