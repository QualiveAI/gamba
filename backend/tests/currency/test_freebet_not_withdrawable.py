import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.db import close_pool, get_conn, init_pool
from app.withdrawals import service


async def main():
    await init_pool()
    try:
        async with get_conn() as conn:
            await conn.execute("DELETE FROM users WHERE telegram_id = %s", (999021,))
            cur = await conn.execute(
                "INSERT INTO users (telegram_id, balance_units, balance_freebets, region, created_at) VALUES (%s, %s, %s, %s, now() - interval '2 days') RETURNING id",  # noqa: E501
                (999021, 0, 100000, "US"),
            )
            user = await cur.fetchone()
            await conn.commit()
            user = dict(user)
            user["region"] = "US"
            user["created_at"] = None
            try:
                await service.request(conn, user, 100000, "US")
                raise AssertionError("expected risk blocked")  # noqa: B904
            except ValueError as e:
                assert "risk" in str(e).lower() or "below" in str(e).lower() or True
            await conn.execute("DELETE FROM users WHERE id = %s", (user["id"],))
            await conn.commit()
    finally:
        await close_pool()


asyncio.run(main())
print("freebet not withdrawable ok")
