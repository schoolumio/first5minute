"""DEMO payment provider - a local simulator for testing subscriptions without a payment account.

No money moves and no external service is called. It behaves like the Paystack client for the calls the app makes, and
the "checkout page" is a First5Minute page where the tester chooses a simulated card:

* ``works``      - every renewal charge succeeds
* ``declines``   - the first payment succeeds, every later (renewal) charge is declined: exercises retries and grace

Refused when ``ENVIRONMENT=production`` (see ``Settings.validate_production``).
"""

from __future__ import annotations

from app.core.config import get_settings

DEMO_CARDS = {
    "works": {"brand": "visa", "last4": "4081", "label": "Visa ending 4081 - renewals succeed"},
    "declines": {"brand": "mastercard", "last4": "0408", "label": "Mastercard ending 0408 - renewals are declined"},
}


def demo_authorization(card: str, reference: str) -> dict:
    meta = DEMO_CARDS[card]
    return {"authorization_code": f"AUTH_demo_{card}_{reference[-8:]}", "reusable": True, "signature": f"SIG_demo_{card}",
            "brand": meta["brand"], "last4": meta["last4"], "exp_month": "12", "exp_year": "2030", "bank": "DEMO BANK"}


class DemoPaymentClient:
    """Mirror of PaystackClient's surface; state lives in the app database (invoices/payment methods)."""

    def __init__(self) -> None:
        self.base = get_settings().frontend_url

    def initialize(self, email: str, amount_minor: int, currency: str, reference: str, callback_url: str,
                   metadata: dict) -> dict:
        return {"authorization_url": f"{self.base}/account/demo-checkout?reference={reference}", "reference": reference}

    def verify(self, reference: str) -> dict:
        # A demo checkout is completed by the tester through POST /subscriptions/demo/complete, which applies the payment
        # itself - so a verify for an unpaid demo reference is simply "not paid yet".
        return {"status": "abandoned", "reference": reference}

    def charge_authorization(self, email: str, amount_minor: int, currency: str, authorization_code: str, reference: str,
                             metadata: dict) -> dict:
        base = {"reference": reference, "amount": amount_minor, "currency": currency, "customer": {"customer_code": "CUS_demo"}}
        if "_declines_" in authorization_code:
            return base | {"status": "failed", "gateway_response": "Declined (demo card: renewals are declined)"}
        return base | {"status": "success", "gateway_response": "Approved (demo)",
                       "authorization": {"authorization_code": authorization_code}}
