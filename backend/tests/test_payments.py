import pytest

from app.db import get_conn
from app.payments import gifts, yoomoney_sbp


@pytest.mark.asyncio
async def test_manual_claim_flow():
    async with get_conn() as conn:
        await conn.execute(
            "DELETE FROM payment_polling WHERE user_id IN (SELECT id FROM users WHERE telegram_id = %s)",  # noqa: E501
            (999007,),
        )
        await conn.execute("DELETE FROM users WHERE telegram_id = %s", (999007,))
        cur = await conn.execute(
            "INSERT INTO users (telegram_id, balance_units) VALUES (%s, %s) RETURNING id",
            (999007, 0),
        )
        uid = (await cur.fetchone())["id"]
        await conn.commit()
        cur = await conn.execute(
            "INSERT INTO payment_polling (user_id, provider, external_id, amount_rub, status) VALUES (%s, %s, %s, %s, 'pending') RETURNING id",  # noqa: E501
            (uid, "yoomoney", "ext-1", 100),
        )
        pid = (await cur.fetchone())["id"]
        await conn.commit()
        await yoomoney_sbp.manual_claim(conn, pid, "http://receipt")
        row = await (
            await conn.execute("SELECT status FROM payment_polling WHERE id = %s", (pid,))
        ).fetchone()
        assert row["status"] == "manual_review"


@pytest.mark.asyncio
async def test_gift_pending_review():
    async with get_conn() as conn:
        await conn.execute(
            "DELETE FROM gift_conversions WHERE user_id IN (SELECT id FROM users WHERE telegram_id = %s)",  # noqa: E501
            (999008,),
        )
        await conn.execute("DELETE FROM users WHERE telegram_id = %s", (999008,))
        cur = await conn.execute(
            "INSERT INTO users (telegram_id, balance_units) VALUES (%s, %s) RETURNING id",
            (999008, 0),
        )
        uid = (await cur.fetchone())["id"]
        await conn.commit()
        res = await gifts.handle_gift(conn, uid, "gift-1")
        assert res["status"] == "pending_review"
