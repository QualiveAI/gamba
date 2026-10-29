from datetime import date

import pytest

from app.analytics.aggregate import daily_rollup
from app.analytics.events import track
from app.db import get_conn


@pytest.mark.asyncio
async def test_event_dedup():
    async with get_conn() as conn:
        await conn.execute(
            "DELETE FROM events WHERE user_id IN (SELECT id FROM users WHERE telegram_id = %s)",
            (999005,),
        )
        await conn.execute("DELETE FROM users WHERE telegram_id = %s", (999005,))
        cur = await conn.execute(
            "INSERT INTO users (telegram_id, balance_units) VALUES (%s, %s) RETURNING id",
            (999005, 0),
        )
        uid = (await cur.fetchone())["id"]
        await conn.commit()
        first = await track(conn, uid, "login", {}, "key1")
        second = await track(conn, uid, "login", {}, "key1")
        assert first == second
        await conn.commit()


@pytest.mark.asyncio
async def test_daily_rollup():
    async with get_conn() as conn:
        data = await daily_rollup(conn, date.today())
        assert "new_users" in data
