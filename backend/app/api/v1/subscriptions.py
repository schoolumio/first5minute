"""Plans, checkout, Paystack webhook, cancellation and invoice history."""

from __future__ import annotations

import json
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_verified
from app.core.config import get_settings
from app.core.database import get_db
from app.core.logging import get_logger
from app.models import Invoice, Plan, User
from app.providers.payments import get_payment_client
from app.providers.payments.paystack import PaymentError, PaymentNotConfigured, verify_webhook_signature
from app.services import billing
from app.services.audit import audit
from app.services.entitlements import FEATURE_LABELS, active_subscription, entitlements

router = APIRouter(tags=["subscriptions"])
log = get_logger(__name__)


def plan_out(p: Plan) -> dict:
    return {"code": p.code, "name": p.name, "description": p.description, "price_minor": p.price_minor,
            "price": p.price_minor / 100, "currency": p.currency, "interval": p.interval, "rank": p.rank,
            "features": p.features, "is_active": p.is_active}


@router.get("/plans")
def list_plans(db: Session = Depends(get_db)) -> dict:
    plans = db.scalars(select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.rank)).all()
    return {"plans": [plan_out(p) for p in plans], "feature_labels": FEATURE_LABELS,
            "payments_enabled": get_settings().payment_provider != "none"}


@router.get("/subscriptions")
def my_subscription(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    sub = active_subscription(db, user)
    settings = get_settings()
    methods = billing.list_methods(db, user.id)
    renewal = None
    if sub is not None and sub.current_period_end is not None:
        grace_end = sub.current_period_end + timedelta(days=settings.renewal_grace_days)
        will_auto = billing._is_renewable(db, sub)  # noqa: SLF001 - one definition of "will this plan auto-renew?"
        renewal = {"auto_renew": sub.auto_renew, "will_auto_renew": will_auto, "attempts": sub.renewal_attempts,
                   "max_attempts": settings.renewal_max_attempts,
                   "next_attempt_at": sub.next_renewal_attempt_at.isoformat() if sub.next_renewal_attempt_at else None,
                   "past_due": sub.status == "past_due",
                   "access_until": (grace_end if sub.status == "past_due" else sub.current_period_end).isoformat()}
    invoices = db.scalars(select(Invoice).where(Invoice.user_id == user.id).order_by(Invoice.created_at.desc()).limit(50)).all()
    return {
        "entitlements": entitlements(db, user),
        "subscription": {
            "id": sub.id, "plan": plan_out(sub.plan), "status": sub.status,
            "current_period_start": sub.current_period_start.isoformat() if sub.current_period_start else None,
            "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
            "cancel_at_period_end": sub.cancel_at_period_end,
        } if sub else None,
        "renewal": renewal,
        "payment_methods": [{"id": m.id, "brand": m.brand, "last4": m.last4, "exp_month": m.exp_month, "exp_year": m.exp_year,
                             "is_default": m.is_default, "is_demo": m.is_demo} for m in methods],
        "payment_provider": settings.payment_provider,
        "invoices": [{"id": i.id, "amount": i.amount_minor / 100, "currency": i.currency, "status": i.status,
                      "reference": i.provider_reference, "kind": i.kind, "failure_reason": i.failure_reason,
                      "created_at": i.created_at.isoformat(),
                      "paid_at": i.paid_at.isoformat() if i.paid_at else None} for i in invoices],
        "payments_enabled": settings.payment_provider != "none",
    }


class CheckoutIn(BaseModel):
    plan_code: str = Field(pattern="^(starter|pro|elite)$")


@router.post("/subscriptions/checkout")
def checkout(body: CheckoutIn, user: User = Depends(require_verified), db: Session = Depends(get_db)) -> dict:
    plan = db.scalar(select(Plan).where(Plan.code == body.plan_code, Plan.is_active.is_(True)))
    if plan is None:
        raise HTTPException(404, "Plan not found")
    try:
        result = billing.start_checkout(db, user, plan)
    except PaymentNotConfigured as exc:
        raise HTTPException(503, f"Payments are not configured on this environment. {exc}") from exc
    except PaymentError as exc:
        raise HTTPException(502, f"Payment provider error: {exc}") from exc
    db.commit()
    return result


@router.get("/subscriptions/verify/{reference}")
def verify_payment(reference: str, user: User = Depends(require_verified), db: Session = Depends(get_db)) -> dict:
    """Called after redirect back from checkout; confirms with Paystack server-side."""
    inv = db.scalar(select(Invoice).where(Invoice.provider_reference == reference, Invoice.user_id == user.id))
    if inv is None:
        raise HTTPException(404, "Payment not found")
    if inv.status != "paid":
        try:
            data = get_payment_client().verify(reference)
        except PaymentNotConfigured as exc:
            raise HTTPException(503, str(exc)) from exc
        except PaymentError as exc:
            raise HTTPException(502, f"Payment provider error: {exc}") from exc
        if data.get("status") == "success":
            billing.apply_successful_payment(db, reference, int(data["amount"]), data["currency"], data,
                                             provider=inv.payment_provider)
            db.commit()
    db.refresh(inv)
    return {"status": inv.status}


@router.post("/subscriptions/cancel")
def cancel(user: User = Depends(require_verified), db: Session = Depends(get_db)) -> dict:
    sub = billing.cancel_subscription(db, user)
    if sub is None:
        raise HTTPException(404, "No active subscription")
    db.commit()
    return {"message": f"Cancelled. Access continues until {sub.current_period_end:%d %b %Y}."}


@router.post("/subscriptions/resume")
def resume(user: User = Depends(require_verified), db: Session = Depends(get_db)) -> dict:
    sub = billing.resume_subscription(db, user)
    if sub is None:
        raise HTTPException(404, "No cancelled subscription with paid time remaining")
    db.commit()
    return {"message": "Subscription resumed."}


class AutoRenewIn(BaseModel):
    enabled: bool


@router.post("/subscriptions/auto-renew")
def auto_renew(body: AutoRenewIn, user: User = Depends(require_verified), db: Session = Depends(get_db)) -> dict:
    sub = billing.set_auto_renew(db, user, body.enabled)
    if sub is None:
        raise HTTPException(404, "No active subscription")
    db.commit()
    return {"auto_renew": sub.auto_renew}


@router.delete("/subscriptions/payment-methods/{method_id}")
def remove_method(method_id: int, user: User = Depends(require_verified), db: Session = Depends(get_db)) -> dict:
    if not billing.remove_payment_method(db, user, method_id):
        raise HTTPException(404, "Payment method not found")
    db.commit()
    return {"removed": True}


class DemoCompleteIn(BaseModel):
    reference: str
    card: str = Field(pattern="^(works|declines)$")


@router.post("/subscriptions/demo/complete")
def demo_complete(body: DemoCompleteIn, user: User = Depends(require_verified), db: Session = Depends(get_db)) -> dict:
    """DEMO payments only: the simulated checkout page calls this to "pay" with a chosen test card."""
    from app.providers.payments.demo import demo_authorization

    if get_settings().payment_provider != "demo":
        raise HTTPException(404, "Not found")
    inv = db.scalar(select(Invoice).where(Invoice.provider_reference == body.reference, Invoice.user_id == user.id,
                                          Invoice.payment_provider == "demo"))
    if inv is None:
        raise HTTPException(404, "Payment not found")
    payload = {"reference": inv.provider_reference, "demo": True, "customer": {"customer_code": "CUS_demo"},
               "authorization": demo_authorization(body.card, inv.provider_reference)}
    billing.apply_successful_payment(db, inv.provider_reference, inv.amount_minor, inv.currency, payload, provider="demo")
    db.commit()
    db.refresh(inv)
    return {"status": inv.status, "demo": True}


@router.post("/webhooks/paystack", include_in_schema=False)
async def paystack_webhook(request: Request, db: Session = Depends(get_db)) -> dict:
    raw = await request.body()
    if not verify_webhook_signature(raw, request.headers.get("x-paystack-signature")):
        audit(db, "billing.webhook_invalid_signature", None, "webhook", None, ip=request.client.host if request.client else None)
        db.commit()
        raise HTTPException(401, "Invalid signature")
    try:
        event = json.loads(raw)
    except ValueError as exc:
        raise HTTPException(400, "Invalid JSON") from exc
    kind = event.get("event")
    data = event.get("data") or {}
    if kind == "charge.success":
        billing.apply_successful_payment(db, data.get("reference", ""), int(data.get("amount") or 0),
                                         data.get("currency") or "", data)
    else:
        audit(db, "billing.webhook_ignored", None, "webhook", kind)
    db.commit()
    return {"received": True}
