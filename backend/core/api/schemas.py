from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator


class GameMeta(BaseModel):
    game_key: str
    display_name: str
    currencies: list[str]


class GeoMeta(BaseModel):
    geo: str
    methods: list[str]


class TenantBrand(BaseModel):
    name: str
    logo_url: str
    primary_color: str


class TenantMeta(BaseModel):
    tenant: str
    brand: TenantBrand
    domains: dict
    geos: list[str]
    games: list[str]


class DepositQuoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    coins: StrictInt = Field(gt=0, le=100000000)
    method: Literal["stars", "gift", "card", "crypto"]
    channel: Literal["telegram", "web"] | None = None


class DepositRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quote_id: str = Field(min_length=32, max_length=32, pattern=r"^[0-9a-f]{32}$")
    idempotency_key: str = Field(min_length=8, max_length=128)

    @field_validator("idempotency_key")
    @classmethod
    def printable_key(cls, value: str) -> str:
        if any(ord(char) < 33 or ord(char) > 126 for char in value):
            raise ValueError("Chave de idempotência inválida.")
        return value


class DepositResponse(BaseModel):
    intent_id: str
    quote_id: str | None
    coins: int | None
    wallet_unit: str
    method: str | None
    rail: str
    mode: str
    status: str
    expires_at: datetime | None
    provider_amount_atomic: str | None
    provider_currency: str | None
    provider_exponent: int | None
    client_payload: dict
    refund_status: str


class WebhookResponse(BaseModel):
    ok: bool
    credited: bool = False
    status: str | None = None


class GameSessionRequest(BaseModel):
    pass


class GameSessionResponse(BaseModel):
    session_id: str
    game_key: str


class WithdrawalRequest(BaseModel):
    amount_minor: int
    currency: str
    channel: str


class WithdrawalResponse(BaseModel):
    withdrawal_id: str
    status: str


class WithdrawalStatus(BaseModel):
    withdrawal_id: str
    status: str
