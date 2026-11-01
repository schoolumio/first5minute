"""Plan entitlements, user isolation, admin permissions and payment webhooks."""

import hashlib
import hmac
import json
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.database import utcnow
from app.engine.settlement import Rule
from app.ingestion.service import Ingestor
from app.models import AuditLog, Fixture, Invoice, Plan, Subscription, User
from app.scanner.service import run_scan
from tests import factories as f
from tests.conftest import login

SECRET = "sk_test_mock_secret"


@pytest.fixture
def scanned(db):
    now = utcnow()
    ing = Ingestor(db, "mock", False, Rule())
    for nf in f.season_history(now - timedelta(days=60), n_teams=8, rounds=16, early_goal_every=50):
        ing.ingest_fixture(nf)
    for i, (h, a) in enumerate([(1, 2), (3, 4), (5, 6), (7, 8), (2, 3), (4, 5)]):
        ing.ingest_fixture(f.upcoming(f"u{i}", h, a, now + timedelta(hours=6 + i)))
    db.commit()
    run_scan(db, now=now)
    db.commit()
    return now


def test_free_plan_scanner_is_limited_on_backend(client, user_factory, db, scanned):
    user_factory(email="free@example.com")
    login(client, "free@example.com")
    r = client.get("/api/v1/scanner", params={"categories": ["qualified", "watchlist", "below_threshold"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["plan"] == "free" and len(body["items"]) <= 3 and body["locked_count"] > 0
    assert client.get("/api/v1/scanner", params={"min_sample": 5}).status_code == 402
    assert client.get("/api/v1/odds/1").status_code == 402


def test_pro_plan_gets_full_scanner_and_filters(client, user_factory, db, scanned):
    user_factory(email="pro@example.com", plan="pro")
    login(client, "pro@example.com")
    body = client.get("/api/v1/scanner", params={"categories": ["qualified", "watchlist", "below_threshold"],
                                                  "min_sample": 5, "sort": "kickoff"}).json()
    assert body["locked_count"] == 0 and body["total"] == 12 and body["odds_included"]
    kicks = [i["kickoff_at"] for i in body["items"]]
    assert kicks == sorted(kicks)
    only_a = client.post("/api/v1/scanner/filters", json={"market": "MARKET_A", "categories": ["qualified", "watchlist", "below_threshold"]}).json()
    assert {i["market"] for i in only_a["items"]} == {"MARKET_A"}
    fid = body["items"][0]["fixture_id"]
    odds = client.get(f"/api/v1/odds/{fid}").json()
    assert odds["odds"] == [] and odds["provider_configured"] is False and "No odds" in odds["message"]
    analysis = client.get(f"/api/v1/fixtures/{fid}/analysis").json()
    assert "last20" in analysis["home"]["windows"] and not analysis["locked"]["head_to_head"]


def test_free_plan_analysis_is_partially_locked(client, user_factory, db, scanned):
    user_factory(email="free2@example.com")
    login(client, "free2@example.com")
    fid = db.scalar(select(Fixture.id).where(Fixture.provider_id == "u0"))
    a = client.get(f"/api/v1/fixtures/{fid}/analysis").json()
    assert a["locked"]["extended_history"] and "last20" not in a["home"]["windows"]
    assert set(a["predictions"]) == {"MARKET_A", "MARKET_B"}


def test_saved_matches_are_private(client, user_factory, db, scanned):
    user_factory(email="a@example.com")
    user_factory(email="b@example.com")
    fid = db.scalar(select(Fixture.id).where(Fixture.provider_id == "u0"))
    login(client, "a@example.com")
    sid = client.post("/api/v1/saved-matches", json={"fixture_id": fid}).json()["id"]
    assert len(client.get("/api/v1/saved-matches").json()) == 1
    client.cookies.clear()
    login(client, "b@example.com")
    assert client.get("/api/v1/saved-matches").json() == []
    assert client.delete(f"/api/v1/saved-matches/{sid}").status_code == 404


def test_bet_tracking_respects_self_exclusion_and_limits(client, user_factory, db, scanned):
    user_factory(email="bettor@example.com")
    login(client, "bettor@example.com")
    fid = db.scalar(select(Fixture.id).where(Fixture.provider_id == "u0"))
    assert client.put("/api/v1/account/responsible-gambling", json={"daily_stake_limit": 1000}).status_code == 200
    bet = {"fixture_id": fid, "market": "MARKET_A", "decimal_odds": 1.15, "stake": 1500, "confirm": True}
    r = client.post("/api/v1/bets", json=bet)
    assert r.status_code == 201 and r.json()["warnings"]
    assert client.post("/api/v1/bets", json={**bet, "confirm": False}).status_code == 422
    client.put("/api/v1/account/responsible-gambling", json={"self_exclude_days": 30})
    assert client.post("/api/v1/bets", json=bet).status_code == 403


def test_admin_endpoints_require_admin(client, user_factory):
    user_factory(email="plain@example.com", plan="elite")
    login(client, "plain@example.com")
    for path in ("/api/v1/admin/overview", "/api/v1/admin/providers", "/api/v1/admin/model-performance",
                 "/api/v1/admin/users", "/api/v1/admin/audit-logs"):
        assert client.get(path).status_code == 403
    client.cookies.clear()
    assert client.get("/api/v1/admin/overview").status_code == 401


def test_admin_updates_pricing_and_thresholds_with_audit(client, user_factory, db):
    user_factory(email="admin@example.com", role="admin")
    login(client, "admin@example.com")
    r = client.patch("/api/v1/admin/plans/starter", json={"price_minor": 650000})
    assert r.status_code == 200 and r.json()["price"] == 6500
    bad = {"MARKET_A": {"qualified_min_probability": 0.9, "watchlist_min_probability": 0.95},
           "MARKET_B": {"qualified_min_probability": 0.9, "watchlist_min_probability": 0.85},
           "qualified_min_team_sample": 10, "watchlist_min_team_sample": 5, "qualified_min_data_quality": "medium",
           "lookahead_hours": 48}
    assert client.put("/api/v1/admin/settings/scanner.thresholds", json=bad).status_code == 422
    bad["MARKET_A"]["watchlist_min_probability"] = 0.85
    assert client.put("/api/v1/admin/settings/scanner.thresholds", json=bad).status_code == 200
    assert client.get("/api/v1/admin/settings").json()["scanner.thresholds"]["lookahead_hours"] == 48
    actions = {a.action for a in db.scalars(select(AuditLog))}
    assert {"admin.plan_updated", "admin.setting_updated"} <= actions
    assert client.get("/api/v1/plans").json()["plans"][1]["price"] == 6500


def test_admin_can_grant_plan(client, user_factory, db):
    user_factory(email="boss@example.com", role="admin")
    target = user_factory(email="cust@example.com")
    login(client, "boss@example.com")
    r = client.patch(f"/api/v1/admin/users/{target.id}", json={"plan_code": "pro"})
    assert r.status_code == 200 and r.json()["entitlements"]["plan"] == "pro"


def _sign(body: bytes) -> str:
    return hmac.new(SECRET.encode(), body, hashlib.sha512).hexdigest()


@pytest.fixture
def paystack(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "paystack_secret_key", SECRET)
    monkeypatch.setattr(get_settings(), "payment_provider", "paystack")


def _pending_invoice(db, user: User, plan_code="pro", ref="ref-1") -> Invoice:
    plan = db.scalar(select(Plan).where(Plan.code == plan_code))
    inv = Invoice(user_id=user.id, plan_id=plan.id, amount_minor=plan.price_minor, currency=plan.currency,
                  status="pending", payment_provider="paystack", provider_reference=ref)
    db.add(inv)
    db.commit()
    return inv


def test_checkout_unavailable_without_payment_config(client, user_factory):
    user_factory(email="buyer@example.com")
    login(client, "buyer@example.com")
    r = client.post("/api/v1/subscriptions/checkout", json={"plan_code": "pro"})
    assert r.status_code == 503 and "not configured" in r.json()["detail"]


def test_checkout_with_mocked_paystack(client, user_factory, paystack, monkeypatch):
    import httpx

    from app.providers.payments import paystack as ps

    def handler(request):
        assert request.headers["Authorization"] == f"Bearer {SECRET}"
        payload = json.loads(request.content)
        assert payload["amount"] == 1_200_000 and payload["currency"] == "NGN"
        return httpx.Response(200, json={"status": True, "data": {"authorization_url": "https://checkout.paystack.test/x"}})

    original = ps.PaystackClient.__init__
    monkeypatch.setattr(ps.PaystackClient, "__init__", lambda self, transport=None: original(self, httpx.MockTransport(handler)))
    user_factory(email="buyer2@example.com")
    login(client, "buyer2@example.com")
    r = client.post("/api/v1/subscriptions/checkout", json={"plan_code": "pro"})
    assert r.status_code == 200 and r.json()["authorization_url"].startswith("https://checkout.paystack.test")


def test_webhook_rejects_bad_signature(client, paystack):
    body = json.dumps({"event": "charge.success", "data": {}}).encode()
    r = client.post("/api/v1/webhooks/paystack", content=body, headers={"x-paystack-signature": "bad"})
    assert r.status_code == 401


def test_webhook_activates_subscription_idempotently(client, user_factory, db, paystack):
    u = user_factory(email="payer@example.com")
    _pending_invoice(db, u)
    body = json.dumps({"event": "charge.success", "data": {"reference": "ref-1", "amount": 1_200_000, "currency": "NGN",
                                                           "customer": {"customer_code": "CUS_x"}}}).encode()
    for _ in range(2):
        r = client.post("/api/v1/webhooks/paystack", content=body, headers={"x-paystack-signature": _sign(body)})
        assert r.status_code == 200
    db.expire_all()
    subs = db.scalars(select(Subscription).where(Subscription.user_id == u.id)).all()
    assert len(subs) == 1 and subs[0].status == "active" and subs[0].plan.code == "pro"
    login(client, "payer@example.com")
    assert client.get("/api/v1/subscriptions").json()["entitlements"]["plan"] == "pro"
    assert client.post("/api/v1/subscriptions/cancel").status_code == 200
    # Cancelled subscriptions keep access until period end.
    assert client.get("/api/v1/auth/me").json()["entitlements"]["plan"] == "pro"


def test_webhook_amount_mismatch_does_not_activate(client, user_factory, db, paystack):
    u = user_factory(email="cheat@example.com")
    _pending_invoice(db, u, ref="ref-2")
    body = json.dumps({"event": "charge.success", "data": {"reference": "ref-2", "amount": 100, "currency": "NGN"}}).encode()
    assert client.post("/api/v1/webhooks/paystack", content=body, headers={"x-paystack-signature": _sign(body)}).status_code == 200
    db.expire_all()
    assert db.scalar(select(Subscription).where(Subscription.user_id == u.id)) is None
    assert db.scalar(select(Invoice.status).where(Invoice.provider_reference == "ref-2")) == "failed"


def test_expired_subscription_falls_back_to_free(db, user_factory):
    from app.services.billing import expire_subscriptions
    from app.services.entitlements import entitlements

    u = user_factory(email="lapsed@example.com", plan="starter")
    sub = db.scalar(select(Subscription).where(Subscription.user_id == u.id))
    sub.current_period_end = utcnow() - timedelta(minutes=1)
    db.commit()
    assert expire_subscriptions(db) == 1
    assert entitlements(db, u)["plan"] == "free"


def test_system_status_reports_demo_mode(client):
    s = client.get("/api/v1/system/status").json()
    assert s["data_mode"] == "demo" and "synthetic" in s["demo_notice"]
