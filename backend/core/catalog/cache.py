import json

from core.ops.redis_client import get_redis


async def get_cached(key):
    r = await get_redis()
    val = await r.get(key)
    if val:
        return json.loads(val)
    return None


async def set_cached(key, value, ttl=60):
    r = await get_redis()
    await r.set(key, json.dumps(value), ex=ttl)


async def invalidate(pattern):
    r = await get_redis()
    keys = await r.keys(pattern)
    if keys:
        await r.delete(*keys)
