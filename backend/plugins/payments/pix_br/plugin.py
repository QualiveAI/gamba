import hashlib
import hmac
import json
import os

import httpx

from core.contracts.payment import PaymentIntent, PaymentStatus, WebhookOutcome


class PixBrAdapter:
    MANIFEST = {"key": "pix", "type": "payment", "geo": "BR", "version": "1", "enabled_env": None}
    rail_key = "pix"
    geo = "BR"
    methods = []
    refund_supported = False

    def create_payment(self, user_id, amount_minor, currency, idempotency_key):
        psp_url = os.getenv("PIX_PSP_URL", "")
        psp_key = os.getenv("PIX_PSP_KEY", "")
        if not psp_url:
            return PaymentIntent(
                idempotency_key, "pix", amount_minor, currency, {"qr": "DUMMY_PIX"}
            )
        resp = httpx.post(
            psp_url,
            json={"amount": amount_minor, "currency": currency, "user_id": user_id},
            headers={"X-API-Key": psp_key, "Idempotency-Key": idempotency_key},
        )
        resp.raise_for_status()
        data = resp.json()
        return PaymentIntent(idempotency_key, "pix", amount_minor, currency, {"qr": data.get("qr")})

    def poll_payment(self, intent_id):
        return PaymentStatus(intent_id, "pending", 0)

    def handle_webhook(self, headers, body):
        secret = os.getenv("PIX_WEBHOOK_SECRET", "")
        sig = headers.get("x-signature", "")
        calc = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        if secret and not hmac.compare_digest(calc, sig):
            raise ValueError("bad signature")  # noqa: B904
        data = json.loads(body)
        return WebhookOutcome(
            data.get("intent_id"), data.get("event_id", ""), data.get("status", "succeeded"), True
        )


def register(reg):
    reg.register(PixBrAdapter())
