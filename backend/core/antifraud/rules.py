from datetime import UTC


async def velocity(conn, user_id, window_minutes=60):
    row = await (
        await conn.execute(
            "SELECT COUNT(*) AS c FROM withdrawals WHERE user_id = %s AND created_at > now() - make_interval(mins => %s)",  # noqa: E501
            (user_id, window_minutes),
        )
    ).fetchone()
    return int(row["c"]) if row else 0


async def new_account_cooldown(conn, user):
    created = (
        user.get("created_at") if isinstance(user, dict) else getattr(user, "created_at", None)
    )
    if created is None:
        return False
    from datetime import datetime

    if isinstance(created, str):
        created = datetime.fromisoformat(created.replace("Z", "+00:00"))
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return (datetime.now(UTC) - created).total_seconds() < 3600


def region_mismatch(user, rail_geo):
    user_region = user.get("region") if isinstance(user, dict) else getattr(user, "region", None)
    return bool(user_region and rail_geo and user_region != rail_geo)


async def multi_account(conn, ip_hash, device_hash):
    row = await (
        await conn.execute(
            "SELECT COUNT(*) AS c FROM users WHERE signup_ip = %s OR device_fingerprint = %s",
            (ip_hash, device_hash),
        )
    ).fetchone()
    return (int(row["c"]) if row else 0) >= 3


async def chase_anomaly(conn, user_id):
    # placeholder threshold
    return False


async def activation_fail_rate(conn, user_id):
    row = await (
        await conn.execute(
            "SELECT COUNT(*) FILTER (WHERE status = 'rejected') AS rej, COUNT(*) AS tot FROM withdrawals WHERE user_id = %s",  # noqa: E501
            (user_id,),
        )
    ).fetchone()
    rej = int(row["rej"]) if row else 0
    tot = int(row["tot"]) if row else 0
    return tot >= 5 and (rej / tot) > 0.2
