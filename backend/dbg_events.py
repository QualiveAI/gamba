import asyncio
from app.db import init_pool, close_pool, get_conn
from core.payments.intents import create_intent
from core.payments.events import ingest, process_pending

async def main():
    await init_pool()
    async with get_conn() as conn:
        await conn.execute("INSERT INTO users (telegram_id, balance_units, region, created_at) VALUES (999902,0,'US',now()) ON CONFLICT DO NOTHING")
        await conn.commit()
        row = await (await conn.execute("SELECT id FROM users WHERE telegram_id=999902")).fetchone()
        uid = row["id"]
    intent = await create_intent(uid, "default", "mock", 500, "units", "dbg-key2")
    eid = await ingest("mock", "dbg-evt2", {"ok": True}, intent_id=intent.id)
    print("intent", intent.id, "event", eid, flush=True)
    res = await process_pending()
    print("results", res, flush=True)
    await close_pool()

asyncio.run(main())