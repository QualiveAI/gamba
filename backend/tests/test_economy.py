import pytest

from app.db import get_conn
from app.economy.segments import compute_segment
from core.engine.ledger.ledger import post_entry, reconcile


@pytest.mark.asyncio
async def test_ledger_invariant():
    async with get_conn() as conn:
        await conn.execute(
            "DELETE FROM ledger_entries WHERE user_id IN (SELECT id FROM users WHERE telegram_id = %s)",  # noqa: E501
            (999003,),
        )
        await conn.execute("DELETE FROM users WHERE telegram_id = %s", (999003,))
        cur = await conn.execute(
            "INSERT INTO users (telegram_id, balance_units, segment) VALUES (%s, %s, %s) RETURNING id",  # noqa: E501
            (999003, 0, "new"),
        )
        uid = (await cur.fetchone())["id"]
        await conn.commit()
        await post_entry(conn, uid, "units", 100, "test", "r1")
        await post_entry(conn, uid, "units", -30, "test", "r2")
        await conn.commit()
        broken = await reconcile(conn)
        assert uid not in broken


@pytest.mark.asyncio
async def test_segment_new():
    async with get_conn() as conn:
        await conn.execute("DELETE FROM users WHERE telegram_id = %s", (999004,))
        cur = await conn.execute(
            "INSERT INTO users (telegram_id, balance_units, segment) VALUES (%s, %s, %s) RETURNING id",  # noqa: E501
            (999004, 0, "new"),
        )
        uid = (await cur.fetchone())["id"]
        await conn.commit()
        seg = await compute_segment(conn, uid)
        assert seg == "new"
