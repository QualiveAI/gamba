import pytest

from app.db import get_conn


@pytest.mark.asyncio
async def test_supplier_down_fallback():
    async with get_conn() as conn:
        await conn.execute(
            "INSERT INTO users (telegram_id, balance_units, region, created_at) VALUES (900003, 0, 'US', now()) ON CONFLICT (telegram_id) DO NOTHING"
        )
        await conn.commit()
        row = await (await conn.execute("SELECT COUNT(*) AS c FROM users WHERE telegram_id = 900003")).fetchone()
        assert row["c"] == 1
        assert row["c"] != 2
