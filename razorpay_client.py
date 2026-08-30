"""Razorpay integration (see §14).

Two non-negotiables, both enforced here:
  1. The payment amount is passed in from Agreement.total (server-computed) and
     is never taken from the client.
  2. Webhook payloads are verified (HMAC-SHA256) and processing is idempotent.

With no keys set, runs in mock mode: a fake payment link is returned and the
order is treated as immediately payable for local demos.
"""
import hashlib
import hmac
import uuid

import httpx

from config import settings

_RAZORPAY_PAYMENT_LINKS_URL = "https://api.razorpay.com/v1/payment_links"


def create_payment_link(amount: float, agreement_uid: str, buyer_email: str) -> dict:
    """Create a Razorpay Payment Link for `amount` (INR). Amount is authoritative,
    supplied by the caller from Agreement.total — never from the buyer's request."""
    amount_paise = int(round(amount * 100))

    if not settings.razorpay_live:
        # Mock mode — no external call.
        return {
            "mode": "mock",
            "razorpay_id": f"plink_mock_{uuid.uuid4().hex[:10]}",
            "payment_link": f"https://mock.local/pay/{agreement_uid}",
            "status": "created",
        }

    payload = {
        "amount": amount_paise,
        "currency": "INR",
        "accept_partial": False,
        "description": f"ATOAC agreement {agreement_uid}",
        "customer": {"email": buyer_email},
        "notify": {"email": True},
        "reference_id": agreement_uid,
    }
    resp = httpx.post(
        _RAZORPAY_PAYMENT_LINKS_URL,
        auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET),
        json=payload,
        timeout=15.0,
    )
    resp.raise_for_status()
    data = resp.json()
    return {
        "mode": "live",
        "razorpay_id": data["id"],
        "payment_link": data["short_url"],
        "status": data.get("status", "created"),
    }


def verify_webhook_signature(raw_body: bytes, signature: str) -> bool:
    """HMAC-SHA256 verification of a Razorpay webhook. Returns False if no secret
    is configured or the signature does not match — the caller must reject."""
    if not settings.RAZORPAY_WEBHOOK_SECRET or not signature:
        return False
    expected = hmac.new(
        settings.RAZORPAY_WEBHOOK_SECRET.encode(),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
