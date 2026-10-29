import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.db import close_pool, get_conn, init_pool
from core.rewards.welcome import grant_welcome


async def main():
    await init_pool()
    try:
        async with get_conn() as conn:
            await conn.execute("DELETE FROM users WHERE telegram_id = %s", (999022,))
            await conn.execute(
                "DELETE FROM ledger_entries WHERE user_id IN (SELECT id FROM users WHERE telegram_id = %s)",  # noqa: E501
                (999022,),
            )
            cur = await conn.execute(
                "INSERT INTO users (telegram_id, balance_units, balance_freebets) VALUES (%s, %s, %s) RETURNING id",  # noqa: E501
                (999022, 0, 0),
            )
            uid = (await cur.fetchone())["id"]
            await conn.commit()
            user = {"id": uid}
            r1 = await grant_welcome(conn, user)
            r2 = await grant_welcome(conn, user)
            print(r1, r2)
            assert r1["granted"] is True
            assert r2["granted"] is False
            await conn.execute("DELETE FROM ledger_entries WHERE user_id = %s", (uid,))
            await conn.execute("DELETE FROM users WHERE id = %s", (uid,))
            await conn.commit()
    finally:
        await close_pool()


asyncio.run(main())
print("welcome idempotent ok")
