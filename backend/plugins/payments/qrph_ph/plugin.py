import hashlib
import hmac
import json
import os

import httpx

from core.contracts.payment import PaymentIntent, PaymentStatus, WebhookOutcome


class QrphPhAdapter:
    MANIFEST = {
        "key": "qrph",
        "type": "payment",
        "geo": "PH",
        "version": "1",
        "enabled_env": None,
        "contract_version": "1",
    }
    rail_key = "qrph"
    geo = "PH"
    methods = []
    refund_supported = False

    def create_payment(self, user_id, amount_minor, currency, idempotency_key):
        url = os.getenv("QRPH_PSP_URL", "")
        if not url:
            return PaymentIntent(
                idempotency_key, "qrph", amount_minor, currency, {"qr": "DUMMY_QRPH"}
            )
        resp = httpx.post(
            url,
            json={"amount": amount_minor, "currency": currency, "user_id": user_id},
            timeout=8.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return PaymentIntent(
            idempotency_key, "qrph", amount_minor, currency, {"qr": data.get("qr")}
        )

    def poll_payment(self, intent_id):
        return PaymentStatus(intent_id, "pending", 0)

    def handle_webhook(self, headers, body):
        secret = os.getenv("QRPH_WEBHOOK_SECRET", "")
        sig = headers.get("x-signature", "")
        calc = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        if secret and not hmac.compare_digest(calc, sig):
            raise ValueError("bad signature")  # noqa: B904
        data = json.loads(body)
        return WebhookOutcome(
            data.get("intent_id"), data.get("event_id", ""), data.get("status", "succeeded"), True
        )


def register(reg):
    reg.register(QrphPhAdapter())
