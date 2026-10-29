import os
import uuid

import httpx

from core.contracts.prize import DeliveryResult, VerificationResult


class UidTopupChannel:
    MANIFEST = {
        "key": "uid_topup",
        "type": "prize",
        "geo": None,
        "version": "1",
        "enabled_env": None,
    }
    channel_key = "uid_topup"

    def deliver(self, prize_quote, user_ref):
        url = os.getenv("TOPUP_PROVIDER_URL", "")
        key = os.getenv("TOPUP_PROVIDER_KEY", "")
        idem = str(uuid.uuid4())
        if not url:
            return DeliveryResult(f"topup_{idem}", "success")
        resp = httpx.post(
            url,
            json={
                "user_ref": user_ref,
                "amount": getattr(prize_quote, "amount_units", 0),
                "idempotency_key": idem,
            },
            headers={"X-API-Key": key},
        )
        resp.raise_for_status()
        data = resp.json()
        return DeliveryResult(data.get("order_id", idem), data.get("status", "pending"))

    def verify_delivery(self, delivery_id):
        return VerificationResult(delivery_id, True, "ok")


def register(reg):
    reg.register(UidTopupChannel())
