from datetime import date


async def update_streak(conn, user_id: int, deposit_date: date):
    row = await (
        await conn.execute(
            "SELECT current_streak, last_deposit_date FROM deposit_streaks WHERE user_id = %s",
            (user_id,),  # noqa: E501
        )
    ).fetchone()
    if row is None:
        await conn.execute(
            "INSERT INTO deposit_streaks (user_id, current_streak, last_deposit_date) VALUES (%s, %s, %s)",  # noqa: E501
            (user_id, 1, deposit_date),
        )
        await conn.commit()
        return {"streak": 1, "bonus_percent": 0}
    last = row["last_deposit_date"]
    streak = int(row["current_streak"])
    if last is not None and (deposit_date - last).days == 1:
        streak += 1
    elif last == deposit_date:
        pass
    else:
        streak = 1
    bonus = 0.10 if streak >= 3 else 0.0
    await conn.execute(
        "UPDATE deposit_streaks SET current_streak = %s, last_deposit_date = %s, bonus_percent = %s WHERE user_id = %s",  # noqa: E501
        (streak, deposit_date, bonus, user_id),
    )
    await conn.commit()
    return {"streak": streak, "bonus_percent": bonus}
