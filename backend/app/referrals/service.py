import re

from psycopg.types.json import Jsonb

from app.config import settings


async def create_referral_link(user_id: int) -> str:
    username = getattr(settings, "bot_username", "").lstrip("@")
    if not re.fullmatch(r"[A-Za-z0-9_]{5,32}", username):
        raise ValueError("bot_username_not_configured")
    return f"https://t.me/{username}?start=ref_{user_id}"


async def handle_referral(
    conn,
    new_user_id: int,
    referrer_id: int,
    signup_ip: str | None = None,
    device_fingerprint: str | None = None,
    *,
    commit: bool = True,
):
    if new_user_id == referrer_id:
        return {"status": "ignored"}
    users = await (
        await conn.execute(
            "SELECT id FROM users WHERE id IN (%s, %s) AND is_guest = FALSE ORDER BY id FOR UPDATE",
            (new_user_id, referrer_id),
        )
    ).fetchall()
    if len(users) != 2:
        return {"status": "ignored"}
    existing = await (
        await conn.execute("SELECT status FROM referrals WHERE referee_id = %s", (new_user_id,))
    ).fetchone()
    if existing:
        return {"status": existing["status"]}
    # Антифрод: три аккаунта с одинаковым IP/устройством за сутки.
    for column, value, reason in (
        ("signup_ip", signup_ip, "ip_abuse"),
        ("device_fingerprint", device_fingerprint, "device_abuse"),
    ):
        if not value:
            continue
        row = await (
            await conn.execute(
                f"SELECT COUNT(*) AS c FROM users WHERE {column} = %s "
                "AND created_at > now() - interval '24 hours'",
                (value,),
            )
        ).fetchone()
        if row and int(row["c"]) >= 3:
            await conn.execute(
                "INSERT INTO referral_flags (user_id, reason, details) VALUES (%s, %s, %s)",
                (new_user_id, reason, Jsonb({column: value})),
            )
            if commit:
                await conn.commit()
            return {"status": "flagged"}
    row = await (
        await conn.execute(
            "INSERT INTO referrals (referrer_id, referee_id, status) VALUES (%s, %s, 'held') "
            "ON CONFLICT (referee_id) DO NOTHING RETURNING id",
            (referrer_id, new_user_id),
        )
    ).fetchone()
    if row:
        await conn.execute(
            "INSERT INTO events (user_id, event_type, payload, idempotency_key) "
            "VALUES (%s, 'referral_signup', %s, %s) ON CONFLICT (idempotency_key) DO NOTHING",
            (new_user_id, Jsonb({"referrer_id": referrer_id}), f"referral_signup:{new_user_id}"),
        )
    if commit:
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
