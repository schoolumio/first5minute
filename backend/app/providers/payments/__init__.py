"""Payment providers."""

from __future__ import annotations

from app.core.config import get_settings
from app.providers.payments.paystack import PaymentNotConfigured


def get_payment_client():
    """Return the configured payment client (Paystack or the local demo simulator)."""
    provider = get_settings().payment_provider
    if provider == "demo":
        from app.providers.payments.demo import DemoPaymentClient

        return DemoPaymentClient()
    if provider == "paystack":
        from app.providers.payments.paystack import PaystackClient

        return PaystackClient()
    raise PaymentNotConfigured("Payments are not configured (set PAYMENT_PROVIDER=paystack and PAYSTACK_SECRET_KEY)")
