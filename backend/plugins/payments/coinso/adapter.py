"""Coinso (coinso.io) — крипто-рельс: игрок платит USDT/USDC, приход конвертируется в USDT.

API: POST /api/payment/create (Bearer Secret Key), суммы инвойса в RUB;
вебхук payment.success / payment.failed; сверка через GET /api/payment/status.
Спецификация: docs/PAYMENTS_COINSO.md
"""

import json
import os

import httpx

from core.contracts.payment import PaymentIntent, PaymentStatus, WebhookOutcome


class CoinsoError(Exception):
    pass


class CoinsoAdapter:
    MANIFEST = {"key": "coinso", "type": "payment", "geo": "*", "version": "1"}
    rail_key = "coinso"
    geo = "*"
    methods = ["crypto"]
    refund_supported = False

    @staticmethod
    def _cfg() -> dict:
        return {
            "base": os.getenv("COINSO_API_BASE", "https://coinso.io/api"),
            "secret": os.getenv("COINSO_SECRET_KEY", ""),
            "project_id": int(os.getenv("COINSO_PROJECT_ID", "0") or 0),
            "network": os.getenv("COINSO_NETWORK", "usdt_trc20"),
            "success_url": os.getenv("COINSO_SUCCESS_URL", ""),
            # 1 unit = 1 USD cent; Coinso принимает суммы в рублях
            "usd_rub_rate": float(os.getenv("COINSO_USD_RUB_RATE", "90.0")),
        }

    def client_fee_percent(self) -> float:
        # Комиссию платит клиент: добавляется к сумме сверху
        return float(os.getenv("COINSO_FEE_PERCENT", "20.0"))

    def create_payment(
        self, user_id: int, amount_minor: int, currency: str, idempotency_key: str
    ) -> PaymentIntent:
        cfg = self._cfg()
        if not cfg["secret"] or not cfg["project_id"]:
            # Ключи не настроены: mock-инвойс для тестов/staging
            return PaymentIntent(
                idempotency_key,
                self.rail_key,
                amount_minor,
                currency,
                {
                    "payment_url": f"https://coinso.example/pay/{idempotency_key}",
                    "invoice_id": idempotency_key,
                    "mock": True,
                },
            )
        amount_rub = round(amount_minor / 100.0 * cfg["usd_rub_rate"], 2)
        payload: dict = {
            "project_id": cfg["project_id"],
            "amount": amount_rub,
            "description": f"WINDROP deposit user{user_id}",
            "custom": idempotency_key,
            "method": "crypto",
            "currency": cfg["network"],
            "client_telegram_id": str(user_id),
            "client_user_id": str(user_id),
        }
        if cfg["success_url"]:
            payload["success_url"] = cfg["success_url"]
        resp = httpx.post(
            f"{cfg['base']}/payment/create",
            json=payload,
            headers={"Authorization": f"Bearer {cfg['secret']}"},
            timeout=40.0,  # SBP-h2h может отвечать до 30 с
        )
        data = resp.json()
        if not data.get("success"):
            raise CoinsoError(str(data.get("message", "coinso create failed")))
        invoice_id = str(data.get("invoice_id", ""))
        return PaymentIntent(
            intent_id=idempotency_key,
            rail=self.rail_key,
            amount_minor=amount_minor,
            currency=currency,
            client_payload={
                "payment_url": str(data.get("payment_url", "")),
                "invoice_id": invoice_id,
                "amount_rub": amount_rub,
            },
        )

    def poll_payment(self, intent_id: str, provider_ref: str | None = None) -> PaymentStatus:
        """Сверка статуса по invoice_id (роутер передаёт его из payment_intents.provider_ref)."""
        cfg = self._cfg()
        if not provider_ref or not cfg["secret"]:
            return PaymentStatus(intent_id, "pending", 0)
        resp = httpx.get(
            f"{cfg['base']}/payment/status",
            params={"invoice_id": provider_ref},
            headers={"Authorization": f"Bearer {cfg['secret']}"},
            timeout=15.0,
        )
        data = resp.json()
        status = str(data.get("status", "pending")).lower()
        mapping = {"paid": "succeeded", "success": "succeeded", "failed": "failed"}
        return PaymentStatus(intent_id, mapping.get(status, "pending"), 0)

    def handle_webhook(self, headers: dict, body) -> WebhookOutcome:
        data = body if isinstance(body, dict) else json.loads(body)
        event = str(
            data.get("event") or data.get("payment_status") or data.get("status") or ""
        ).lower()
        invoice_id = str(data.get("invoice_id", ""))
        if "success" in event or event == "paid":
            status = "succeeded"
        elif "fail" in event or "expired" in event or "cancel" in event:
            status = "failed"
        else:
            status = "pending"
        return WebhookOutcome(
            intent_id=str(data.get("custom")) if data.get("custom") else None,
            event_id=invoice_id or f"coinso:{event}",
            status=status,
            credited=False,
        )


def register(reg):
    reg.register(CoinsoAdapter())
