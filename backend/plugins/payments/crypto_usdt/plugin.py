import hashlib
import hmac
import json
import os

from core.contracts.payment import PaymentIntent, PaymentStatus, WebhookOutcome


class CryptoUsdtAdapter:
    MANIFEST = {
        "key": "crypto_usdt",
        "type": "payment",
        "geo": "*",
        "version": "1",
        "enabled_env": None,
    }
    rail_key = "crypto_usdt"
    geo = "*"
    methods = []
    refund_supported = False

    def create_payment(self, user_id, amount_minor, currency, idempotency_key):
        api_key = os.getenv("COINSO_API_KEY") or os.getenv("EPAYVISTA_API_KEY", "")
        # mock-friendly
        if not api_key:
            return PaymentIntent(
                idempotency_key,
                "crypto_usdt",
                amount_minor,
                currency,
                {"address": "DUMMY", "memo": idempotency_key},
            )
        return PaymentIntent(
            idempotency_key,
            "crypto_usdt",
            amount_minor,
            currency,
            {"address": "ADDR", "memo": idempotency_key},
        )

    def poll_payment(self, intent_id):
        return PaymentStatus(intent_id, "pending", 0)

    def handle_webhook(self, headers, body):
        secret = os.getenv("CRYPTO_WEBHOOK_SECRET", "")
        sig = headers.get("x-signature", "")
        calc = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        if secret and not hmac.compare_digest(calc, sig):
            raise ValueError("bad signature")  # noqa: B904
        data = json.loads(body)
        return WebhookOutcome(
            data.get("intent_id"), data.get("event_id", ""), data.get("status", "succeeded"), True
        )


def register(reg):
    reg.register(CryptoUsdtAdapter())
