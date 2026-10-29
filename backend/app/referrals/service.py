async def create_referral_link(user_id: int) -> str:
    return f"https://t.me/robloxcasebot?start=ref_{user_id}"


async def handle_referral(
    conn,
    new_user_id: int,
    referrer_id: int,
    signup_ip: str | None = None,
    device_fingerprint: str | None = None,
):  # noqa: E501
    # anti-fraud: 3+ accounts same ip/device in 24h
    if signup_ip:
        row = await (
            await conn.execute(
                "SELECT COUNT(*) AS c FROM users WHERE signup_ip = %s AND created_at > now() - interval '24 hours'",  # noqa: E501
                (signup_ip,),
            )
        ).fetchone()
        if row and int(row["c"]) >= 3:
            await conn.execute(
                "INSERT INTO referral_flags (user_id, reason, details) VALUES (%s, %s, %s)",
                (new_user_id, "ip_abuse", {"ip": signup_ip}),
            )
            await conn.commit()
            return {"status": "flagged"}
    if device_fingerprint:
        row = await (
            await conn.execute(
                "SELECT COUNT(*) AS c FROM users WHERE device_fingerprint = %s AND created_at > now() - interval '24 hours'",  # noqa: E501
                (device_fingerprint,),
            )
        ).fetchone()
        if row and int(row["c"]) >= 3:
            await conn.execute(
                "INSERT INTO referral_flags (user_id, reason, details) VALUES (%s, %s, %s)",
                (new_user_id, "device_abuse", {"fp": device_fingerprint}),
            )
            await conn.commit()
            return {"status": "flagged"}
    await conn.execute(
        "INSERT INTO referrals (referrer_id, referee_id, status) VALUES (%s, %s, 'held')",
        (referrer_id, new_user_id),
    )
    await conn.commit()
    from app.analytics.events import track

    await track(conn, new_user_id, "referral_signup", {"referrer_id": referrer_id})
    await conn.commit()
    return {"status": "held"}


async def release_referral_bonus(conn):
    rows = await (
        await conn.execute(
            "SELECT id, referrer_id, referee_id FROM referrals WHERE status = 'held' AND created_at < now() - interval '7 days'"  # noqa: E501
        )
    ).fetchall()
    for r in rows:
        # check referee deposited
        dep = await (
            await conn.execute(
                "SELECT 1 FROM events WHERE user_id = %s AND event_type = 'deposit' LIMIT 1",
                (r["referee_id"],),  # noqa: E501
            )
        ).fetchone()
        flag = await (
            await conn.execute(
                "SELECT 1 FROM referral_flags WHERE user_id = %s LIMIT 1", (r["referee_id"],)
            )
        ).fetchone()
        if dep and not flag:
            await conn.execute(
                "UPDATE users SET balance_units = balance_units + 10 WHERE id = %s",
                (r["referrer_id"],),  # noqa: E501
            )
            await conn.execute(
                "UPDATE users SET balance_units = balance_units + 10 WHERE id = %s",
                (r["referee_id"],),  # noqa: E501
            )
            await conn.execute(
                "UPDATE referrals SET status = 'released', bonus_released_at = now() WHERE id = %s",
                (r["id"],),  # noqa: E501
            )
            from app.analytics.events import track

            await track(conn, r["referrer_id"], "referral_bonus", {"referee_id": r["referee_id"]})
    await conn.commit()
