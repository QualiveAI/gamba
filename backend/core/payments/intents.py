import uuid
from dataclasses import dataclass

from app.db import get_conn


@dataclass
class PaymentIntent:
    id: str
    user_id: int
    tenant: str
    rail: str
    amount_minor: int
    currency: str
    status: str
    provider_ref: str | None


async def create_intent(user_id: int, tenant: str, rail: str,
                        amount_minor: int, currency: str,
                        idempotency_key: str) -> PaymentIntent:
    if amount_minor <= 0:
        raise ValueError("amount_minor must be positive")
    async with get_conn() as conn:
        existing = await (await conn.execute(
            "SELECT id,user_id,tenant,rail,amount_minor,currency,status,provider_ref "
            "FROM payment_intents WHERE idempotency_key=%s", (idempotency_key,)
        )).fetchone()
        if existing:
            return PaymentIntent(**dict(existing))
        intent_id = uuid.uuid4().hex
        await conn.execute(
            "INSERT INTO payment_intents "
            "(id,user_id,tenant,rail,amount_minor,currency,idempotency_key) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (intent_id, user_id, tenant, rail, amount_minor, currency, idempotency_key)
        )
        await conn.commit()
    return PaymentIntent(intent_id, user_id, tenant, rail, amount_minor,
                         currency, "pending", None)


async def attach_provider_ref(intent_id: str, provider_ref: str) -> None:
    async with get_conn() as conn:
        await conn.execute(
            "UPDATE payment_intents SET provider_ref=%s WHERE id=%s",
            (provider_ref, intent_id))
        await conn.commit()


async def get_intent(intent_id: str) -> PaymentIntent | None:
    async with get_conn() as conn:
        row = await (await conn.execute(
            "SELECT id,user_id,tenant,rail,amount_minor,currency,status,provider_ref "
            "FROM payment_intents WHERE id=%s", (intent_id,)
        )).fetchone()
    return PaymentIntent(**dict(row)) if row else None