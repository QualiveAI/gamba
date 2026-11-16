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
        await conn.execute(
            "DELETE FROM mission_progress WHERE user_id IN (SELECT id FROM users WHERE telegram_id = %s)",
            (999011,),
        )
        await conn.execute("DELETE FROM users WHERE telegram_id = %s", (999011,))
        cur = await conn.execute(
            "INSERT INTO users (telegram_id, balance_units) VALUES (%s, %s) RETURNING id",
            (999011, 0),
        )
        uid = (await cur.fetchone())["id"]
        await conn.commit()
        mp = await update_progress(conn, uid, "open_case")
        assert mp["progress"].get("open_case") is True


@pytest.mark.asyncio
async def test_daily_claim_goes_through_ledger():
    """Прямой UPDATE баланса ломал инвариант balance == SUM(delta)."""
    tg = 999012
    async with get_conn() as conn:
        # Тест идемпотентен: сбрасываем только историю чекинов тестового игрока,
        # пользователя не удаляем (на него ссылаются другие таблицы).
        await conn.execute(
            "DELETE FROM daily_rewards WHERE user_id IN "
            "(SELECT id FROM users WHERE telegram_id = %s)",
            (tg,),
        )
        cur = await conn.execute(
            "INSERT INTO users (telegram_id, balance_units, segment, created_at) "
            "VALUES (%s, 0, 'new', now() - interval '2 days') "
            "ON CONFLICT (telegram_id) DO UPDATE SET balance_freebets = 0, "
            "balance_units = 0, last_claim_at = NULL RETURNING id, telegram_id",
            (tg,),
        )
        user = dict(await cur.fetchone())
        await conn.commit()
        user["segment"] = "new"
        before = await (
            await conn.execute(
                "SELECT COALESCE(SUM(delta), 0) AS s FROM ledger_entries WHERE user_id = %s",
                (user["id"],),
            )
        ).fetchone()
        await claim_daily(conn, user)
        row = await (
            await conn.execute("SELECT balance_freebets FROM users WHERE id = %s", (user["id"],))
        ).fetchone()
        entry = await (
            await conn.execute(
                "SELECT delta, reason FROM ledger_entries WHERE user_id = %s "
                "ORDER BY id DESC LIMIT 1",
                (user["id"],),
            )
        ).fetchone()
        total = await (
            await conn.execute(
                "SELECT COALESCE(SUM(delta), 0) AS s FROM ledger_entries WHERE user_id = %s",
                (user["id"],),
            )
        ).fetchone()
        # Баланс выставляется в ноль перед чекином, поэтому итог — ровно награда.
        assert int(row["balance_freebets"]) == 500
        assert dict(entry) == {"delta": 500, "reason": "daily_claim_freebets"}
        assert int(total["s"]) == int(before["s"]) + 500
        assert int(total["s"]) == int(row["balance_freebets"])
