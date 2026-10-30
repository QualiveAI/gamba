import pytest
import uuid

from app.db import get_conn
from core.payments.events import ingest, process_pending, link_intent
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
async def test_webhook_before_intent():
    uid = await _user()
    eid = await ingest("mock", "evt-1", {"foo": "bar"})
    async with get_conn() as conn:
        row = await (await conn.execute("SELECT processed_at FROM payment_events WHERE id = %s", (eid,))).fetchone()
    assert row is not None
    assert row["processed_at"] is None

    intent = await create_intent(uid, "default", "mock", 500, "units", "ik-1")
    await link_intent(eid, intent.id)

    results = await process_pending()
    assert any(r["id"] == eid and r["status"] == "processed" for r in results)

    async with get_conn() as conn:
        cnt = await (await conn.execute("SELECT COUNT(*) AS c FROM ledger_entries WHERE reason = 'deposit_units'")).fetchone()
    assert cnt["c"] >= 1

    eid2 = await ingest("mock", "evt-1", {"foo": "bar2"})
    assert eid2 == eid
    async with get_conn() as conn:
        cnt2 = await (await conn.execute("SELECT COUNT(*) AS c FROM ledger_entries WHERE reason = 'deposit_units'")).fetchone()
    assert cnt2["c"] == cnt["c"]