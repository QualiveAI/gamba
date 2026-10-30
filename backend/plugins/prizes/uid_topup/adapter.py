import os
import uuid
import asyncio

import httpx

from core.contracts.prize import DeliveryResult, VerificationResult
from core.ops.exceptions import SupplierDown, OutOfStock


class UidTopupChannel:
    MANIFEST = {"key": "uid_topup", "type": "prize", "contract_version": 1, "enabled_env": "TOPUP_ENABLED"}
    channel_key = "uid_topup"

    def __init__(self):
        self._validate_cache = {}

    async def validate(self, uid, game):
        cache_key = f"{game}:{uid}"
        if cache_key in self._validate_cache:
            return self._validate_cache[cache_key]
        url = os.getenv("TOPUP_PROVIDER_URL", "")
        key = os.getenv("TOPUP_PROVIDER_KEY", "")
        if not url:
            result = True
            self._validate_cache[cache_key] = result
            return result
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.post(
                    f"{url}/validate",
                    json={"uid": uid, "game": game},
                    headers={"X-API-Key": key},
                )
                result = resp.status_code == 200 and resp.json().get("valid", False)
        except Exception:
            result = False
        self._validate_cache[cache_key] = result
        return result

    async def deliver(self, prize_quote, user_ref, idempotency_key=None):
        if idempotency_key is None:
            idempotency_key = str(uuid.uuid4())
        url = os.getenv("TOPUP_PROVIDER_URL", "")
        key = os.getenv("TOPUP_PROVIDER_KEY", "")
        if not url:
            return DeliveryResult(f"topup_{idempotency_key}", "pending")
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    resp = await client.post(
                        f"{url}/order",
                        json={
                            "user_ref": user_ref,
                            "amount": getattr(prize_quote, "amount_units", getattr(prize_quote, "nominal_units", 0)),
                            "idempotency_key": idempotency_key,
                        },
                        headers={"X-API-Key": key},
                    )
                    if resp.status_code == 404:
                        raise OutOfStock("out of stock")
                    resp.raise_for_status()
                    data = resp.json()
                    return DeliveryResult(data.get("order_id", idempotency_key), "pending")
            except OutOfStock:
                raise
            except Exception as e:
                if attempt == 1:
                    raise SupplierDown(str(e))
                await asyncio.sleep(0.1)
        raise SupplierDown("max retries")

    async def verify(self, delivery_id):
        url = os.getenv("TOPUP_PROVIDER_URL", "")
        key = os.getenv("TOPUP_PROVIDER_KEY", "")
        if not url:
            return VerificationResult(delivery_id, True, True, "ok")
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(
                    f"{url}/order/{delivery_id}",
                    headers={"X-API-Key": key},
                )
                data = resp.json()
                status = data.get("status", "pending")
                terminal = status in ("activated", "failed")
                return VerificationResult(delivery_id, terminal, status == "activated", status)
        except Exception:
            return VerificationResult(delivery_id, False, False, "error")

    def verify_delivery(self, delivery_id):
        return VerificationResult(delivery_id, True, True, "ok")


def register(reg):
    reg.register(UidTopupChannel())