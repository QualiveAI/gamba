"""PayGate.to — карточный рельс без KYC: игрок платит картой/Apple/Google Pay,
выплата USDC приходит мгновенно на наш self-custodial Polygon-кошелёк.

Схема API (без ключей и регистрации):
1) GET control/wallet.php?address={наш USDC Polygon}&callback={callback c уникальным параметром}
   -> address_in (зашифрованный), polygon_address_in (читаемый), ipn_token
2) редирект игрока: GET checkout.paygate.to/process-payment.php
   (address, amount USD, provider, email, currency)
3) колбэк: GET на наш callback + value_coin, coin, txid_in, txid_out,
   address_in (читаемый), value_forwarded_coin.
   PayGate повторяет колбэк, пока не ответим ok.

Верификация зачисления — на уровне роутера: address_in из колбэка должен
совпасть с polygon_address_in интента, value_forwarded_coin >= порога.
Документация: paygate.to/docs
"""

import json
import os
from urllib.parse import quote

import httpx

from core.contracts.payment import PaymentIntent, PaymentStatus, WebhookOutcome


class PayGateError(Exception):
    pass


class PayGateAdapter:
    MANIFEST = {"key": "paygate", "type": "payment", "geo": "*", "version": "1"}
    rail_key = "paygate"
    geo = "*"
    methods = ["card"]
    refund_supported = False

    @staticmethod
    def _cfg() -> dict:
        return {
            "api_base": os.getenv("PAYGATE_API_BASE", "https://api.paygate.to"),
            "checkout_base": os.getenv("PAYGATE_CHECKOUT_BASE", "https://checkout.paygate.to"),
            "wallet": os.getenv("PAYGATE_WALLET", ""),
            "callback_base": os.getenv("PAYGATE_CALLBACK_BASE", ""),
            "provider": os.getenv("PAYGATE_PROVIDER", "hosted"),
        }

    def client_fee_percent(self) -> float:
        # Комиссию платит клиент: закладываем её в сумму сверху
        return float(os.getenv("PAYGATE_FEE_PERCENT", "20.0"))

    def create_payment(
        self, user_id: int, amount_minor: int, currency: str, idempotency_key: str
    ) -> PaymentIntent:
        cfg = self._cfg()
        if not cfg["wallet"] or not cfg["callback_base"]:
            # Кошелёк не настроен: mock-ссылка для тестов/staging
            return PaymentIntent(
                idempotency_key,
                self.rail_key,
                amount_minor,
                currency,
                {
                    "payment_url": f"https://paygate.example/pay/{idempotency_key}",
                    "polygon_address_in": "MOCK",
                    "expected_usdc": amount_minor / 100.0,
                    "mock": True,
                },
            )
        callback = f"{cfg['callback_base']}/webhooks/paygate?intent_id={idempotency_key}"
        resp = httpx.get(
            f"{cfg['api_base']}/control/wallet.php",
            params={"address": cfg["wallet"], "callback": callback},
            timeout=15.0,
        )
        data = resp.json()
        address_in = data.get("address_in", "")
        polygon_address_in = data.get("polygon_address_in", "")
        if not address_in or not polygon_address_in:
            raise PayGateError(f"paygate wallet.php failed: {data}")
        amount_usd = round(amount_minor / 100.0, 2)
        payment_url = (
            f"{cfg['checkout_base']}/process-payment.php"
            f"?address={quote(address_in, safe='')}"
            f"&amount={amount_usd}"
            f"&provider={cfg['provider']}"
            f"&email={quote(f'user{user_id}@windrop.local', safe='')}"
            f"&currency=USD"
        )
        return PaymentIntent(
            intent_id=idempotency_key,
            rail=self.rail_key,
            amount_minor=amount_minor,
            currency=currency,
            client_payload={
                "payment_url": payment_url,
                "polygon_address_in": polygon_address_in,
                "expected_usdc": amount_usd,
            },
        )

    def poll_payment(self, intent_id: str, provider_ref: str | None = None) -> PaymentStatus:
        # У PayGate нет серверного status-эндпоинта: статус знаем только из колбэка
        return PaymentStatus(intent_id, "pending", 0)

    def handle_webhook(self, headers: dict, body) -> WebhookOutcome:
        # Колбэк PayGate — GET с query-параметрами; роутер передаёт их словарём
        data = body if isinstance(body, dict) else json.loads(body)
        txid_in = str(data.get("txid_in", "") or "")
        try:
            value = float(data.get("value_forwarded_coin", "") or data.get("value_coin", "") or 0)
        except ValueError:
            value = 0.0
        if txid_in and value > 0:
            status = "succeeded"
        else:
            status = "pending" if not data.get("intent_id") else "failed"
        return WebhookOutcome(
            intent_id=str(data.get("intent_id")) if data.get("intent_id") else None,
            event_id=txid_in or f"paygate:{data.get('address_in', '')}",
            status=status,
            credited=False,
        )


def register(reg):
    reg.register(PayGateAdapter())
