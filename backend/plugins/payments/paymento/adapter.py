"""Paymento API IPN (не Payment Links): официальный raw-body HMAC и Verify.

Документы: docs.paymento.io/api-documentation/{payment-request,payment-callback,payment-verify}
HTTP transport намеренно не реализован: только инъекция контролируемого transport/mock.
Подпись callback подтверждает происхождение inbox, но НЕ достаточна для settlement.
"""

import hashlib
import hmac
import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol

from core.contracts.payment import (
    AuthenticatedCallback,
    PaymentError,
    PaymentMethod,
    VerifiedPayment,
    WebhookOutcome,
)
from core.payments.sandbox import SandboxAdapter


class PaymentoTransport(Protocol):
    async def post_json(self, url: str, *, headers: dict, payload: dict) -> bytes: ...


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PaymentError("duplicate_json_key", status_code=400)
        result[key] = value
    return result


def parse_json(body: bytes) -> dict:
    if type(body) is not bytes or len(body) > 65536:
        raise PaymentError("invalid_paymento_body", status_code=400)
    try:
        data = json.loads(
            body,
            parse_float=Decimal,
            object_pairs_hook=_unique_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non_finite")),
        )
    except (ValueError, UnicodeDecodeError) as exc:
        raise PaymentError("invalid_paymento_json", status_code=400) from exc
    if not isinstance(data, dict):
        raise PaymentError("invalid_paymento_body", status_code=400)
    return data


def verify_ipn_signature(headers: dict, body: bytes, secret_key: str) -> bool:
    if not isinstance(secret_key, str) or not secret_key or type(body) is not bytes:
        return False
    normalized = {str(k).lower(): str(v) for k, v in headers.items()}
    received = normalized.get("x-hmac-sha256-signature", "")
    # Именно IPN API, не X-Paymento-Signature от другого продукта Payment Links.
    if not re.fullmatch(r"[0-9A-F]{64}", received):
        return False
    expected = hmac.new(secret_key.encode("utf-8"), body, hashlib.sha256).hexdigest().upper()
    return hmac.compare_digest(expected, received)


def _atomic(value, exponent: int) -> int:
    if isinstance(value, (bool, float)) or value is None:
        raise PaymentError("paymento_amount_unverifiable")
    try:
        amount = Decimal(str(value)) * (Decimal(10) ** exponent)
    except (ValueError, InvalidOperation) as exc:
        raise PaymentError("paymento_amount_unverifiable") from exc
    if (
        not amount.is_finite()
        or amount <= 0
        or amount != amount.to_integral_value()
        or amount > 9_000_000_000_000_000_000
    ):
        raise PaymentError("paymento_amount_unverifiable")
    return int(amount)


class PaymentoAdapter(SandboxAdapter):
    MANIFEST = {"key": "paymento", "type": "payment", "geo": "*", "version": "1"}
    rail_key = "paymento"
    geo = "*"
    methods = [PaymentMethod("crypto", "Criptomoedas")]
    refund_supported = False

    def __init__(
        self,
        *,
        secret_key: str | None = None,
        api_key: str | None = None,
        transport: PaymentoTransport | None = None,
    ):
        self._secret_key = secret_key
        self._api_key = api_key
        self._transport = transport

    def _config(self) -> tuple[str, str]:
        from core.payments.policy import runtime_settings

        settings = runtime_settings()
        secret = (
            self._secret_key
            if self._secret_key is not None
            else getattr(settings, "paymento_secret_key", "")
        )
        api_key = (
            self._api_key
            if self._api_key is not None
            else getattr(settings, "paymento_api_key", "")
        )
        return secret, api_key

    @staticmethod
    def request_contract(
        *,
        intent_id: str,
        amount_atomic: int,
        currency: str,
        exponent: int,
        expires_at: datetime,
        return_url: str | None = None,
        coin_name: str | None = None,
    ) -> dict:
        """Точная форма POST /v1/payment/request; никакого выполнения запроса."""
        if (
            not intent_id
            or type(amount_atomic) is not int
            or amount_atomic <= 0
            or type(exponent) is not int
            or not 0 <= exponent <= 18
            or expires_at.tzinfo is None
        ):
            raise PaymentError("invalid_paymento_request")
        amount = format(Decimal(amount_atomic) / Decimal(10) ** exponent, f".{exponent}f")
        body = {
            "orderId": intent_id,
            "riskSpeed": 1,
            "additionalData": [{"key": "OrderId", "value": intent_id}],
            "tokenExpiryDate": expires_at.isoformat(),
        }
        if coin_name:
            body["cryptoAmounts"] = [{"coinName": coin_name, "amount": amount}]
        else:
            if currency not in ("BRL", "USD", "EUR") or exponent != 2:
                raise PaymentError("invalid_paymento_fiat")
            body.update({"fiatAmount": amount, "fiatCurrency": currency})
        if return_url is not None:
            if not return_url.startswith("https://"):
                raise PaymentError("invalid_paymento_return_url")
            body["returnUrl"] = return_url
        return {"method": "POST", "url": "https://api.paymento.io/v1/payment/request", "json": body}

    def authenticate_webhook(self, headers: dict, body: bytes) -> AuthenticatedCallback:
        secret, _ = self._config()
        if not secret:
            raise PaymentError("paymento_secret_not_configured", status_code=503)
        if not verify_ipn_signature(headers, body, secret):
            raise PaymentError("invalid_webhook_signature", "Assinatura inválida.", 401)
        data = parse_json(body)
        for name in ("Token", "PaymentId", "OrderId"):
            if not isinstance(data.get(name), str) or not data[name] or len(data[name]) > 256:
                raise PaymentError("paymento_callback_incomplete", status_code=400)
        if type(data.get("OrderStatus")) is not int or data["OrderStatus"] not in (
            0,
            1,
            2,
            3,
            4,
            5,
            7,
            8,
            9,
            10,
        ):
            raise PaymentError("paymento_invalid_status", status_code=400)
        # PaymentId не меняется при изменении статуса. Digest raw body различает
        # последовательные состояния, а ledger всё равно уникален на intent.
        digest = hashlib.sha256(body).hexdigest()
        event_id = f"ipn:{data['PaymentId']}:{digest}"
        if len(event_id) > 256:
            raise PaymentError("invalid_event_id", status_code=400)
        return AuthenticatedCallback(data["OrderId"], event_id, "paymento", "live")

    def handle_webhook(self, headers: dict, body: bytes) -> WebhookOutcome:
        callback = self.authenticate_webhook(headers, body)
        # Статус raw IPN не превращается в VerifiedPayment без Verify API.
        return WebhookOutcome(callback.reference, callback.event_id, "pending")

    async def reconcile_event(self, event: dict, intent) -> VerifiedPayment:
        if (
            not event.get("authenticated")
            or event.get("verification_source") != "signed_webhook"
            or event.get("rail") != "paymento"
            or event.get("mode") != "live"
            or intent.mode != "live"
            or intent.rail != "paymento"
        ):
            raise PaymentError("paymento_unverified_inbox")
        if self._transport is None:
            raise PaymentError("paymento_transport_unavailable", status_code=503)
        _, api_key = self._config()
        if not api_key:
            raise PaymentError("paymento_api_key_not_configured", status_code=503)
        raw = bytes(event["raw_body"]) if event.get("raw_body") is not None else b""
        callback = parse_json(raw)
        token = callback.get("Token")
        if token != intent.provider_ref or callback.get("OrderId") != intent.id or not token:
            raise PaymentError("paymento_reference_mismatch")
        response = await self._transport.post_json(
            "https://api.paymento.io/v1/payment/verify",
            headers={
                "Api-Key": api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            payload={"token": token},
        )
        return self.verify_response(
            parse_json(response),
            intent=intent,
            event_id=event["provider_event_id"],
            token=token,
        )

    @staticmethod
    def verify_response(response: dict, *, intent, event_id: str, token: str) -> VerifiedPayment:
        """Только ответ авторизованного transport; не HTTP payload пользователя."""
        body = response.get("body")
        if (
            not isinstance(body, dict)
            or body.get("token") != token
            or token != intent.provider_ref
            or body.get("orderId") != intent.id
        ):
            raise PaymentError("paymento_reference_mismatch")
        status = body.get("orderStatus")
        if type(status) is not int or status not in (0, 1, 2, 3, 4, 5, 7, 8, 9, 10):
            raise PaymentError("paymento_invalid_status")
        settlement = body.get("settlement")
        if not isinstance(settlement, dict):
            raise PaymentError("paymento_settlement_missing")
        # Начальные/неполные состояния никогда не принимаются за оплату.
        # Они требуют нового IPN/повторной сверки, а не подстановки суммы из intent.
        if status != 8 or response.get("success") is not True:
            raise PaymentError("paymento_not_approved")
        if intent.provider_currency not in ("USDT", "USDC", "ETH", "BTC"):
            raise PaymentError("paymento_currency_unverifiable")
        expected = _atomic(settlement.get("expectedCryptoAmount"), intent.provider_exponent)
        received = _atomic(settlement.get("receivedCryptoAmount"), intent.provider_exponent)
        if expected != intent.provider_amount_atomic or received != expected:
            raise PaymentError("paymento_amount_mismatch")
        if (
            settlement.get("asset") != intent.provider_currency
            or settlement.get("network") != intent.chain
            or settlement.get("toAddress") != intent.address
            or not intent.chain
            or not intent.address
            or not intent.token
        ):
            raise PaymentError("paymento_destination_mismatch")
        contract = settlement.get("contractAddress")
        actual_token = contract if contract else f"native:{settlement.get('asset')}"
        if actual_token != intent.token:
            raise PaymentError("paymento_token_mismatch")
        transactions = settlement.get("transactions")
        if not isinstance(transactions, list) or not transactions:
            raise PaymentError("paymento_transactions_missing")
        hashes = set()
        completed = 0
        paid_at = None
        for transaction in transactions:
            if not isinstance(transaction, dict) or transaction.get("status") != 3:
                raise PaymentError("paymento_transaction_unconfirmed")
            txhash = transaction.get("txHash")
            if not isinstance(txhash, str) or not txhash or txhash in hashes:
                raise PaymentError("paymento_transaction_duplicate")
            hashes.add(txhash)
            if transaction.get("toAddress") != intent.address:
                raise PaymentError("paymento_destination_mismatch")
            confirmations = transaction.get("confirmations")
            required = transaction.get("requiredConfirmations")
            if (
                type(confirmations) is not int
                or type(required) is not int
                or required < 1
                or confirmations < required
            ):
                raise PaymentError("paymento_transaction_unconfirmed")
            completed += _atomic(transaction.get("amount"), intent.provider_exponent)
            try:
                when = datetime.fromisoformat(transaction["confirmedAt"].replace("Z", "+00:00"))
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                raise PaymentError("paymento_confirmation_time_missing") from exc
            if when.tzinfo is None:
                raise PaymentError("paymento_confirmation_time_missing")
            paid_at = max(paid_at, when) if paid_at else when
        if completed != expected:
            raise PaymentError("paymento_amount_mismatch")
        return VerifiedPayment(
            reference=intent.id,
            rail="paymento",
            mode="live",
            provider_event_id=event_id,
            status="succeeded",
            amount_atomic=completed,
            currency=settlement["asset"],
            source="provider_poll",
            chain=settlement["network"],
            token=actual_token,
            address=settlement["toAddress"],
            charge_id=f"paymento:{token}",
            paid_at=paid_at,
        )


def register(reg):
    reg.register(PaymentoAdapter())
