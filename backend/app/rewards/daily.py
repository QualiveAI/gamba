from datetime import UTC, datetime


async def claim_daily(conn, user):
    user_id = user["id"] if isinstance(user, dict) else user.id
    amount = 500  # 500 медных монеток (фрибетов) ежедневно
    row = await (
        await conn.execute(
            "SELECT claimed_at FROM daily_rewards WHERE user_id = %s "
            "ORDER BY claimed_at DESC LIMIT 1",
            (user_id,),
        )
    ).fetchone()
    if row and (datetime.now(UTC) - row["claimed_at"]).total_seconds() < 86400:
        raise ValueError("cooldown")  # noqa: B904
    # streak: сколько дней подряд (с yesterday или today назад)
    marks = await (
        await conn.execute(
            "SELECT claimed_at::date AS d FROM daily_rewards WHERE user_id = %s "
            "ORDER BY claimed_at::date DESC LIMIT 400",
            (user_id,),
        )
    ).fetchall()
    days = {r["d"] for r in marks}
    today = datetime.now(UTC).date()
    from datetime import timedelta

    streak = 0
    cursor = today
    if today not in days:
        cursor = today - timedelta(days=1)
    while cursor in days:
        streak += 1
        cursor -= timedelta(days=1)
    # amount_units хранит медные монетки (фрибеты)
    await conn.execute(
        "INSERT INTO daily_rewards (user_id, amount_units) VALUES (%s, %s)",
        (user_id, amount),
    )
    new_streak = streak + 1
    await conn.execute(
        "UPDATE users SET balance_freebets = balance_freebets + %s, last_claim_at = now() "
        "WHERE id = %s",
        (amount, user_id),
    )  # noqa: E501
    await conn.commit()
    from app.analytics.events import track

    await track(conn, user_id, "daily_claim", {"amount": amount})
    await conn.commit()
    return {"amount": amount, "streak": new_streak}
