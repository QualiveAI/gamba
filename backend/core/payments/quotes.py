"""Серверная неизменяемая котировка: coins, фиат и атомы провайдера раздельны."""

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, Decimal, localcontext

from core.contracts.payment import PaymentError
from core.payments.policy import (
    METHODS,
    PricingConfig,
    ensure_enabled,
    primary_bot_id,
    validate_actor,
)

MAX_ATOMIC = 9_000_000_000_000_000_000


def ceil_atomic(value: Decimal) -> int:
    result = int(value.to_integral_value(rounding=ROUND_CEILING))
    if not 0 <= result <= MAX_ATOMIC:
        raise PaymentError("amount_out_of_range", "Valor fora do limite.", 422)
    return result


def compute_client_fee(amount_minor: int, fee_percent) -> int:
    from core.payments.policy import decimal_setting

    if type(amount_minor) is not int or amount_minor <= 0:
        raise PaymentError("invalid_amount", status_code=422)
    # Старый вызывающий код мог передавать 20.0; строковое преобразование здесь
    # сохраняет совместимость без арифметики с float.
    percent = decimal_setting(str(fee_percent), positive=False)
    if percent > 100:
        raise PaymentError("invalid_payment_config")
    with localcontext() as ctx:
        ctx.prec = 50
        return ceil_atomic(Decimal(amount_minor) * percent / 100)


@dataclass(frozen=True)
class PaymentQuote:
    id: str
    user_id: int
    tenant: str
    coins: int
    amount_brl_minor: int
    fee_brl_minor: int
    gross_brl_minor: int
    net_brl_minor: int
    coin_usd_price: str
    usd_brl_rate: str
    fee_percent: str
    rate_version: str
    config_version: str
    config_snapshot: dict
    method: str
    rail: str
    mode: str
    channel: str
    provider_amount_atomic: int
    provider_currency: str
    provider_exponent: int
    chain: str | None
    token: str | None
    address: str | None
    merchant_bot_id: int | None
    auth_bot_id: int | None
    auth_scope: str
    is_guest: bool
    created_at: datetime
    expires_at: datetime

    def public(self) -> dict:
        result = asdict(self)
        for key in (
            "user_id",
            "config_snapshot",
            "merchant_bot_id",
            "auth_bot_id",
            "auth_scope",
            "is_guest",
        ):
            result.pop(key, None)
        result["quote_id"] = result.pop("id")
        result["wallet_unit"] = "coin"
        result["currency"] = "BRL"
        result["provider_amount_atomic"] = str(self.provider_amount_atomic)
        return result


def build_quote(
    user: dict,
    coins: int,
    method: str,
    tenant: str = "default",
    channel: str | None = None,
    *,
    config: PricingConfig | None = None,
    now: datetime | None = None,
    quote_id: str | None = None,
    merchant_bot_id: int | None = None,
) -> PaymentQuote:
    config = config or PricingConfig.load()
    validate_actor(user, config.mode)
    if config.mode == "disabled":
        raise PaymentError("payments_disabled", "Pagamentos desativados.", 503)
    if type(coins) is not int or not 1 <= coins <= config.max_coins:
        raise PaymentError("invalid_coins", "Informe uma quantidade inteira de moedas.", 422)
    if method not in METHODS:
        raise PaymentError("unknown_method", "Método de pagamento inválido.", 422)
    channel = channel or ("web" if user["auth_scope"] in ("guest", "roblox") else "telegram")
    if channel not in ("telegram", "web"):
        raise PaymentError("invalid_channel", status_code=422)
    if user["auth_scope"] in ("guest", "roblox") and channel != "web":
        raise PaymentError("invalid_channel", status_code=403)
    if not tenant or len(tenant) > 64:
        raise PaymentError("invalid_tenant", status_code=422)
    created_at = now or datetime.now(UTC)
    if created_at.tzinfo is None:
        raise PaymentError("invalid_quote_time")
    qid = quote_id or uuid.uuid4().hex
    with localcontext() as ctx:
        ctx.prec = 50
        net = ceil_atomic(Decimal(coins) * config.coin_usd_price * config.usd_brl_rate * 100)
        fee = compute_client_fee(net, config.fee_percent)
        gross = net + fee
        if gross > min(MAX_ATOMIC, 9_007_199_254_740_991):
            raise PaymentError("amount_out_of_range", status_code=422)
        amount = gross
        currency, exponent = "BRL", 2
        chain = token = address = None
        if method == "stars":
            amount = ceil_atomic(
                Decimal(gross) / 100 / config.usd_brl_rate / config.stars_usd_price
            )
            currency, exponent = "XTR", 0
        elif method == "crypto":
            if config.mode != "sandbox":
                raise PaymentError("crypto_destination_not_configured", status_code=503)
            # Fixture не является настоящим активом/сетью/депозитным адресом.
            amount = ceil_atomic(Decimal(gross) / 100 / config.usd_brl_rate * 1_000_000)
            currency, exponent = "TEST-USDT", 6
            chain, token, address = "sandbox", "TEST-USDT", f"sandbox-wallet:{qid}"
    snapshot = config.snapshot()
    return PaymentQuote(
        qid,
        user["id"],
        tenant,
        coins,
        net,
        fee,
        gross,
        net,
        str(config.coin_usd_price),
        str(config.usd_brl_rate),
        str(config.fee_percent),
        config.version,
        config.version,
        snapshot,
        method,
        METHODS[method][1],
        config.mode,
        channel,
        amount,
        currency,
        exponent,
        chain,
        token,
        address,
        merchant_bot_id if method == "stars" else None,
        user.get("auth_bot_id"),
        user["auth_scope"],
        user.get("is_guest") is True or user["auth_scope"] == "guest",
        created_at,
        created_at + timedelta(seconds=config.ttl_seconds),
    )


def quote_from_row(row) -> PaymentQuote:
    values = {name: row[name] for name in PaymentQuote.__dataclass_fields__}
    for name in ("coin_usd_price", "usd_brl_rate", "fee_percent"):
        values[name] = str(values[name])
    if isinstance(values["config_snapshot"], str):
        values["config_snapshot"] = json.loads(values["config_snapshot"])
    return PaymentQuote(**values)


async def get_quote(conn, quote_id: str, *, lock: bool = False) -> PaymentQuote | None:
    row = await (
        await conn.execute(
            "SELECT * FROM payment_quotes WHERE id=%s" + (" FOR UPDATE" if lock else ""),
            (quote_id,),
        )
    ).fetchone()
    return quote_from_row(row) if row else None


async def create_quote(
    conn,
    *,
    user: dict,
    coins: int,
    method: str,
    tenant: str = "default",
    channel: str | None = None,
) -> PaymentQuote:
    quote = build_quote(user, coins, method, tenant, channel, merchant_bot_id=primary_bot_id())
    await ensure_enabled(conn, method, quote.mode, creation=True, channel=quote.channel)
    # DB identity проверяется независимо от claims, особенно для guest.
    row = await (
        await conn.execute("SELECT id, is_guest FROM users WHERE id=%s FOR SHARE", (user["id"],))
    ).fetchone()
    if not row or bool(row["is_guest"]) != quote.is_guest:
        raise PaymentError("actor_mismatch", status_code=403)
    data = asdict(quote)
    data["config_snapshot"] = json.dumps(quote.config_snapshot)
    columns = list(data)
    await conn.execute(
        "INSERT INTO payment_quotes ("
        + ",".join(columns)
        + ") VALUES ("
        + ",".join(["%s"] * len(columns))
        + ")",
        tuple(data[c] for c in columns),
    )
    return quote
