import pytest

from app.db import get_conn
from core.engine.ledger.ledger import CrossCurrencyForbidden, post_entry


@pytest.mark.asyncio
async def test_freebets_cannot_be_withdrawn():
    async with get_conn() as conn, conn.transaction():
        cur = await conn.execute(
            "INSERT INTO users (telegram_id) VALUES (%s) RETURNING id",
            (8899021,),
        )
        user_id = (await cur.fetchone())["id"]
        await post_entry(conn, user_id, "freebets", 100000, "test_setup", "freebet_setup")
        with pytest.raises(CrossCurrencyForbidden, match="freebets cannot be withdrawn"):
            await post_entry(conn, user_id, "freebets", -1000, "withdrawal_request", "forbidden")
        row = await (
            await conn.execute(
                "SELECT balance_units, balance_freebets FROM users WHERE id=%s", (user_id,)
            )
        ).fetchone()
        assert row["balance_units"] == 0
        assert row["balance_freebets"] == 100000
