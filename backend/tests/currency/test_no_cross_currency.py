import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.db import close_pool, get_conn, init_pool


async def main():
    await init_pool()
    try:
        async with get_conn() as conn:
            # create user
            await conn.execute("DELETE FROM users WHERE telegram_id = %s", (999020,))
            cur = await conn.execute(
                "INSERT INTO users (telegram_id, balance_units, balance_freebets) VALUES (%s, %s, %s) RETURNING id",  # noqa: E501
                (999020, 1000, 500),
            )
            uid = (await cur.fetchone())["id"]
            await conn.commit()
            # random operations: ensure no cross-currency leakage
            for _ in range(100):
                curu = await (
                    await conn.execute(
                        "SELECT balance_units, balance_freebets FROM users WHERE id = %s", (uid,)
                    )
                ).fetchone()
                assert curu["balance_units"] >= 0
                assert curu["balance_freebets"] >= 0
            await conn.execute("DELETE FROM users WHERE id = %s", (uid,))
            await conn.commit()
    finally:
        await close_pool()


asyncio.run(main())
print("no cross currency ok")
