"""Phase 6: saved payment methods, auto-renewal, dunning/grace, reminders, email outbox, demo payments."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import utcnow
from app.models import Invoice, Notification, PaymentMethod, Plan, Subscription
from app.providers.payments.paystack import PaymentError
from app.services import billing
from app.services.email import OUTBOX
from app.services.entitlements import active_subscription, entitlements
from app.services.notifications import deliver_notification_emails
from tests.conftest import login

SECRET = "sk_test_renewals"


class FakeClient:
    """Stands in for the payment provider; ``script`` is a list of charge responses (or exceptions), consumed in order."""

    def __init__(self, script=None, verify_result=None):
        self.script = list(script or [])
        self.calls: list[dict] = []
        self.verify_result = verify_result or {"status": "abandoned"}

    def charge_authorization(self, **kw):
        self.calls.append(kw)
        item = self.script.pop(0) if self.script else {"status": "success"}
        if isinstance(item, Exception):
            raise item
        out = {"reference": kw["reference"], "amount": kw["amount_minor"], "currency": kw["currency"], **item}
        return out

    def verify(self, reference):
        return {"reference": reference, **self.verify_result}


@pytest.fixture(autouse=True)
def provider(monkeypatch):
    monkeypatch.setattr(get_settings(), "payment_provider", "paystack")
    monkeypatch.setattr(get_settings(), "paystack_secret_key", SECRET)
    OUTBOX.clear()


def make_sub(db, user, end_in=timedelta(hours=1), plan="pro", status="active", card=True, **kw) -> Subscription:
    p = db.scalar(select(Plan).where(Plan.code == plan))
    now = utcnow()
    sub = Subscription(user_id=user.id, plan_id=p.id, status=status, current_period_start=now - timedelta(days=30) + end_in,
                       current_period_end=now + end_in, payment_provider="paystack", **kw)
    db.add(sub)
    if card:
        db.add(PaymentMethod(user_id=user.id, provider="paystack", authorization_code="AUTH_abc", brand="visa", last4="4081"))
    db.commit()
    return sub


def inv_count(db, sub, status=None):
    q = select(Invoice).where(Invoice.subscription_id == sub.id, Invoice.kind == "renewal")
    if status:
        q = q.where(Invoice.status == status)
    return len(db.scalars(q).all())


def test_first_payment_saves_reusable_card_only(db, user_factory):
    u = user_factory(email="a@example.com")
    plan = db.scalar(select(Plan).where(Plan.code == "pro"))
    db.add(Invoice(user_id=u.id, plan_id=plan.id, amount_minor=plan.price_minor, currency=plan.currency, status="pending",
                   payment_provider="paystack", provider_reference="r1", kind="checkout"))
    db.commit()
    auth = {"authorization_code": "AUTH_x", "reusable": True, "signature": "SIG_1", "brand": "visa ", "last4": "4081",
            "exp_month": "12", "exp_year": "2030", "bank": "TEST BANK"}
    sub = billing.apply_successful_payment(db, "r1", plan.price_minor, plan.currency, {"authorization": auth})
    db.commit()
    assert sub.status == "active" and sub.auto_renew
    pm = billing.default_method(db, u.id, "paystack")
    assert pm.last4 == "4081" and pm.brand == "visa" and pm.authorization_code == "AUTH_x"
    # a non-reusable authorisation is never stored
    db.add(Invoice(user_id=u.id, plan_id=plan.id, amount_minor=plan.price_minor, currency=plan.currency, status="pending",
                   payment_provider="paystack", provider_reference="r2", kind="checkout"))
    db.commit()
    billing.apply_successful_payment(db, "r2", plan.price_minor, plan.currency,
                                     {"authorization": {"authorization_code": "AUTH_y", "reusable": False, "last4": "1111"}})
    db.commit()
    assert [m.authorization_code for m in billing.list_methods(db, u.id)] == ["AUTH_x"]
    receipt = db.scalars(select(Notification).where(Notification.user_id == u.id, Notification.kind == "billing")).first()
    assert receipt.email_requested and "r1" in receipt.body and "renews automatically" in receipt.body


def test_same_card_entered_twice_is_deduplicated(db, user_factory):
    u = user_factory(email="dup@example.com")
    for code in ("AUTH_1", "AUTH_2"):
        billing.save_payment_method(db, u.id, "paystack", {"authorization_code": code, "signature": "SAME", "last4": "4081"})
    db.commit()
    methods = billing.list_methods(db, u.id)
    assert len(methods) == 1 and methods[0].authorization_code == "AUTH_2"


def test_renewal_charges_saved_card_and_extends_period(db, user_factory):
    u = user_factory(email="r@example.com")
    sub = make_sub(db, u, end_in=timedelta(hours=1))
    old_end = sub.current_period_end
    fake = FakeClient([{"status": "success", "authorization": {"authorization_code": "AUTH_abc"}}])
    out = billing.renew_due_subscriptions(db, fake)
    db.refresh(sub)
    assert out["charged"] == 1 and len(fake.calls) == 1
    call = fake.calls[0]
    assert call["authorization_code"] == "AUTH_abc" and call["amount_minor"] == sub.plan.price_minor and call["email"] == u.email
    assert sub.current_period_end == old_end + timedelta(days=30) and sub.renewal_attempts == 0 and sub.status == "active"
    assert inv_count(db, sub, "paid") == 1
    # nothing more to charge until the next window
    assert billing.renew_due_subscriptions(db, fake)["charged"] == 0 and len(fake.calls) == 1


def test_not_charged_before_window_or_when_disabled_or_cancelled(db, user_factory):
    fake = FakeClient()
    early = make_sub(db, user_factory(email="e@example.com"), end_in=timedelta(days=10))
    off = make_sub(db, user_factory(email="o@example.com"), end_in=timedelta(hours=1), auto_renew=False)
    cancelled = make_sub(db, user_factory(email="c@example.com"), end_in=timedelta(hours=1), status="cancelled",
                         cancel_at_period_end=True)
    nocard = make_sub(db, user_factory(email="n@example.com"), end_in=timedelta(hours=1), card=False)
    out = billing.renew_due_subscriptions(db, fake)
    assert fake.calls == [] and out["charged"] == 0 and out["no_card"] == 1
    assert all(inv_count(db, s) == 0 for s in (early, off, cancelled, nocard))


def test_failed_renewal_retries_then_grace_then_expiry(db, user_factory, monkeypatch):
    s = get_settings()
    u = user_factory(email="f@example.com")
    sub = make_sub(db, u, end_in=timedelta(hours=1))
    end = sub.current_period_end
    fake = FakeClient([{"status": "failed", "gateway_response": "Insufficient funds"}] * 3)

    # attempt 1: inside the lead window, before the period ends -> still fully active
    out = billing.renew_due_subscriptions(db, fake, now=end - timedelta(hours=1))
    db.refresh(sub)
    assert out["failed"] == 1 and sub.status == "active" and sub.renewal_attempts == 1
    # not retried too soon
    assert billing.renew_due_subscriptions(db, fake, now=end - timedelta(minutes=30))["failed"] == 0
    # attempt 2 after the period ended -> past_due, access continues in grace
    out = billing.renew_due_subscriptions(db, fake, now=end + timedelta(hours=24))
    db.refresh(sub)
    assert out["failed"] == 1 and sub.status == "past_due" and sub.renewal_attempts == 2 and sub.past_due_since is not None
    assert active_subscription(db, u, now=end + timedelta(days=1)).id == sub.id
    assert entitlements(db, u)["plan"] == "pro"  # real clock: the period has not actually ended yet
    # attempt 3 (final)
    out = billing.renew_due_subscriptions(db, fake, now=end + timedelta(hours=49))
    db.refresh(sub)
    assert out["failed"] == 1 and sub.renewal_attempts == s.renewal_max_attempts and sub.next_renewal_attempt_at is None
    # no fourth charge, ever
    assert billing.renew_due_subscriptions(db, fake, now=end + timedelta(hours=60))["failed"] == 0 and len(fake.calls) == 3
    # within grace: still has access; after grace: expired
    assert billing.expire_subscriptions(db, now=end + timedelta(days=s.renewal_grace_days) - timedelta(hours=1)) == 0
    assert active_subscription(db, u, now=end + timedelta(days=2)) is not None
    assert billing.expire_subscriptions(db, now=end + timedelta(days=s.renewal_grace_days, hours=1)) == 1
    db.commit()
    db.refresh(sub)
    assert sub.status == "expired" and active_subscription(db, u, now=end + timedelta(days=4)) is None
    titles = [n.title for n in db.scalars(select(Notification).where(Notification.user_id == u.id).order_by(Notification.id))]
    assert "We couldn't renew your plan" in titles and "Renewal failed - action needed" in titles and "Subscription expired" in titles
    failed = db.scalars(select(Invoice).where(Invoice.subscription_id == sub.id, Invoice.status == "failed")).all()
    assert len(failed) == 3 and failed[0].failure_reason == "Insufficient funds"


def test_successful_retry_recovers_past_due(db, user_factory):
    u = user_factory(email="rec@example.com")
    sub = make_sub(db, u, end_in=timedelta(hours=1))
    end = sub.current_period_end
    fake = FakeClient([{"status": "failed", "gateway_response": "Declined"}, {"status": "success"}])
    billing.renew_due_subscriptions(db, fake, now=end + timedelta(hours=1))
    db.refresh(sub)
    assert sub.status == "past_due"
    billing.renew_due_subscriptions(db, fake, now=end + timedelta(hours=26))
    db.refresh(sub)
    assert sub.status == "active" and sub.renewal_attempts == 0 and sub.past_due_since is None
    # a late renewal starts the new period when it is actually paid (the grace days are not free time)
    assert sub.current_period_end == end + timedelta(hours=26) + timedelta(days=30)


def test_provider_error_and_amount_mismatch_count_as_failures(db, user_factory):
    sub1 = make_sub(db, user_factory(email="p1@example.com"))
    sub2 = make_sub(db, user_factory(email="p2@example.com"))
    fake = FakeClient([PaymentError("gateway down"), {"status": "success", "amount": 100}])
    out = billing.renew_due_subscriptions(db, fake)
    assert out["failed"] == 2 and out["charged"] == 0
    for s in (sub1, sub2):
        db.refresh(s)
        assert s.renewal_attempts == 1 and s.current_period_end < utcnow() + timedelta(days=2)


def test_pending_charge_is_resolved_not_double_charged(db, user_factory):
    sub = make_sub(db, user_factory(email="pend@example.com"))
    fake = FakeClient([{"status": "pending"}], verify_result={"status": "pending"})
    assert billing.renew_due_subscriptions(db, fake)["pending"] == 1
    # an immediate rerun must not charge again (and not before next_renewal_attempt_at)
    assert billing.renew_due_subscriptions(db, fake)["charged"] == 0 and len(fake.calls) == 1
    # later the provider reports success: the pending invoice is settled, still exactly one charge
    fake.verify_result = {"status": "success", "amount": sub.plan.price_minor, "currency": sub.plan.currency}
    out = billing.renew_due_subscriptions(db, fake, now=utcnow() + timedelta(hours=3))
    db.refresh(sub)
    assert out["charged"] == 1 and len(fake.calls) == 1 and inv_count(db, sub, "paid") == 1
    assert sub.current_period_end > utcnow() + timedelta(days=25)


def test_webhook_confirms_pending_renewal(client, db, user_factory):
    sub = make_sub(db, user_factory(email="wh@example.com"))
    fake = FakeClient([{"status": "pending"}])
    billing.renew_due_subscriptions(db, fake)
    ref = db.scalars(select(Invoice).where(Invoice.subscription_id == sub.id)).first().provider_reference
    body = json.dumps({"event": "charge.success", "data": {"reference": ref, "amount": sub.plan.price_minor,
                                                          "currency": sub.plan.currency}}).encode()
    sig = hmac.new(SECRET.encode(), body, hashlib.sha512).hexdigest()
    assert client.post("/api/v1/webhooks/paystack", content=body, headers={"x-paystack-signature": sig}).status_code == 200
    db.expire_all()
    s = db.get(Subscription, sub.id)
    assert s.status == "active" and s.current_period_end > utcnow() + timedelta(days=25) and s.renewal_attempts == 0


def test_expire_without_card_ends_plan_but_with_card_goes_past_due(db, user_factory):
    gone = make_sub(db, user_factory(email="x1@example.com"), end_in=-timedelta(minutes=5), card=False)
    kept = make_sub(db, user_factory(email="x2@example.com"), end_in=-timedelta(minutes=5))
    assert billing.expire_subscriptions(db) == 1
    db.commit()
    db.refresh(gone)
    db.refresh(kept)
    assert gone.status == "expired" and kept.status == "past_due"


def test_reminders_once_per_period_with_correct_wording(db, user_factory):
    auto = make_sub(db, user_factory(email="rm1@example.com"), end_in=timedelta(days=2))
    manual = make_sub(db, user_factory(email="rm2@example.com"), end_in=timedelta(days=2), card=False)
    cancelled = make_sub(db, user_factory(email="rm3@example.com"), end_in=timedelta(days=2), status="cancelled",
                         cancel_at_period_end=True)
    far = make_sub(db, user_factory(email="rm4@example.com"), end_in=timedelta(days=20))
    assert billing.send_renewal_reminders(db) == 3
    assert billing.send_renewal_reminders(db) == 0
    db.commit()

    def body(s):
        return db.scalar(select(Notification.body).where(Notification.user_id == s.user_id))

    assert "will be charged" in body(auto) and "4081" in body(auto)
    assert "will not renew automatically" in body(manual)
    assert "will not renew" in body(cancelled)
    assert body(far) is None


def test_cancel_resume_toggle_and_remove_card_via_api(client, db, user_factory):
    u = user_factory(email="api@example.com")
    sub = make_sub(db, u, end_in=timedelta(days=10))
    login(client, "api@example.com")
    data = client.get("/api/v1/subscriptions").json()
    assert data["renewal"]["will_auto_renew"] is True and data["payment_methods"][0]["last4"] == "4081"
    assert "authorization_code" not in json.dumps(data)  # the token never leaves the server
    assert client.post("/api/v1/subscriptions/auto-renew", json={"enabled": False}).json() == {"auto_renew": False}
    assert client.get("/api/v1/subscriptions").json()["renewal"]["will_auto_renew"] is False
    assert client.post("/api/v1/subscriptions/auto-renew", json={"enabled": True}).status_code == 200
    assert client.post("/api/v1/subscriptions/cancel").status_code == 200
    assert client.post("/api/v1/subscriptions/resume").status_code == 200
    db.expire_all()
    assert db.get(Subscription, sub.id).status == "active"
    mid = data["payment_methods"][0]["id"]
    assert client.delete(f"/api/v1/subscriptions/payment-methods/{mid}").status_code == 200
    assert client.delete(f"/api/v1/subscriptions/payment-methods/{mid}").status_code == 404
    assert client.get("/api/v1/subscriptions").json()["renewal"]["will_auto_renew"] is False


def test_cannot_remove_someone_elses_card(client, db, user_factory):
    owner = user_factory(email="own@example.com")
    make_sub(db, owner)
    mid = db.scalar(select(PaymentMethod.id).where(PaymentMethod.user_id == owner.id))
    user_factory(email="intruder@example.com")
    login(client, "intruder@example.com")
    assert client.delete(f"/api/v1/subscriptions/payment-methods/{mid}").status_code == 404
    assert billing.list_methods(db, owner.id)


def test_email_outbox_delivers_once_and_respects_age(db, user_factory):
    u = user_factory(email="mail@example.com")
    billing.notify(db, u.id, "Hello", "Body one")
    billing.notify(db, u.id, "In-app only", "No mail", email=False)
    old = Notification(user_id=u.id, kind="billing", title="Old", body="stale", email_requested=True,
                       created_at=utcnow() - timedelta(days=5))
    db.add(old)
    db.commit()
    out = deliver_notification_emails(db)
    db.commit()
    assert out == {"sent": 1, "failed": 0, "dropped": 1}
    assert len(OUTBOX) == 1 and OUTBOX[0].to == "mail@example.com" and "Body one" in OUTBOX[0].body
    assert deliver_notification_emails(db) == {"sent": 0, "failed": 0, "dropped": 0}


def test_email_failure_keeps_notification_queued(db, user_factory, monkeypatch):
    u = user_factory(email="down@example.com")
    billing.notify(db, u.id, "Hello", "Body")
    db.commit()

    def boom(*a, **k):
        raise OSError("smtp down")

    monkeypatch.setattr("app.services.notifications.send_email", boom)
    assert deliver_notification_emails(db)["failed"] == 1
    monkeypatch.undo()
    monkeypatch.setattr(get_settings(), "payment_provider", "paystack")
    assert deliver_notification_emails(db)["sent"] == 1


# --- demo payment provider --------------------------------------------------------


@pytest.fixture
def demo(monkeypatch):
    monkeypatch.setattr(get_settings(), "payment_provider", "demo")


def _demo_buy(client, card):
    r = client.post("/api/v1/subscriptions/checkout", json={"plan_code": "pro"})
    assert r.status_code == 200 and "/account/demo-checkout?reference=" in r.json()["authorization_url"]
    ref = r.json()["reference"]
    done = client.post("/api/v1/subscriptions/demo/complete", json={"reference": ref, "card": card})
    assert done.status_code == 200 and done.json()["status"] == "paid"
    return ref


def test_demo_checkout_renewals_work_or_decline(client, db, user_factory, demo):
    ok = user_factory(email="demo-ok@example.com")
    login(client, "demo-ok@example.com")
    _demo_buy(client, "works")
    sub = db.scalar(select(Subscription).where(Subscription.user_id == ok.id))
    assert sub.status == "active" and billing.default_method(db, ok.id).is_demo
    sub.current_period_end = utcnow() + timedelta(hours=1)
    db.commit()
    assert billing.renew_due_subscriptions(db)["charged"] == 1

    bad = user_factory(email="demo-bad@example.com")
    client.cookies.clear()
    login(client, "demo-bad@example.com")
    _demo_buy(client, "declines")
    sub2 = db.scalar(select(Subscription).where(Subscription.user_id == bad.id))
    sub2.current_period_end = utcnow() + timedelta(hours=1)
    db.commit()
    out = billing.renew_due_subscriptions(db)
    assert out["failed"] == 1
    assert "demo card" in db.scalar(select(Invoice.failure_reason).where(Invoice.user_id == bad.id, Invoice.status == "failed"))


def test_demo_endpoint_unavailable_for_real_providers(client, db, user_factory):
    u = user_factory(email="nodemo@example.com")
    login(client, "nodemo@example.com")
    plan = db.scalar(select(Plan).where(Plan.code == "pro"))
    db.add(Invoice(user_id=u.id, plan_id=plan.id, amount_minor=1, currency="NGN", status="pending",
                   payment_provider="demo", provider_reference="x"))
    db.commit()
    assert client.post("/api/v1/subscriptions/demo/complete", json={"reference": "x", "card": "works"}).status_code == 404


def test_demo_payments_refused_in_production_and_time_travel_needs_demo(monkeypatch, capsys):
    from app.cli import main

    s = get_settings()
    monkeypatch.setattr(s, "payment_provider", "demo")
    monkeypatch.setattr(s, "environment", "production")
    with pytest.raises(RuntimeError, match="PAYMENT_PROVIDER=demo"):
        s.validate_production()
    monkeypatch.setattr(s, "environment", "development")
    monkeypatch.setattr(s, "payment_provider", "paystack")
    with pytest.raises(SystemExit):
        main(["renew", "--as-of", "2030-01-01T00:00"])
    with pytest.raises(SystemExit):
        main(["renew", "--advance-days", "30"])
