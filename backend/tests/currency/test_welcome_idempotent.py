import pytest

from app.db import get_conn
from core.rewards.welcome import grant_welcome


@pytest.mark.asyncio
async def test_welcome_is_idempotent():
    async with get_conn() as conn:
        cur = await conn.execute(
            "INSERT INTO users (telegram_id) VALUES (%s) RETURNING id", (8899022,)
        )
        user = dict(await cur.fetchone())
        await conn.commit()
        first = await grant_welcome(conn, user)
        second = await grant_welcome(conn, user)
        assert first["granted"] is True
        assert second["granted"] is False
        rows = await (
            await conn.execute(
                "SELECT delta FROM ledger_entries WHERE user_id=%s AND reason='welcome_freebet'",
                (user["id"],),
            )
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["delta"] == first["amount"]
