from datetime import UTC, datetime


async def assign_proxy(conn, account_id: int, proxy_id: int, geo: str):
    # geo must match
    await conn.execute(
        "INSERT INTO growth_accounts (id, platform, geo, proxy_id, status, warmup_started_at) VALUES (%s, %s, %s, %s, 'warming', now()) ON CONFLICT (id) DO UPDATE SET proxy_id = EXCLUDED.proxy_id, geo = EXCLUDED.geo",  # noqa: E501
        (account_id, "telegram", geo, proxy_id),
    )
    await conn.commit()


def warmup_policy(platform: str, geo: str):
    return {
        "read_only_hours": 24,
        "light_post_per_day": 1,
        "full_post_per_day": 3,
    }


async def can_post(conn, account_id: int):
    row = await (
        await conn.execute(
            "SELECT warmup_started_at FROM growth_accounts WHERE id = %s", (account_id,)
        )
    ).fetchone()
    if row is None:
        return False
    started = row["warmup_started_at"]
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    age = (datetime.now(UTC) - started).total_seconds() / 3600.0
    return not age < 24
