import pytest

from app.db import get_conn
from core.engine.ledger.ledger import CrossCurrencyForbidden, post_entry


@pytest.mark.asyncio
async def test_no_cross_currency_credit():
    async with get_conn() as conn, conn.transaction():
        cur = await conn.execute(
            "INSERT INTO users (telegram_id) VALUES (%s) RETURNING id", (8899020,)
        )
        user_id = (await cur.fetchone())["id"]
        await post_entry(conn, user_id, "units", 1000, "test_setup", "gold_setup")
        await post_entry(conn, user_id, "freebets", 500, "test_setup", "copper_setup")
        with pytest.raises(CrossCurrencyForbidden):
            await post_entry(conn, user_id, "units", 100, "item_sold", "forbidden", "cases_freebet")
        await post_entry(conn, user_id, "freebets", -100, "case_open", "copper_only")
        row = await (
            await conn.execute(
                "SELECT balance_units, balance_freebets FROM users WHERE id=%s", (user_id,)
            )
        ).fetchone()
        assert row["balance_units"] == 1000
        assert row["balance_freebets"] == 400
