"""Paystack payment provider (Nigerian + international cards, bank, USSD, transfer).

Docs: https://paystack.com/docs/api/
  POST /transaction/initialize        start checkout, returns authorization_url
  GET  /transaction/verify/{ref}      confirm payment server-side
Webhooks are signed with HMAC-SHA512 of the raw body using the secret key,
sent in the ``x-paystack-signature`` header.
"""

from __future__ import annotations

import hashlib
import hmac

import httpx

from app.core.config import get_settings


class PaymentNotConfigured(Exception):
    pass


class PaymentError(Exception):
    pass


def verify_webhook_signature(raw_body: bytes, signature: str | None, secret: str | None = None) -> bool:
    secret = secret or get_settings().paystack_secret_key
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature)


class PaystackClient:
    def __init__(self, transport: httpx.BaseTransport | None = None):
        s = get_settings()
        if s.payment_provider != "paystack" or not s.paystack_secret_key:
            raise PaymentNotConfigured("Paystack is not configured (set PAYMENT_PROVIDER=paystack and PAYSTACK_SECRET_KEY)")
        self.client = httpx.Client(
            base_url=s.paystack_base_url,
            headers={"Authorization": f"Bearer {s.paystack_secret_key}"},
            timeout=20.0,
            transport=transport,
        )

    def initialize(self, email: str, amount_minor: int, currency: str, reference: str, callback_url: str,
                   metadata: dict) -> dict:
        resp = self.client.post("/transaction/initialize", json={
            "email": email, "amount": amount_minor, "currency": currency, "reference": reference,
            "callback_url": callback_url, "metadata": metadata,
        })
        data = resp.json()
        if resp.status_code >= 400 or not data.get("status"):
            raise PaymentError(data.get("message") or f"HTTP {resp.status_code}")
        return data["data"]

    def verify(self, reference: str) -> dict:
        resp = self.client.get(f"/transaction/verify/{reference}")
        data = resp.json()
        if resp.status_code >= 400 or not data.get("status"):
            raise PaymentError(data.get("message") or f"HTTP {resp.status_code}")
        return data["data"]
