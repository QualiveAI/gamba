import asyncio
import uuid

import pytest

from app.db import get_conn
from core.contracts.payment import PaymentError
from core.payments.intents import attach_provider_ref, create_intent, get_intent
from core.payments.quotes import create_quote


@pytest.mark.asyncio
async def test_create_intent_persists_canonical_id(payment_factory):
    user, quote, intent = await payment_factory()
    got = await get_intent(intent.id)
    assert got.id == intent.id == got.client_payload["intent_id"]
    assert got.user_id == user["id"]
    assert got.coins == quote.coins == 100
    assert got.provider_amount_atomic == quote.gross_brl_minor == 972
    assert got.currency == "BRL"
    assert got.public()["provider_amount_atomic"] == "972"


@pytest.mark.asyncio
async def test_scoped_idempotency_and_conflict(payment_factory):
    key = uuid.uuid4().hex
    user, quote, first = await payment_factory(key=key)
    async with get_conn() as conn, conn.transaction():
        second = await create_intent(conn=conn, user=user, quote_id=quote.id, idempotency_key=key)
        assert second.id == first.id
        different_quote = await create_quote(conn, user=user, coins=101, method="card")
        with pytest.raises(PaymentError, match="chave"):
            await create_intent(
                conn=conn, user=user, quote_id=different_quote.id, idempotency_key=key
            )
    other, _, third = await payment_factory(key=key)
    assert other["id"] != user["id"] and third.id != first.id


@pytest.mark.asyncio
async def test_concurrent_key_has_one_intent(payment_factory):
    user, _, _ = await payment_factory()
    async with get_conn() as conn:
        quote = await create_quote(conn, user=user, coins=120, method="card")
    key = uuid.uuid4().hex

    async def create():
        async with get_conn() as conn, conn.transaction():
            return await create_intent(conn=conn, user=user, quote_id=quote.id, idempotency_key=key)

    first, second = await asyncio.gather(create(), create())
    assert first.id == second.id


@pytest.mark.asyncio
async def test_legacy_amount_rejected_before_db():
    with pytest.raises(PaymentError) as exc:
        await create_intent(1, "default", "mock", 100, "units", "legacy-key")
    assert exc.value.code == "legacy_amount_ambiguous"


@pytest.mark.asyncio
async def test_provider_ref_write_once(payment_factory):
    _, _, intent = await payment_factory()
    await attach_provider_ref(intent.id, "provider:" + intent.id)
    await attach_provider_ref(intent.id, "provider:" + intent.id)
    with pytest.raises(PaymentError) as exc:
        await attach_provider_ref(intent.id, "other:" + intent.id)
    assert exc.value.code == "provider_reference_conflict"


@pytest.mark.asyncio
async def test_quote_immutable_db(payment_factory):
    _, quote, _ = await payment_factory()
    async with get_conn() as conn:
        with pytest.raises(Exception, match="payment_quote_immutable"):
            async with conn.transaction():
                await conn.execute(
                    "UPDATE payment_quotes SET coins=coins+1 WHERE id=%s", (quote.id,)
                )
