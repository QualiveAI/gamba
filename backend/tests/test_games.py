import pytest

from app.db import get_conn
from app.games.crash import crash_multiplier
from app.games.mines import reveal, start
from app.games.upgrade import upgrade_chance


def test_upgrade_chance():
    assert abs(upgrade_chance(10, 20) - 0.4) < 1e-9


def test_crash_multiplier_min():
    assert crash_multiplier(0.0) >= 1.0


@pytest.mark.asyncio
async def test_mines_bias_next_move():
    async with get_conn() as conn:
        await conn.execute(
            "DELETE FROM mines_sessions WHERE user_id IN (SELECT id FROM users WHERE telegram_id = %s)",  # noqa: E501
            (999006,),
        )  # noqa: E501
        await conn.execute(
            "DELETE FROM events WHERE user_id IN (SELECT id FROM users WHERE telegram_id = %s)",
            (999006,),
        )
        await conn.execute("DELETE FROM users WHERE telegram_id = %s", (999006,))
        cur = await conn.execute(
            "INSERT INTO users (telegram_id, balance_units, predictor_mode) VALUES (%s, %s, %s) RETURNING id",  # noqa: E501
            (999006, 1000, "user"),
        )
        user = await cur.fetchone()
        await conn.commit()
        user = dict(user)
        user["predictor_mode"] = "user"
        s = await start(conn, user, 200, 0)
        sid = s["session_id"]
        # first reveal no bias
        r1 = await reveal(conn, sid, 0, user)
        assert r1["bias_applied"] is False
        # second reveal may bias (bet > threshold? 200 > 100 yes)
        await reveal(conn, sid, 1, user)
        # revealed cells should not be in mines; check session mines
        row = await (
            await conn.execute("SELECT mines, revealed FROM mines_sessions WHERE id = %s", (sid,))
        ).fetchone()
        mines = set(row["mines"])
        revealed = set(row["revealed"])
        assert mines.isdisjoint(revealed)
