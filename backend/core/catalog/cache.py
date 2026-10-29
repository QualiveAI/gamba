import json
import os

import redis.asyncio as redis


async def get_cached(key):
    r = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    val = await r.get(key)
    await r.aclose()
    if val:
        return json.loads(val)
    return None


async def set_cached(key, value, ttl=60):
    r = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    await r.setex(key, ttl, json.dumps(value))
    await r.aclose()


async def invalidate(pattern):
    r = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    keys = await r.keys(pattern)
    if keys:
        await r.delete(*keys)
    await r.aclose()
