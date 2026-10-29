import os

import redis.asyncio as redis

CACHE_TTL = 5


async def get_flag(conn, key: str, default: bool = True) -> bool:
    r = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    cached = await r.get(f"flag:{key}")
    if cached is not None:
        await r.aclose()
        return cached.decode() == "1"
    row = await (
        await conn.execute("SELECT value FROM system_config WHERE key = %s", (key,))
    ).fetchone()
    val = default
    if row:
        v = row["value"]
        val = bool(v.get("value", v.get("enabled", default))) if isinstance(v, dict) else bool(v)
    await r.setex(f"flag:{key}", CACHE_TTL, "1" if val else "0")
    await r.aclose()
    return val


async def set_flag(conn, key: str, value: bool, who: str = "admin"):
    await conn.execute(
        "INSERT INTO system_config (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()",  # noqa: E501
        (key, {"value": value}),
    )
    await conn.commit()
    # audit
    await conn.execute(
        "INSERT INTO events (user_id, event_type, payload) VALUES (%s, %s, %s)",
        (None, "flag_change", {"key": key, "value": value, "who": who}),
    )
    await conn.commit()
