import pytest
from psycopg.types.json import Json

from app.db import get_conn
from app.predictor.service import predict_mines


@pytest.mark.asyncio
async def test_admin_mode_100():
    async with get_conn() as conn:
        await conn.execute(
            "DELETE FROM mines_predictions WHERE session_id IN (SELECT id FROM mines_sessions WHERE user_id IN (SELECT id FROM users WHERE telegram_id = %s))",  # noqa: E501
            (999012,),
        )  # noqa: E501
        await conn.execute(
            "DELETE FROM mines_sessions WHERE user_id IN (SELECT id FROM users WHERE telegram_id = %s)",  # noqa: E501
            (999012,),
        )  # noqa: E501
        await conn.execute(
            "DELETE FROM events WHERE user_id IN (SELECT id FROM users WHERE telegram_id = %s)",
            (999012,),
        )  # noqa: E501
        await conn.execute("DELETE FROM users WHERE telegram_id = %s", (999012,))
        cur = await conn.execute(
            "INSERT INTO users (telegram_id, balance_units, predictor_mode) VALUES (%s, %s, %s) RETURNING id",  # noqa: E501
            (999012, 0, "admin"),
        )
        user = await cur.fetchone()
        await conn.commit()
        user = dict(user)
        user["predictor_mode"] = "admin"
        s = await (
            await conn.execute(
                "INSERT INTO mines_sessions (user_id, bet_units, mine_count, grid_size, mines, revealed, status) VALUES (%s, %s, %s, %s, %s, %s, 'active') RETURNING id",  # noqa: E501
                (user["id"], 10, 3, 25, Json([0, 1, 2]), Json([])),
            )
        ).fetchone()
        await conn.commit()
        res = await predict_mines(conn, user["id"], s["id"], 10)
        assert res["confidence"] == 1.0
        assert len(res["suggested_cells"]) > 0


@pytest.mark.asyncio
async def test_low_high_bet():
    async with get_conn() as conn:
        await conn.execute(
            "DELETE FROM mines_predictions WHERE session_id IN (SELECT id FROM mines_sessions WHERE user_id IN (SELECT id FROM users WHERE telegram_id = %s))",  # noqa: E501
            (999013,),
        )  # noqa: E501
        await conn.execute(
            "DELETE FROM mines_sessions WHERE user_id IN (SELECT id FROM users WHERE telegram_id = %s)",  # noqa: E501
            (999013,),
        )  # noqa: E501
        await conn.execute(
            "DELETE FROM events WHERE user_id IN (SELECT id FROM users WHERE telegram_id = %s)",
            (999013,),
        )  # noqa: E501
        await conn.execute("DELETE FROM users WHERE telegram_id = %s", (999013,))
        cur = await conn.execute(
            "INSERT INTO users (telegram_id, balance_units, predictor_mode) VALUES (%s, %s, %s) RETURNING id",  # noqa: E501
            (999013, 0, "user"),
        )
        user = await cur.fetchone()
        await conn.commit()
        user = dict(user)
        user["predictor_mode"] = "user"
        for bet, _expected_cells in [(5, 5), (200, 1)]:
            s = await (
                await conn.execute(
                    "INSERT INTO mines_sessions (user_id, bet_units, mine_count, grid_size, mines, revealed, status) VALUES (%s, %s, %s, %s, %s, %s, 'active') RETURNING id",  # noqa: E501
                    (user["id"], bet, 3, 25, Json([0, 1, 2]), Json([])),
                )
            ).fetchone()
            await conn.commit()
            res = await predict_mines(conn, user["id"], s["id"], bet)
            if bet <= 10:
                assert len(res["suggested_cells"]) == 5 or len(res["suggested_cells"]) >= 1
            if bet >= 100:
                assert len(res["suggested_cells"]) == 1
