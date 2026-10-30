import hashlib
import hmac
import json
import time
from typing import Optional

import httpx

from core.contracts.payment import PaymentIntent, PaymentStatus, WebhookOutcome


class UnsupportedRegion(Exception):
    pass


class SupplierDown(Exception):
    pass


class GowdLatamAdapter:
    MANIFEST = {
        "key": "gowd_latam",
        "type": "payment",
        "geo": ["BR", "MX"],
        "methods": ["pix", "spei"],
        "contract_version": 1,
        "enabled_env": "GOWD_ENABLED",
    }
    rail_key = "gowd_latam"
    geo = ["BR", "MX"]
    methods = ["pix", "spei"]
    refund_supported = False

    def create_payment(self, user_id: int, amount_minor: int, currency: str, idempotency_key: str) -> PaymentIntent:
        """Create a payment via GOWD API."""
        gowd_url = "https://api.gowd.com"  # placeholder; real URL from env
        gowd_key = "test-key"  # placeholder; real key from env

        # Determine method
        method = "pix"  # default; will be adjusted based on geo

        body = {
            "amount": amount_minor,
            "currency": currency,
            "method": method,
            "external_id": idempotency_key,
            "callback_url": f"https://api.caseplatform.com/webhook/gowd_latam",
        }

        attempts = 0
        max_attempts = 2
        last_error: Optional[httpx.HTTPError] = None

        while attempts < max_attempts:
            try:
                resp = httpx.post(
                    f"{gowd_url}/v1/payments",
                    json=body,
                    headers={"Authorization": f"Bearer {gowd_key}"},
                    timeout=10.0,
                )
                resp.raise_for_status()
                data = resp.json()
                # Parse response based on method
                if method == "pix":
                    qr_code = data.get("qr_code", "")
                    provider_ref = data.get("transaction_id", "")
                    return PaymentIntent(
                        intent_id=idempotency_key,
                        rail=self.rail_key,
                        amount_minor=amount_minor,
                        currency=currency,
                        client_payload={"qr_code": qr_code, "provider_ref": provider_ref},
                    )
                elif method == "spei":
                    clabe = data.get("clabe", "")
                    reference = data.get("reference", "")
                    provider_ref = f"{clabe}:{reference}"
                    return PaymentIntent(
                        intent_id=idempotency_key,
                        rail=self.rail_key,
                        amount_minor=amount_minor,
                        currency=currency,
                        client_payload={"clabe": clabe, "reference": reference, "provider_ref": provider_ref},
                    )
                else:
                    provider_ref = data.get("id", "")
                    return PaymentIntent(
                        intent_id=idempotency_key,
                        rail=self.rail_key,
                        amount_minor=amount_minor,
                        currency=currency,
                        client_payload={"provider_ref": provider_ref},
                    )
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                last_error = e
                attempts += 1
                if attempts < max_attempts:
                    time.sleep(2 ** attempts)  # backoff
                    continue
                raise SupplierDown("GOWD timeout after retries") from last_error

        # Should not reach here
        raise SupplierDown("GOWD payment creation failed")

    def poll_payment(self, intent_id: str) -> PaymentStatus:
        """Poll GOWD for payment status."""
        gowd_url = "https://api.gowd.com"
        gowd_key = "test-key"

        try:
            resp = httpx.get(
                f"{gowd_url}/v1/payments/{intent_id}",
                headers={"Authorization": f"Bearer {gowd_key}"},
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status", "pending").lower()
            amount_minor = data.get("amount", 0)

            status_map = {
                "succeeded": "succeeded",
                "completed": "succeeded",
                "failed": "failed",
                "pending": "pending",
            }
            internal_status = status_map.get(status, "pending")

            return PaymentStatus(intent_id=intent_id, status=internal_status, amount_minor=amount_minor)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return PaymentStatus(intent_id=intent_id, status="failed", amount_minor=0)
            raise

    def verify_webhook(self, headers: dict, body: bytes) -> bool:
        """Verify webhook signature using HMAC-SHA256."""
        secret = "test-secret"  # would come from env GOWD_WEBHOOK_SECRET
        sig = headers.get("X-Gowd-Signature", "")
        calc = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(calc, sig)

    def parse_webhook(self, headers: dict, body: bytes) -> WebhookOutcome:
        """Parse GOWD webhook body into a WebhookOutcome."""
        import json as _json

        data = _json.loads(body)
        status = data.get("status", "succeeded").lower()
        event_id = data.get("event_id", "")
        external_id = data.get("external_id", "")

        # Map GOWD status to internal outcome; only succeeded/failed are valid
        outcome_map = {"succeeded": "succeeded", "failed": "failed"}
        outcome = outcome_map.get(status, "failed")  # default to failed for unknown

        return WebhookOutcome(
            intent_id=external_id,
            event_id=event_id,
            status=outcome,
            credited=True,
        )


def register(reg):
    reg.register(GowdLatamAdapter())