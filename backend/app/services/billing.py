"""Subscription lifecycle: checkout, payment confirmation, renewal, cancel, expiry."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import utcnow
from app.models import Invoice, Notification, Plan, Subscription, User
from app.providers.payments.paystack import PaystackClient
from app.services.audit import audit

PERIOD = {"month": timedelta(days=30), "year": timedelta(days=365)}


def start_checkout(db: Session, user: User, plan: Plan, client: PaystackClient | None = None) -> dict:
    if plan.price_minor <= 0:
        raise ValueError("free plan does not require checkout")
    client = client or PaystackClient()
    reference = f"p5-{user.id}-{plan.code}-{secrets.token_hex(6)}"
    data = client.initialize(
        email=user.email,
        amount_minor=plan.price_minor,
        currency=plan.currency,
        reference=reference,
        callback_url=f"{get_settings().frontend_url}/account/billing?reference={reference}",
        metadata={"user_id": user.id, "plan_code": plan.code},
    )
    db.add(Invoice(user_id=user.id, plan_id=plan.id, amount_minor=plan.price_minor, currency=plan.currency,
                   status="pending", payment_provider="paystack", provider_reference=reference))
    audit(db, "billing.checkout_started", user.id, "plan", plan.code, {"reference": reference})
    db.flush()
    return {"authorization_url": data.get("authorization_url"), "reference": reference}


def apply_successful_payment(db: Session, reference: str, amount_minor: int, currency: str, payload: dict,
                             paid_at: datetime | None = None) -> Subscription | None:
    """Idempotently mark an invoice paid and activate/extend the subscription."""
    inv = db.scalar(
        select(Invoice).where(Invoice.payment_provider == "paystack", Invoice.provider_reference == reference).with_for_update()
    )
    if inv is None:
        audit(db, "billing.unknown_reference", None, "invoice", reference)
        return None
    if inv.status == "paid":
        return db.get(Subscription, inv.subscription_id) if inv.subscription_id else None
    if amount_minor != inv.amount_minor or currency.upper() != inv.currency.upper():
        inv.status = "failed"
        audit(db, "billing.amount_mismatch", inv.user_id, "invoice", inv.id,
              {"expected": inv.amount_minor, "got": amount_minor, "currency": currency})
        return None
    now = paid_at or utcnow()
    plan = db.get(Plan, inv.plan_id)
    assert plan is not None
    sub = db.scalar(
        select(Subscription).where(Subscription.user_id == inv.user_id, Subscription.plan_id == plan.id,
                                   Subscription.status == "active")
    )
    period = PERIOD.get(plan.interval, timedelta(days=30))
    if sub is None:
        # Replacing another plan: end any other active subscription now.
        for other in db.scalars(select(Subscription).where(Subscription.user_id == inv.user_id,
                                                           Subscription.status.in_(["active", "cancelled"]))):
            other.status, other.current_period_end = "expired", now
        sub = Subscription(user_id=inv.user_id, plan_id=plan.id, status="active", current_period_start=now,
                           current_period_end=now + period, payment_provider="paystack",
                           provider_customer_ref=str((payload.get("customer") or {}).get("customer_code") or "") or None)
        db.add(sub)
    else:  # renewal extends from the later of now / current end
        start = max(now, sub.current_period_end or now)
        sub.current_period_start, sub.current_period_end = start, start + period
        sub.cancel_at_period_end = False
    db.flush()
    inv.status, inv.paid_at, inv.subscription_id, inv.raw_payload = "paid", now, sub.id, payload
    db.add(Notification(user_id=inv.user_id, kind="billing", title=f"{plan.name} plan active",
                        body=f"Payment received. Your {plan.name} plan is active until {sub.current_period_end:%d %b %Y}.",
                        link="/account/billing"))
    audit(db, "billing.payment_succeeded", inv.user_id, "invoice", inv.id, {"plan": plan.code})
    db.flush()
    return sub


def cancel_subscription(db: Session, user: User) -> Subscription | None:
    sub = db.scalar(select(Subscription).where(Subscription.user_id == user.id, Subscription.status == "active"))
    if sub is None:
        return None
    sub.status, sub.cancel_at_period_end, sub.cancelled_at = "cancelled", True, utcnow()
    audit(db, "billing.subscription_cancelled", user.id, "subscription", sub.id)
    db.flush()
    return sub


def expire_subscriptions(db: Session, now: datetime | None = None) -> int:
    now = now or utcnow()
    subs = db.scalars(select(Subscription).where(Subscription.status.in_(["active", "cancelled"]),
                                                 Subscription.current_period_end <= now)).all()
    for s in subs:
        s.status = "expired"
        db.add(Notification(user_id=s.user_id, kind="billing", title="Subscription expired",
                            body=f"Your {s.plan.name} plan has expired. Renew to restore access.", link="/pricing"))
    db.flush()
    return len(subs)
