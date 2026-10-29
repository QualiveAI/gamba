from datetime import UTC, datetime


async def claim_daily(conn, user):
    user_id = user["id"] if isinstance(user, dict) else user.id
    segment = user.get("segment") if isinstance(user, dict) else getattr(user, "segment", "new")
    amount = {"new": 5, "active": 10, "veteran": 20}.get(segment, 5)
    row = await (
        await conn.execute(
            "SELECT claimed_at FROM daily_rewards WHERE user_id = %s ORDER BY claimed_at DESC LIMIT 1",  # noqa: E501
            (user_id,),
        )
    ).fetchone()
    if row and (datetime.now(UTC) - row["claimed_at"]).total_seconds() < 86400:
        raise ValueError("cooldown")  # noqa: B904
    await conn.execute(
        "INSERT INTO daily_rewards (user_id, amount_units) VALUES (%s, %s)", (user_id, amount)
    )
    await conn.execute(
        "UPDATE users SET balance_units = balance_units + %s, last_claim_at = now() WHERE id = %s",
        (amount, user_id),
    )  # noqa: E501
    await conn.commit()
    from app.analytics.events import track

    await track(conn, user_id, "daily_claim", {"amount": amount})
    await conn.commit()
    return {"amount": amount}
