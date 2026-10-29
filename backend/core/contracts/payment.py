from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class PaymentMethod:
    key: str
    name: str


@dataclass
class PaymentIntent:
    intent_id: str
    rail: str
    amount_minor: int
    currency: str
    client_payload: dict


@dataclass
class PaymentStatus:
    intent_id: str
    status: str
    amount_minor: int


@dataclass
class WebhookOutcome:
    intent_id: str | None
    event_id: str
    status: str
    credited: bool = False


@runtime_checkable
class PaymentRailAdapter(Protocol):
    rail_key: str
    geo: str
    methods: list[PaymentMethod]
    refund_supported: bool

    def create_payment(
        self, user_id: int, amount_minor: int, currency: str, idempotency_key: str
    ) -> PaymentIntent: ...  # noqa: E501

    def poll_payment(self, intent_id: str) -> PaymentStatus: ...

    def handle_webhook(self, headers: dict, body: bytes) -> WebhookOutcome: ...
