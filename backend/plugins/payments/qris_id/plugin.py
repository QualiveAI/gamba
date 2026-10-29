import hashlib
import hmac
import json
import os

import httpx

from core.contracts.payment import PaymentIntent, PaymentStatus, WebhookOutcome
from core.observability.metrics import inc


class QrisIdAdapter:
    MANIFEST = {
        "key": "qris",
        "type": "payment",
        "geo": "ID",
        "version": "1",
        "enabled_env": None,
        "contract_version": "1",
    }
    rail_key = "qris"
    geo = "ID"
    methods = []
    refund_supported = False

    _fail_count = 0

    def create_payment(self, user_id, amount_minor, currency, idempotency_key):
        url = os.getenv("QRIS_PSP_URL", "")
        if not url:
            return PaymentIntent(
                idempotency_key, "qris", amount_minor, currency, {"qr": "DUMMY_QRIS"}
            )
        try:
            resp = httpx.post(
                url,
                json={"amount": amount_minor, "currency": currency, "user_id": user_id},
                timeout=8.0,
            )
            resp.raise_for_status()
            self._fail_count = 0
            data = resp.json()
            return PaymentIntent(
                idempotency_key, "qris", amount_minor, currency, {"qr": data.get("qr")}
            )
        except httpx.HTTPStatusError:
            self._fail_count += 1
            if self._fail_count >= 3:
                inc("rail_degraded", {"rail": "qris"})
            raise

    def poll_payment(self, intent_id):
        return PaymentStatus(intent_id, "pending", 0)

    def handle_webhook(self, headers, body):
        secret = os.getenv("QRIS_WEBHOOK_SECRET", "")
        sig = headers.get("x-signature", "")
        calc = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        if secret and not hmac.compare_digest(calc, sig):
            raise ValueError("bad signature")  # noqa: B904
        data = json.loads(body)
        return WebhookOutcome(
            data.get("intent_id"), data.get("event_id", ""), data.get("status", "succeeded"), True
        )


def register(reg):
    reg.register(QrisIdAdapter())
