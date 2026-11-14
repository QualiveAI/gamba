import json

from core.ops.exceptions import ServiceDisabled
from core.ops.redis_client import get_redis

CACHE_TTL = 5


async def get_flag(conn, key: str, default: bool = True) -> bool:
    r = await get_redis()
    cached = await r.get(f"flag:{key}")
    if cached is not None:
        return cached == "1"
    row = await (
        await conn.execute("SELECT value FROM system_config WHERE key = %s", (key,))
    ).fetchone()
    val = default
    if row:
        v = row["value"]
        val = bool(v.get("value", v.get("enabled", default))) if isinstance(v, dict) else bool(v)
    await r.set(f"flag:{key}", "1" if val else "0", ex=CACHE_TTL)
    return val


async def set_flag(conn, key: str, value: bool, who: str = "admin"):
    await conn.execute(
        "INSERT INTO system_config (key, value) VALUES (%s, %s) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
        (key, json.dumps({"value": value})),
    )
    try:
        r = await get_redis()
        await r.delete(f"flag:{key}")
    except Exception:
        pass
    await conn.execute(
        "INSERT INTO events (user_id, event_type, payload) VALUES (%s, %s, %s)",
        (None, "flag_change", json.dumps({"key": key, "value": value, "who": who})),
    )
    await conn.commit()


async def require_enabled(conn, key: str, service: str = "service") -> None:
    enabled = await get_flag(conn, key, True)
    if not enabled:
        raise ServiceDisabled(service)
