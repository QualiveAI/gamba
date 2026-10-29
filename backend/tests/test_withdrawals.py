import pytest

from app.db import get_conn
from app.withdrawals import service


@pytest.mark.asyncio
async def test_threshold():
    async with get_conn() as conn:
        await conn.execute(
            "DELETE FROM withdrawals WHERE user_id IN (SELECT id FROM users WHERE telegram_id = %s)",  # noqa: E501
            (999009,),
        )  # noqa: E501
        await conn.execute("DELETE FROM users WHERE telegram_id = %s", (999009,))
        cur = await conn.execute(
            "INSERT INTO users (telegram_id, balance_units, region, created_at) VALUES (%s, %s, %s, now() - interval '2 days') RETURNING id",  # noqa: E501
            (999009, 1000, "US"),
        )
        user = await cur.fetchone()
        await conn.commit()
        user = dict(user)
        user["region"] = "US"
        user["created_at"] = None
        # below minimum
        with pytest.raises(ValueError):
            await service.request(conn, user, 100, "US")
