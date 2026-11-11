from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable

PaymentMode = Literal["disabled", "sandbox", "live"]


class PaymentError(ValueError):
    """Ожидаемый отказ: наружу возвращается код, а не секреты провайдера."""

    def __init__(self, code: str, message: str = "Pagamento indisponível.", status_code: int = 409):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class PaymentMethod:
    key: str
    name: str


@dataclass(frozen=True)
class PaymentIntent:
    intent_id: str
    rail: str
    # Для новых адаптеров это атомарная сумма ПРОВАЙДЕРА, никогда wallet coins.
    amount_minor: int
    currency: str
    client_payload: dict
    mode: str = "disabled"
    provider_ref: str | None = None


@dataclass(frozen=True)
class VerifiedPayment:
    """Результат доверенного серверного verifier, НЕ модель входящего HTTP JSON.

    Worker восстанавливает его только из отдельно сохранённого verified_payload.
    Наличие reference, токена игрока или status=succeeded в raw_payload не является
    верификацией. Адаптер обязан проверить подпись либо авторизованную сверку.
    """

    reference: str
    rail: str
    mode: str
    provider_event_id: str
    status: str
    amount_atomic: int
    currency: str
    source: str
    chain: str | None = None
    token: str | None = None
    address: str | None = None
    charge_id: str | None = None
    user_id: int | None = None
    merchant_bot_id: int | None = None
    paid_at: datetime | None = None
    receipt_event_id: int | None = None
    operator_user_id: int | None = None

    def __post_init__(self):
        if not self.reference or len(self.reference) > 128:
            raise PaymentError("invalid_reference")
        if not self.provider_event_id or len(self.provider_event_id) > 256:
            raise PaymentError("invalid_event_id")
        if self.mode not in ("sandbox", "live"):
            raise PaymentError("invalid_evidence_mode")
        if self.status not in ("pending", "failed", "expired", "succeeded"):
            raise PaymentError("invalid_payment_status")
        if type(self.amount_atomic) is not int or self.amount_atomic <= 0:
            raise PaymentError("invalid_provider_amount")
        if self.source not in (
            "sandbox_fixture",
            "signed_webhook",
            "provider_poll",
            "telegram_main",
            "gift_review",
        ):
            raise PaymentError("unverified_payment")
        if self.paid_at is not None and self.paid_at.tzinfo is None:
            raise PaymentError("invalid_payment_time")


@dataclass(frozen=True)
class PaymentStatus:
    intent_id: str
    status: str
    amount_minor: int
    # Старый status без evidence не может привести к зачислению.
    evidence: VerifiedPayment | None = None


@dataclass(frozen=True)
class WebhookOutcome:
    intent_id: str | None
    event_id: str
    status: str
    credited: bool = False
    evidence: VerifiedPayment | None = None


@dataclass(frozen=True)
class AuthenticatedCallback:
    reference: str
    event_id: str
    rail: str
    mode: str
    source: str = "signed_webhook"


@dataclass(frozen=True)
class MethodAvailability:
    method: str
    label: str
    rail: str
    enabled: bool
    reason: str | None
    mode: str


@runtime_checkable
class PaymentRailAdapter(Protocol):
    rail_key: str
    geo: str
    methods: list[PaymentMethod]
    refund_supported: bool

    def create_payment(
        self,
        user_id: int,
        amount_minor: int,
        currency: str,
        idempotency_key: str,
        *,
        mode: str = "disabled",
        metadata: dict | None = None,
    ) -> PaymentIntent: ...

    def poll_payment(
        self,
        intent_id: str,
        provider_ref: str | None = None,
        *,
        payment: dict | None = None,
    ) -> PaymentStatus: ...

    def handle_webhook(self, headers: dict, body: bytes) -> WebhookOutcome: ...
