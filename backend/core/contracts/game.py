from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class PrizeSpec:
    prize_id: str
    name: str
    nominal_units: int
    region: str | None = None


@dataclass
class PrizeQuote:
    prize_id: str
    amount_units: int
    region: str | None = None


@dataclass
class DeliveryResult:
    delivery_id: str
    status: str


@dataclass
class DeliveryStatus:
    delivery_id: str
    status: str


@dataclass
class AccountValidation:
    valid: bool
    region: str | None = None
    message: str = ""


@runtime_checkable
class GameAdapter(Protocol):
    game_key: str
    display_name: str
    supported_currencies: list[str]

    def prize_catalog(self) -> list[PrizeSpec]: ...

    def quote_prize(self, prize_id: str, amount_units: int) -> PrizeQuote: ...

    def deliver(
        self, user_ref: str, prize_quote: PrizeQuote, idempotency_key: str
    ) -> DeliveryResult: ...  # noqa: E501

    def poll_delivery(self, delivery_id: str) -> DeliveryStatus: ...

    def validate_account(self, user_ref: str) -> AccountValidation: ...
