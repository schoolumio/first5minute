"""Subscription lifecycle: checkout, payment confirmation, auto-renewal, dunning, cancel and expiry.

Money rules this module enforces:

* A subscription is only ever activated/extended by ``apply_successful_payment`` after the provider confirmed the charge
  and the amount/currency match the invoice. It is idempotent per invoice reference.
* Auto-renewal charges only a reusable authorisation the user created by paying at checkout; the app never sees or stores
  card numbers. The invoice is committed *before* the provider is called, so a crash can never lose a charge reference.
* Failed renewals are retried a limited number of times; access continues for a grace period, then the plan expires.
* Cancelling or switching off auto-renew stops all further charges.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import utcnow
from app.core.logging import get_logger
from app.models import Invoice, Notification, PaymentMethod, Plan, Subscription, User
from app.providers.payments import get_payment_client
from app.providers.payments.paystack import PaymentError, PaymentNotConfigured
from app.services.audit import audit

log = get_logger(__name__)

PERIOD = {"month": timedelta(days=30), "year": timedelta(days=365)}
LIVE_STATUSES = ("active", "cancelled", "past_due")
PENDING_STATES = {"pending", "ongoing", "processing", "queued"}


def _money(minor: int, currency: str) -> str:
    return f"{currency} {minor / 100:,.2f}"


def notify(db: Session, user_id: int, title: str, body: str, link: str = "/account?tab=billing", email: bool = True) -> None:
    """In-app notification plus (by default) an email queued in the outbox for the notify job."""
    db.add(Notification(user_id=user_id, kind="billing", title=title, body=body, link=link, email_requested=email))


# --- checkout --------------------------------------------------------------------


def start_checkout(db: Session, user: User, plan: Plan, client=None) -> dict:
    if plan.price_minor <= 0:
        raise ValueError("free plan does not require checkout")
    provider = get_settings().payment_provider
    client = client or get_payment_client()
    reference = f"f5-{user.id}-{plan.code}-{secrets.token_hex(6)}"
    data = client.initialize(
        email=user.email,
        amount_minor=plan.price_minor,
        currency=plan.currency,
        reference=reference,
        callback_url=f"{get_settings().frontend_url}/account?tab=billing&reference={reference}",
        metadata={"user_id": user.id, "plan_code": plan.code},
    )
    db.add(Invoice(user_id=user.id, plan_id=plan.id, amount_minor=plan.price_minor, currency=plan.currency,
                   status="pending", payment_provider=provider, provider_reference=reference, kind="checkout"))
    audit(db, "billing.checkout_started", user.id, "plan", plan.code, {"reference": reference})
    db.flush()
    return {"authorization_url": data.get("authorization_url"), "reference": reference}


# --- payment methods -------------------------------------------------------------


def default_method(db: Session, user_id: int, provider: str | None = None) -> PaymentMethod | None:
    q = select(PaymentMethod).where(PaymentMethod.user_id == user_id, PaymentMethod.removed_at.is_(None))
    if provider:
        q = q.where(PaymentMethod.provider == provider)
    return db.scalars(q.order_by(PaymentMethod.is_default.desc(), PaymentMethod.id.desc())).first()


def list_methods(db: Session, user_id: int) -> list[PaymentMethod]:
    return list(db.scalars(select(PaymentMethod).where(PaymentMethod.user_id == user_id, PaymentMethod.removed_at.is_(None))
                           .order_by(PaymentMethod.is_default.desc(), PaymentMethod.id.desc())))


def save_payment_method(db: Session, user_id: int, provider: str, auth: dict | None) -> PaymentMethod | None:
    """Store a *reusable* provider authorisation (token + card display details only). Newest card becomes the default."""
    if not auth or not auth.get("reusable", True) or not auth.get("authorization_code"):
        return None
    code, sig = str(auth["authorization_code"]), auth.get("signature")
    existing = db.scalars(select(PaymentMethod).where(PaymentMethod.user_id == user_id, PaymentMethod.provider == provider,
                                                      PaymentMethod.removed_at.is_(None))).all()
    for m in existing:
        m.is_default = False
    match = next((m for m in existing if m.authorization_code == code or (sig and m.card_signature == sig)), None)
    pm = match or PaymentMethod(user_id=user_id, provider=provider, authorization_code=code)
    pm.authorization_code, pm.card_signature = code, sig
    pm.brand = (auth.get("brand") or auth.get("card_type") or "card")[:32].strip()
    pm.last4, pm.exp_month, pm.exp_year = auth.get("last4"), auth.get("exp_month"), auth.get("exp_year")
    pm.bank, pm.is_default, pm.is_demo = (auth.get("bank") or None), True, provider == "demo"
    if match is None:
        db.add(pm)
    db.flush()
    return pm


def remove_payment_method(db: Session, user: User, method_id: int) -> bool:
    pm = db.scalar(select(PaymentMethod).where(PaymentMethod.id == method_id, PaymentMethod.user_id == user.id,
                                               PaymentMethod.removed_at.is_(None)))
    if pm is None:
        return False
    pm.removed_at, pm.is_default = utcnow(), False
    nxt = default_method(db, user.id)
    if nxt is not None:
        nxt.is_default = True
    audit(db, "billing.payment_method_removed", user.id, "payment_method", pm.id)
    if nxt is None:
        sub = db.scalar(select(Subscription).where(Subscription.user_id == user.id, Subscription.status.in_(LIVE_STATUSES))
                        .order_by(Subscription.current_period_end.desc().nullslast()))
        if sub is not None and sub.status != "cancelled" and sub.current_period_end:
            notify(db, user.id, "Card removed - plan will not renew automatically",
                   f"You removed your saved card. Your {sub.plan.name} plan will end on {sub.current_period_end:%d %b %Y} "
                   "unless you renew manually from Account > Subscription.", email=False)
    db.flush()
    return True


# --- confirmation ----------------------------------------------------------------


def apply_successful_payment(db: Session, reference: str, amount_minor: int, currency: str, payload: dict,
                             paid_at: datetime | None = None, provider: str = "paystack") -> Subscription | None:
    """Idempotently mark an invoice paid and activate/extend the subscription."""
    inv = db.scalar(
        select(Invoice).where(Invoice.payment_provider == provider, Invoice.provider_reference == reference).with_for_update()
    )
    if inv is None:
        audit(db, "billing.unknown_reference", None, "invoice", reference)
        return None
    if inv.status == "paid":
        return db.get(Subscription, inv.subscription_id) if inv.subscription_id else None
    if amount_minor != inv.amount_minor or currency.upper() != inv.currency.upper():
        inv.status, inv.failure_reason = "failed", "amount or currency mismatch"
        audit(db, "billing.amount_mismatch", inv.user_id, "invoice", inv.id,
              {"expected": inv.amount_minor, "got": amount_minor, "currency": currency})
        return None
    now = paid_at or utcnow()
    plan = db.get(Plan, inv.plan_id)
    assert plan is not None
    sub = db.get(Subscription, inv.subscription_id) if (inv.kind == "renewal" and inv.subscription_id) else None
    if sub is None:
        sub = db.scalar(
            select(Subscription).where(Subscription.user_id == inv.user_id, Subscription.plan_id == plan.id,
                                       Subscription.status.in_(["active", "past_due"]))
        )
    period = PERIOD.get(plan.interval, timedelta(days=30))
    if sub is None:
        # Replacing another plan: end any other live subscription now.
        for other in db.scalars(select(Subscription).where(Subscription.user_id == inv.user_id,
                                                           Subscription.status.in_(LIVE_STATUSES))):
            other.status, other.current_period_end = "expired", now
        sub = Subscription(user_id=inv.user_id, plan_id=plan.id, status="active", current_period_start=now,
                           current_period_end=now + period, payment_provider=provider,
                           provider_customer_ref=str((payload.get("customer") or {}).get("customer_code") or "") or None)
        db.add(sub)
    else:  # renewal extends from the later of now / current end
        start = max(now, sub.current_period_end or now)
        sub.current_period_start, sub.current_period_end = start, start + period
        sub.cancel_at_period_end, sub.cancelled_at = False, None
    sub.status, sub.auto_renew = "active", True
    sub.renewal_attempts, sub.next_renewal_attempt_at, sub.past_due_since = 0, None, None
    db.flush()
    method = save_payment_method(db, inv.user_id, provider, payload.get("authorization"))
    inv.status, inv.paid_at, inv.subscription_id, inv.raw_payload, inv.failure_reason = "paid", now, sub.id, payload, None
    renews = ("It renews automatically" + (f" using your {method.brand} card ending {method.last4}" if method and method.last4 else "")
              + "; switch this off any time in Account > Subscription.") if (method or default_method(db, inv.user_id, provider)) else \
        "Renew from Account > Subscription before it ends to keep access."
    notify(db, inv.user_id, f"Payment received - {plan.name} plan active",
           f"Receipt {inv.provider_reference}: {_money(inv.amount_minor, inv.currency)} for the {plan.name} plan "
           f"({'renewal' if inv.kind == 'renewal' else 'new payment'}). Active until {sub.current_period_end:%d %b %Y}. {renews}")
    audit(db, "billing.payment_succeeded", inv.user_id, "invoice", inv.id, {"plan": plan.code, "kind": inv.kind})
    db.flush()
    return sub


# --- cancel / resume / auto-renew ------------------------------------------------


def cancel_subscription(db: Session, user: User) -> Subscription | None:
    sub = db.scalar(select(Subscription).where(Subscription.user_id == user.id, Subscription.status.in_(["active", "past_due"])))
    if sub is None:
        return None
    sub.status, sub.cancel_at_period_end, sub.cancelled_at = "cancelled", True, utcnow()
    sub.next_renewal_attempt_at = None
    audit(db, "billing.subscription_cancelled", user.id, "subscription", sub.id)
    db.flush()
    return sub


def resume_subscription(db: Session, user: User) -> Subscription | None:
    """Undo a cancellation while paid access remains. Auto-renewal resumes if a saved card exists."""
    sub = db.scalar(select(Subscription).where(Subscription.user_id == user.id, Subscription.status == "cancelled"))
    if sub is None or sub.current_period_end is None or sub.current_period_end <= utcnow():
        return None
    sub.status, sub.cancel_at_period_end, sub.cancelled_at = "active", False, None
    audit(db, "billing.subscription_resumed", user.id, "subscription", sub.id)
    db.flush()
    return sub


def set_auto_renew(db: Session, user: User, enabled: bool) -> Subscription | None:
    sub = db.scalar(select(Subscription).where(Subscription.user_id == user.id, Subscription.status.in_(["active", "past_due"])))
    if sub is None:
        return None
    sub.auto_renew = enabled
    if not enabled:
        sub.next_renewal_attempt_at = None
    audit(db, "billing.auto_renew_changed", user.id, "subscription", sub.id, {"enabled": enabled})
    db.flush()
    return sub


# --- auto-renewal ------------------------------------------------------------------


def _is_renewable(db: Session, sub: Subscription) -> bool:
    s = get_settings()
    return (sub.status in ("active", "past_due") and sub.auto_renew and not sub.cancel_at_period_end
            and sub.renewal_attempts < s.renewal_max_attempts and sub.plan.price_minor > 0
            and default_method(db, sub.user_id, s.payment_provider) is not None)


def _fail_renewal(db: Session, sub: Subscription, inv: Invoice, reason: str, now: datetime) -> None:
    s = get_settings()
    inv.status, inv.failure_reason = "failed", (reason or "declined")[:200]
    end = sub.current_period_end or now
    if now >= end:
        sub.status = "past_due"
        sub.past_due_since = sub.past_due_since or now
    left = s.renewal_max_attempts - sub.renewal_attempts
    grace_end = end + timedelta(days=s.renewal_grace_days)
    if left > 0:
        sub.next_renewal_attempt_at = now + timedelta(hours=s.renewal_retry_hours)
        body = (f"We could not renew your {sub.plan.name} plan ({inv.failure_reason}). We will try again on "
                f"{sub.next_renewal_attempt_at:%d %b %Y %H:%M} UTC. You can also pay now from Account > Subscription "
                f"(access continues until {grace_end:%d %b %Y}).")
        title = "We couldn't renew your plan"
    else:
        sub.next_renewal_attempt_at = None
        body = (f"Your {sub.plan.name} plan could not be renewed after {s.renewal_max_attempts} attempts. Access ends on "
                f"{grace_end:%d %b %Y} unless you update payment from Account > Subscription.")
        title = "Renewal failed - action needed"
    notify(db, sub.user_id, title, body)
    audit(db, "billing.renewal_failed", sub.user_id, "invoice", inv.id, {"reason": inv.failure_reason, "attempt": sub.renewal_attempts})


def _resolve_pending(db: Session, sub: Subscription, client, now: datetime, stats: dict) -> bool:
    """Settle a renewal charge the provider left pending. Returns True if one is still unresolved (do not charge again)."""
    inv = db.scalar(select(Invoice).where(Invoice.subscription_id == sub.id, Invoice.kind == "renewal", Invoice.status == "pending")
                    .order_by(Invoice.id.desc()))
    if inv is None:
        return False
    try:
        data = client.verify(inv.provider_reference)
    except (PaymentError, httpx.HTTPError) as exc:
        log.warning("renewal_verify_failed", reference=inv.provider_reference, error=str(exc))
        sub.next_renewal_attempt_at = now + timedelta(hours=1)
        return True
    status = data.get("status")
    if status == "success":
        if apply_successful_payment(db, inv.provider_reference, int(data.get("amount") or inv.amount_minor),
                                    data.get("currency") or inv.currency, data, paid_at=now, provider=inv.payment_provider):
            stats["charged"] += 1
        else:
            _fail_renewal(db, sub, inv, "amount mismatch", now)
            stats["failed"] += 1
        return True
    if status in PENDING_STATES and now - inv.created_at < timedelta(hours=12):
        sub.next_renewal_attempt_at = now + timedelta(hours=2)
        return True
    _fail_renewal(db, sub, inv, str(data.get("gateway_response") or status or "not completed"), now)
    stats["failed"] += 1
    return True


def _attempt_renewal(db: Session, sub: Subscription, method: PaymentMethod, client, now: datetime, stats: dict) -> None:
    s = get_settings()
    plan = sub.plan
    sub.renewal_attempts += 1
    reference = f"f5r-{sub.id}-{int((sub.current_period_end or now).timestamp())}-{sub.renewal_attempts}"
    inv = Invoice(user_id=sub.user_id, subscription_id=sub.id, plan_id=plan.id, amount_minor=plan.price_minor,
                  currency=plan.currency, status="pending", payment_provider=method.provider, provider_reference=reference,
                  kind="renewal")
    db.add(inv)
    sub.next_renewal_attempt_at = now + timedelta(hours=s.renewal_retry_hours)
    audit(db, "billing.renewal_attempt", sub.user_id, "invoice", reference, {"attempt": sub.renewal_attempts})
    db.commit()  # the charge reference is durable before the provider is contacted
    try:
        data = client.charge_authorization(email=sub.user.email, amount_minor=plan.price_minor, currency=plan.currency,
                                           authorization_code=method.authorization_code, reference=reference,
                                           metadata={"user_id": sub.user_id, "plan_code": plan.code, "renewal": True})
    except (PaymentError, httpx.HTTPError) as exc:
        data = {"status": "failed", "gateway_response": f"provider error: {exc}"}
    status = data.get("status")
    if status == "success":
        ok = apply_successful_payment(db, reference, int(data.get("amount") or plan.price_minor),
                                      data.get("currency") or plan.currency, data, paid_at=now, provider=method.provider)
        if ok is not None:
            stats["charged"] += 1
            return
        _fail_renewal(db, sub, inv, "amount mismatch", now)
    elif status in PENDING_STATES:
        sub.next_renewal_attempt_at = now + timedelta(hours=2)
        stats["pending"] += 1
        return
    else:
        _fail_renewal(db, sub, inv, str(data.get("gateway_response") or data.get("message") or status or "declined"), now)
    stats["failed"] += 1


def renew_due_subscriptions(db: Session, client=None, now: datetime | None = None) -> dict:
    """Charge saved authorisations for subscriptions entering (or past) their renewal window."""
    s = get_settings()
    now = now or utcnow()
    stats = {"charged": 0, "failed": 0, "pending": 0, "no_card": 0, "skipped": None}
    ids = [i for (i,) in db.execute(
        select(Subscription.id).where(Subscription.status.in_(["active", "past_due"]), Subscription.auto_renew.is_(True),
                                      Subscription.cancel_at_period_end.is_(False), Subscription.current_period_end.isnot(None),
                                      Subscription.current_period_end <= now + timedelta(hours=s.renewal_lead_hours)))]
    if not ids:
        return stats
    try:
        client = client or get_payment_client()
    except PaymentNotConfigured as exc:
        stats["skipped"] = str(exc)
        return stats
    for sid in ids:
        sub = db.scalar(select(Subscription).where(Subscription.id == sid).with_for_update(of=Subscription))
        if sub is None or sub.status not in ("active", "past_due") or not sub.auto_renew or sub.cancel_at_period_end:
            continue
        if sub.next_renewal_attempt_at and sub.next_renewal_attempt_at > now:
            continue
        if sub.status == "past_due" and sub.current_period_end + timedelta(days=s.renewal_grace_days) <= now:
            continue
        try:
            if _resolve_pending(db, sub, client, now, stats):
                db.commit()
                continue
            if sub.renewal_attempts >= s.renewal_max_attempts or sub.plan.price_minor <= 0:
                continue
            method = default_method(db, sub.user_id, s.payment_provider)
            if method is None:
                stats["no_card"] += 1
                continue
            _attempt_renewal(db, sub, method, client, now, stats)
            db.commit()
        except Exception:  # noqa: BLE001 - one broken subscription must not block the rest
            db.rollback()
            log.exception("renewal_failed_unexpectedly", subscription_id=sid)
    return stats


def send_renewal_reminders(db: Session, now: datetime | None = None) -> int:
    """One reminder per billing period, ``renewal_reminder_days`` before it ends."""
    s = get_settings()
    now = now or utcnow()
    subs = db.scalars(select(Subscription).where(
        Subscription.status.in_(["active", "cancelled"]), Subscription.current_period_end > now,
        Subscription.current_period_end <= now + timedelta(days=s.renewal_reminder_days))).all()
    sent = 0
    for sub in subs:
        if sub.reminder_sent_for == sub.current_period_end:
            continue
        end = sub.current_period_end
        plan = sub.plan
        if sub.status == "cancelled" or sub.cancel_at_period_end:
            title = f"Your {plan.name} plan ends soon"
            body = f"Your {plan.name} plan ends on {end:%d %b %Y} and will not renew. You can resume it from Account > Subscription."
        elif _is_renewable(db, sub):
            m = default_method(db, sub.user_id, s.payment_provider)
            title = f"Your {plan.name} plan renews soon"
            body = (f"{_money(plan.price_minor, plan.currency)} will be charged to your {m.brand} card ending {m.last4} on "
                    f"{end:%d %b %Y}. To stop this, turn off auto-renew or cancel in Account > Subscription.")
        else:
            title = f"Your {plan.name} plan expires soon"
            body = (f"Your {plan.name} plan expires on {end:%d %b %Y} and will not renew automatically. "
                    "Renew from Account > Subscription to keep access.")
        notify(db, sub.user_id, title, body)
        sub.reminder_sent_for = end
        sent += 1
    db.flush()
    return sent


def expire_subscriptions(db: Session, now: datetime | None = None) -> int:
    """End plans whose paid period (plus any dunning grace) is over. Renewable plans become ``past_due`` instead."""
    s = get_settings()
    now = now or utcnow()
    subs = db.scalars(select(Subscription).where(Subscription.status.in_(LIVE_STATUSES),
                                                 Subscription.current_period_end <= now)).all()
    expired = 0
    for sub in subs:
        if sub.status == "past_due":
            if now < sub.current_period_end + timedelta(days=s.renewal_grace_days):
                continue
        elif sub.status == "active" and _is_renewable(db, sub):
            sub.status, sub.past_due_since = "past_due", sub.past_due_since or now
            continue
        was_failed = sub.status == "past_due"
        sub.status, sub.next_renewal_attempt_at = "expired", None
        notify(db, sub.user_id, "Subscription expired",
               f"Your {sub.plan.name} plan has ended" + (" because payment could not be collected" if was_failed else "")
               + ". Renew to restore access.", link="/pricing")
        expired += 1
    db.flush()
    return expired
