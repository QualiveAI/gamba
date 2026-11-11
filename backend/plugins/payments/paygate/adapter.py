"""PayGate.to Cards: точный request-контракт без небезопасного live settlement.

Источник: https://paygate.to/docs/payment-gateway-api/index.html
GET callback не подписан; ipn_token служит поддержке, не доказывает оплату.
До независимой сверки on-chain/merchant live намеренно недоступен.
"""

from decimal import Decimal
from urllib.parse import urlencode, urlsplit

from core.contracts.payment import PaymentError, PaymentMethod, WebhookOutcome
from core.payments.sandbox import SandboxAdapter


class PayGateError(PaymentError):
    pass


class PayGateAdapter(SandboxAdapter):
    MANIFEST = {"key": "paygate", "type": "payment", "geo": "*", "version": "2"}
    rail_key = "paygate"
    geo = "*"
    methods = [PaymentMethod("card", "Cartão")]
    refund_supported = False

    def client_fee_percent(self) -> Decimal:
        from core.payments.policy import PricingConfig

        return PricingConfig.load().fee_percent

    @staticmethod
    def wallet_request(*, intent_id: str, treasury_address: str, callback_base: str) -> dict:
        """Только построение официального GET; transport не подключён."""
        callback = urlsplit(callback_base)
        if callback.scheme != "https" or not callback.netloc or callback.query or callback.fragment:
            raise PayGateError("invalid_callback_base")
        if not intent_id or not treasury_address.startswith("0x") or len(treasury_address) != 42:
            raise PayGateError("invalid_paygate_destination")
        return {
            "method": "GET",
            "url": "https://api.paygate.to/control/wallet.php",
            "params": {
                "address": treasury_address,
                "callback": callback_base.rstrip("/")
                + "/webhooks/paygate?"
                + urlencode({"intent_id": intent_id}),
            },
        }

    @staticmethod
    def checkout_url(
        *, encrypted_address: str, amount_minor: int, currency: str, email: str, provider: str
    ) -> str:
        if (
            type(amount_minor) is not int
            or amount_minor <= 0
            or currency not in ("USD", "EUR", "BRL")
        ):
            raise PayGateError("invalid_paygate_amount")
        if not encrypted_address or not provider or not email:
            raise PayGateError("paygate_checkout_incomplete")
        amount = format(Decimal(amount_minor) / 100, ".2f")
        return "https://checkout.paygate.to/process-payment.php?" + urlencode(
            {
                "address": encrypted_address,
                "amount": amount,
                "provider": provider,
                "email": email,
                "currency": currency,
            }
        )

    def handle_webhook(self, headers: dict, body: bytes) -> WebhookOutcome:
        # Никакой подделки HMAC: публичная спецификация его не определяет.
        raise PayGateError(
            "paygate_unverified_callback", "Confirmação do cartão indisponível.", 503
        )


def register(reg):
    reg.register(PayGateAdapter())
