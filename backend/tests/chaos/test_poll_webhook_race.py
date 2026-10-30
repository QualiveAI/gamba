import pytest
import uuid
import asyncio

from app.db import get_conn
from core.payments.events import ingest, process_pending
from core.payments.intents import create_intent


async def _user():
    tg = 900000 + (uuid.uuid4().int % 100000)
    async with get_conn() as conn:
        await conn.execute(
            "INSERT INTO users (telegram_id, balance_units, region, created_at) VALUES (%s, 0, 'US', now()) ON CONFLICT (telegram_id) DO NOTHING",
            (tg,),
        )
        await conn.commit()
        row = await (await conn.execute("SELECT id FROM users WHERE telegram_id = %s", (tg,))).fetchone()
    return row["id"]


@pytest.mark.asyncio
async def test_poll_webhook_race():
    uid = await _user()
    intent = await create_intent(uid, "default", "mock", 500, "units", "ik-2")

    # concurrent ingest
    eid1, eid2 = await asyncio.gather(
        ingest("mock", "evt-2", {"intent_id": intent.id}),
        ingest("mock", "evt-2", {"intent_id": intent.id}),
    )
    assert eid1 == eid2

    async with get_conn() as conn:
        await conn.execute("UPDATE payment_events SET intent_id = %s WHERE id = %s", (intent.id, eid1))
        await conn.commit()

    await process_pending()

    async with get_conn() as conn:
        cnt = await (await conn.execute("SELECT COUNT(*) AS c FROM payment_events WHERE provider_event_id = 'evt-2'")).fetchone()
    assert cnt["c"] == 1

    async with get_conn() as conn:
        lcnt = await (await conn.execute("SELECT COUNT(*) AS c FROM ledger_entries WHERE ref_id = 'mock:evt-2'")).fetchone()
    assert lcnt["c"] == 1