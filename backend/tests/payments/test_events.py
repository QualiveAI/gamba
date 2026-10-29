import uuid

import pytest

from app.db import get_conn
from core.payments.events import ingest, process_pending, link_intent
from core.payments.intents import create_intent


async def _user_id(tg=None):
    if tg is None:
        tg = 900000 + (uuid.uuid4().int % 100000)
    async with get_conn() as conn:
        await conn.execute(
            "INSERT INTO users (telegram_id, balance_units, region, created_at) "
            "VALUES (%s, 0, 'US', now()) ON CONFLICT (telegram_id) DO NOTHING",
            (tg,),
        )
        await conn.commit()
        row = await (await conn.execute("SELECT id FROM users WHERE telegram_id = %s", (tg,))).fetchone()
    return row["id"]


@pytest.mark.asyncio
async def test_ingest_persists():
    key = f"evt-persist-{uuid.uuid4().hex}"
    eid = await ingest("mock", key, {"foo": "bar"})
    async with get_conn() as conn:
        row = await (await conn.execute("SELECT * FROM payment_events WHERE id = %s", (eid,))).fetchone()
    assert row is not None
    assert row["rail"] == "mock"
    assert row["provider_event_id"] == key
    assert row["processed_at"] is None
    assert eid != -1


@pytest.mark.asyncio
async def test_ingest_idempotent():
    key = f"evt-idem-{uuid.uuid4().hex}"
    first = await ingest("mock", key, {"x": 1})
    second = await ingest("mock", key, {"x": 2})
    assert first == second
    async with get_conn() as conn:
        row = await (await conn.execute(
            "SELECT COUNT(*) AS c FROM payment_events WHERE rail='mock' AND provider_event_id=%s",
            (key,),
        )).fetchone()
        assert row["c"] == 1
        assert row["c"] != 2


@pytest.mark.asyncio
async def test_process_pending_credits():
    uid = await _user_id()
    ikey = f"intent-{uuid.uuid4().hex}"
    ekey = f"evt-{uuid.uuid4().hex}"
    intent = await create_intent(uid, "default", "mock", 500, "units", ikey)
    eid = await ingest("mock", ekey, {"ok": True}, intent_id=intent.id)
    results = await process_pending()
    assert any(r["id"] == eid and r["status"] == "processed" for r in results)
    async with get_conn() as conn:
        row = await (await conn.execute("SELECT balance_units FROM users WHERE id = %s", (uid,))).fetchone()
        ev = await (await conn.execute("SELECT processed_at, outcome FROM payment_events WHERE id = %s", (eid,))).fetchone()
    assert int(row["balance_units"]) == 500
    assert ev["processed_at"] is not None
    assert ev["outcome"] == "processed"


@pytest.mark.asyncio
async def test_process_pending_skips_no_intent():
    ekey = f"evt-{uuid.uuid4().hex}"
    eid = await ingest("mock", ekey, {"ok": True})
    results = await process_pending()
    assert any(r["id"] == eid and r["status"] == "skipped_no_intent" for r in results)
    async with get_conn() as conn:
        ev = await (await conn.execute("SELECT processed_at FROM payment_events WHERE id = %s", (eid,))).fetchone()
    assert ev["processed_at"] is None


@pytest.mark.asyncio
async def test_process_pending_idempotent_no_double_credit():
    uid = await _user_id()
    ikey = f"intent-{uuid.uuid4().hex}"
    ekey1 = f"evt-{uuid.uuid4().hex}"
    ekey2 = f"evt-{uuid.uuid4().hex}"
    intent = await create_intent(uid, "default", "mock", 100, "units", ikey)
    eid1 = await ingest("mock", ekey1, {"ok": True}, intent_id=intent.id)
    await process_pending()
    await ingest("mock", ekey2, {"ok": True}, intent_id=intent.id)
    await process_pending()
    async with get_conn() as conn:
        row = await (await conn.execute("SELECT balance_units FROM users WHERE id = %s", (uid,))).fetchone()
    assert int(row["balance_units"]) == 200
    assert int(row["balance_units"]) != 0


@pytest.mark.asyncio
async def test_link_intent():
    uid = await _user_id()
    ikey = f"intent-{uuid.uuid4().hex}"
    ekey = f"evt-{uuid.uuid4().hex}"
    intent = await create_intent(uid, "default", "mock", 50, "units", ikey)
    eid = await ingest("mock", ekey, {"ok": True})
    await link_intent(eid, intent.id)
    async with get_conn() as conn:
        row = await (await conn.execute("SELECT intent_id FROM payment_events WHERE id = %s", (eid,))).fetchone()
    assert row["intent_id"] == intent.id
    assert row["intent_id"] != "other"
