import json

import pytest

from app.db import get_conn
from app.games.crash import cash_crash, multiplier_at, start_crash
from app.games.mines import cashout, mines_mult, reveal, start
from app.games.shell import pick_shell, shell_mult, start_shell

TG = 999099


async def _mk_user(conn):
    for table in ("events", "user_items", "case_openings", "shell_sessions", "crash_sessions", "mines_sessions"):  # noqa: E501
        await conn.execute(
            f"DELETE FROM {table} WHERE user_id IN (SELECT id FROM users WHERE telegram_id = %s)",  # noqa: E501
            (TG,),
        )
    await conn.execute(
        "DELETE FROM ledger_entries WHERE user_id IN (SELECT id FROM users WHERE telegram_id = %s)",  # noqa: E501
        (TG,),
    )
    await conn.execute("DELETE FROM users WHERE telegram_id = %s", (TG,))
    cur = await conn.execute(
        "INSERT INTO users (telegram_id, balance_units) VALUES (%s, 10000) RETURNING id",
        (TG,),
    )
    u = dict(await cur.fetchone())
    await conn.execute(
        "INSERT INTO ledger_entries (user_id, delta, reason, balance_after, currency) "
        "VALUES (%s, 10000, 'test_setup', 10000, 'units')",
        (u["id"],),
    )
    await conn.commit()
    return u


async def _ledger_sum(conn, uid):
    row = await (
        await conn.execute(
            "SELECT COALESCE(SUM(delta),0) AS s FROM ledger_entries WHERE user_id=%s AND currency='units'",  # noqa: E501
            (uid,),
        )
    ).fetchone()
    return int(row["s"])


def test_multipliers_demo_formulas():
    assert shell_mult(3) == 2.91
    assert shell_mult(4) == 3.88
    assert shell_mult(5) == 4.85
    assert mines_mult(3, 1) == 1.10
    assert mines_mult(3, 2) > mines_mult(3, 1)
    assert multiplier_at(0) == 1.0
    assert multiplier_at(10) > 2.0  # exp(1.2) ≈ 3.32


@pytest.mark.asyncio
async def test_shell_session_flow():
    async with get_conn() as conn:
        u = await _mk_user(conn)
        s = await start_shell(conn, u, 100, 1, "client-seed-1")
        assert s["cups"] == 3 and 0 <= s["ball"] < 3 and s["mult"] == 2.91
        assert await _ledger_sum(conn, u["id"]) == 10000 - 100  # ставка списана
        # забираем гарантированный выигрыш: угадываем фиксированный шарик
        res = await pick_shell(conn, u, s["session_id"], s["ball"])
        assert res["win"] is True and res["payout"] == 291
        assert await _ledger_sum(conn, u["id"]) == 10000 - 100 + 291
        # повторный pick по закрытой сессии запрещён
        with pytest.raises(ValueError):
            await pick_shell(conn, u, s["session_id"], s["ball"])


@pytest.mark.asyncio
async def test_shell_invalid_level():
    async with get_conn() as conn:
        u = await _mk_user(conn)
        with pytest.raises(ValueError):
            await start_shell(conn, u, 100, 7, "cs")


@pytest.mark.asyncio
async def test_crash_session_flow():
    async with get_conn() as conn:
        u = await _mk_user(conn)
        s = await start_crash(conn, u, 100)
        assert s["crash_point"] >= 1.0 and s["growth"] == 0.12
        assert await _ledger_sum(conn, u["id"]) == 10000 - 100
        res = await cash_crash(conn, u, s["session_id"])
        if res["win"]:
            assert res["payout"] == int(100 * res["m"]) and res["m"] < s["crash_point"]
            assert await _ledger_sum(conn, u["id"]) == 10000 - 100 + res["payout"]
        else:
            assert res["m"] == s["crash_point"]
            assert await _ledger_sum(conn, u["id"]) == 10000 - 100
        with pytest.raises(ValueError):
            await cash_crash(conn, u, s["session_id"])  # раунд уже закрыт


@pytest.mark.asyncio
async def test_mines_stake_and_ladder_cashout():
    async with get_conn() as conn:
        u = await _mk_user(conn)
        s = await start(conn, u, 100, 3)
        assert await _ledger_sum(conn, u["id"]) == 10000 - 100  # ставка списывается
        # фиксируем мины подальше от клетки 0
        await conn.execute(
            "UPDATE mines_sessions SET mines = %s WHERE id = %s", (json.dumps([22, 23, 24]), s["session_id"])  # noqa: E501
        )
        await conn.commit()
        r = await reveal(conn, s["session_id"], 0, u)
        assert r["hit_mine"] is False
        res = await cashout(conn, s["session_id"], u)
        assert res["payout"] == 110  # 100 × mines_mult(3,1)=1.10
        assert await _ledger_sum(conn, u["id"]) == 10000 - 100 + 110


@pytest.mark.asyncio
async def test_sell_and_history():
    from app.api.wallet import sell_item, wallet_history

    async with get_conn() as conn:
        u = await _mk_user(conn)
        cur = await conn.execute(
            "INSERT INTO user_items (user_id, label, game_key, currency, value_coins, rarity, image) "
            "VALUES (%s, 'Pet Teste', 'brainrot', 'units', 250, 'common', 'assets/demo/x.webp') RETURNING id",  # noqa: E501
            (u["id"],),
        )
        item_id = (await cur.fetchone())["id"]
        await conn.commit()  # sell_item/history открывают своё соединение
        res = await sell_item(item_id, u)
        assert res["sold"] is True and res["value"] == 250
        assert await _ledger_sum(conn, u["id"]) == 10000 + 250
        # «предметные» записи истории берутся из case_openings — создаём кейс и открытие
        crow = await (
            await conn.execute(
                "INSERT INTO cases (name, price_units, currency, rtp_profile, active, cover) "
                "VALUES ('Test Case', 99, 'units', '{}', TRUE, NULL) RETURNING id"
            )
        ).fetchone()
        rid = await (
            await conn.execute(
                "INSERT INTO case_rewards (case_id, reward_type, game_key, label, nominal_units, "
                "weight, image, rarity) VALUES (%s, 'balance', 't', 'Pet Teste2', 100, 10, "
                "'assets/demo/brainrot1.webp', 'common') RETURNING id",
                (crow["id"],),
            )
        ).fetchone()
        await conn.execute(
            "INSERT INTO case_openings (user_id, case_id, reward_id, server_seed, server_seed_hash, "
            "client_seed, nonce, roll, rtp_used) VALUES (%s, %s, %s, 's', 'h', 'c', 1, 0.5, 0.5)",
            (u["id"], crow["id"], rid["id"]),
        )
        await conn.commit()
        hist = await wallet_history(u)
        texts = [h["text"] for h in hist]
        assert "item_sold" in texts and "test_setup" in texts
        item_entries = [h for h in hist if h["kind"] == "item"]
        assert any(h["image"] for h in item_entries)
