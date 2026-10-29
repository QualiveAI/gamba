import pytest

from app.db import get_conn
from core.payments.intents import create_intent, get_intent, attach_provider_ref


async def _user_id():
    async with get_conn() as conn:
        await conn.execute(
            "INSERT INTO users (telegram_id, balance_units, region, created_at) VALUES (900101, 0, 'US', now()) ON CONFLICT (telegram_id) DO NOTHING"
        )
        await conn.commit()
        row = await (await conn.execute("SELECT id FROM users WHERE telegram_id = 900101")).fetchone()
    return row["id"]


@pytest.mark.asyncio
async def test_create_intent_persists():
    uid = await _user_id()
    intent = await create_intent(uid, "default", "mock", 100, "units", "key-1")
    got = await get_intent(intent.id)
    assert got is not None
    assert got.id == intent.id
    assert got.user_id == uid
    assert got.amount_minor == 100
    assert got.status == "pending"
    assert got.id != "nonexistent"


@pytest.mark.asyncio
async def test_idempotency_key_returns_existing():
    uid = await _user_id()
    first = await create_intent(uid, "default", "mock", 100, "units", "key-2")
    second = await create_intent(uid, "default", "mock", 100, "units", "key-2")
    assert first.id == second.id
    async with get_conn() as conn:
        row = await (await conn.execute("SELECT COUNT(*) AS c FROM payment_intents WHERE idempotency_key = 'key-2'")).fetchone()
        assert row["c"] == 1
        assert row["c"] != 2


@pytest.mark.asyncio
async def test_positive_amount_required():
    uid = await _user_id()
    with pytest.raises(ValueError):
        await create_intent(uid, "default", "mock", 0, "units", "key-3")


@pytest.mark.asyncio
async def test_attach_provider_ref():
    uid = await _user_id()
    intent = await create_intent(uid, "default", "mock", 100, "units", "key-4")
    await attach_provider_ref(intent.id, "prov-1")
    got = await get_intent(intent.id)
    assert got.provider_ref == "prov-1"
    assert got.provider_ref != "other"