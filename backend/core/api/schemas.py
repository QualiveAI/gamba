from pydantic import BaseModel


class GameMeta(BaseModel):
    game_key: str
    display_name: str
    currencies: list[str]


class GeoMeta(BaseModel):
    geo: str
    methods: list[str]


class DepositRequest(BaseModel):
    rail: str
    amount_minor: int
    currency: str


class DepositResponse(BaseModel):
    intent_id: str
    client_payload: dict


class WebhookResponse(BaseModel):
    ok: bool
    credited: bool = False


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
