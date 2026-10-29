from datetime import date, timedelta

from psycopg.types.json import Json


async def daily_rollup(conn, d: date) -> dict:
    # per-game RTP from case_openings
    rows = await (
        await conn.execute(
            "SELECT co.case_id, SUM(co.roll) AS rolls, COUNT(*) AS n, "
            "SUM(cr.nominal_units) AS reward_sum, SUM(c.price_units) AS price_sum "
            "FROM case_openings co JOIN case_rewards cr ON cr.id = co.reward_id "
            "JOIN cases c ON c.id = co.case_id "
            "WHERE co.created_at::date = %s GROUP BY co.case_id",
            (d,),
        )
    ).fetchall()
    game_rtp = {}
    for r in rows:
        price_sum = int(r["price_sum"]) if r["price_sum"] else 0
        reward_sum = int(r["reward_sum"]) if r["reward_sum"] else 0
        game_rtp[str(r["case_id"])] = (reward_sum / price_sum) if price_sum else 0.0

    # retention D1/D7
    new_users = await (
        await conn.execute("SELECT id FROM users WHERE created_at::date = %s", (d,))
    ).fetchall()
    new_ids = [r["id"] for r in new_users]
    d1 = 0
    d7 = 0
    for uid in new_ids:
        r1 = await (
            await conn.execute(
                "SELECT 1 FROM users WHERE id = %s AND last_claim_at::date >= %s LIMIT 1",
                (uid, d + timedelta(days=1)),
            )
        ).fetchone()
        if r1:
            d1 += 1
        r7 = await (
            await conn.execute(
                "SELECT 1 FROM users WHERE id = %s AND last_claim_at::date >= %s LIMIT 1",
                (uid, d + timedelta(days=7)),
            )
        ).fetchone()
        if r7:
            d7 += 1
    retention_d1 = (d1 / len(new_ids)) if new_ids else 0.0
    retention_d7 = (d7 / len(new_ids)) if new_ids else 0.0

    # conversion rate: signup->deposit
    deposits = await (
        await conn.execute(
            "SELECT COUNT(DISTINCT user_id) AS c FROM events WHERE event_type = 'deposit' AND created_at::date = %s",  # noqa: E501
            (d,),
        )
    ).fetchone()
    conv = (int(deposits["c"]) / len(new_ids)) if new_ids else 0.0

    # LTV estimate: avg balance of new users
    ltv = 0.0
    if new_ids:
        bal = await (
            await conn.execute(
                "SELECT COALESCE(AVG(balance_units),0) AS a FROM users WHERE id = ANY(%s)",
                (new_ids,),
            )
        ).fetchone()
        ltv = float(bal["a"]) if bal else 0.0

    data = {
        "game_rtp": game_rtp,
        "retention_d1": retention_d1,
        "retention_d7": retention_d7,
        "conversion": conv,
        "ltv": ltv,
        "new_users": len(new_ids),
    }
    await conn.execute(
        "INSERT INTO analytics_daily (date, data) VALUES (%s, %s) ON CONFLICT (date) DO UPDATE SET data = EXCLUDED.data",  # noqa: E501
        (d, Json(data)),
    )
    await conn.commit()
    return data
