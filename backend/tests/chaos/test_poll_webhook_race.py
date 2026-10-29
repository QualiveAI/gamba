import pytest

from app.db import get_conn


@pytest.mark.asyncio
async def test_poll_webhook_race():
    async with get_conn() as conn:
        await conn.execute(
            "INSERT INTO users (telegram_id, balance_units, region, created_at) VALUES (900002, 0, 'US', now()) ON CONFLICT (telegram_id) DO NOTHING"
        )
        await conn.commit()
        row = await (await conn.execute("SELECT COUNT(*) AS c FROM users WHERE telegram_id = 900002")).fetchone()
        assert row["c"] == 1
        assert row["c"] != 2
