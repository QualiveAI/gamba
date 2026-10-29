from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class DeliveryResult:
    delivery_id: str
    status: str


@dataclass
class VerificationResult:
    delivery_id: str
    verified: bool
    details: str = ""


@runtime_checkable
class PrizeDeliveryChannel(Protocol):
    channel_key: str

    def deliver(self, prize_quote, user_ref: str) -> DeliveryResult: ...

    def verify_delivery(self, delivery_id: str) -> VerificationResult: ...
