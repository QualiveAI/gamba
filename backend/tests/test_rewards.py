import pytest

from app.db import get_conn
from app.rewards.daily import claim_daily
from app.rewards.missions import update_progress


@pytest.mark.asyncio
async def test_daily_cooldown():
    async with get_conn() as conn:
        await conn.execute(
            "DELETE FROM daily_rewards WHERE user_id IN (SELECT id FROM users WHERE telegram_id = %s)",  # noqa: E501
            (999010,),
        )  # noqa: E501
        await conn.execute(
            "DELETE FROM events WHERE user_id IN (SELECT id FROM users WHERE telegram_id = %s)",
            (999010,),
        )  # noqa: E501
        await conn.execute("DELETE FROM users WHERE telegram_id = %s", (999010,))
        cur = await conn.execute(
            "INSERT INTO users (telegram_id, balance_units, segment, created_at) VALUES (%s, %s, %s, now() - interval '2 days') RETURNING id",  # noqa: E501
            (999010, 0, "new"),
        )
        user = await cur.fetchone()
        await conn.commit()
        user = dict(user)
        user["segment"] = "new"
        await claim_daily(conn, user)
        with pytest.raises(ValueError):
            await claim_daily(conn, user)


@pytest.mark.asyncio
async def test_mission_progression():
    async with get_conn() as conn:
        await conn.execute(
            "DELETE FROM mission_progress WHERE user_id IN (SELECT id FROM users WHERE telegram_id = %s)",  # noqa: E501
            (999011,),
        )  # noqa: E501
        await conn.execute(
            "DELETE FROM events WHERE user_id IN (SELECT id FROM users WHERE telegram_id = %s)",
            (999011,),
        )  # noqa: E501
        await conn.execute("DELETE FROM users WHERE telegram_id = %s", (999011,))
        cur = await conn.execute(
            "INSERT INTO users (telegram_id, balance_units) VALUES (%s, %s) RETURNING id",
            (999011, 0),
        )
        uid = (await cur.fetchone())["id"]
        await conn.commit()
        mp = await update_progress(conn, uid, "open_case")
        assert mp["progress"].get("open_case") is True
