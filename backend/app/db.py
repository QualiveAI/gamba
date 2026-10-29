import contextlib
from collections.abc import AsyncIterator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.config import settings

_pool: AsyncConnectionPool | None = None


async def init_pool() -> None:
    global _pool
    _pool = AsyncConnectionPool(
        conninfo=settings.database_url,
        min_size=1,
        max_size=10,
        kwargs={"row_factory": dict_row, "autocommit": False},
        open=False,
    )
    await _pool.open()


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> AsyncConnectionPool:
    if _pool is None:
        raise RuntimeError("pool not initialized")  # noqa: B904
    return _pool


@contextlib.asynccontextmanager
async def get_conn() -> AsyncIterator[psycopg.AsyncConnection]:
    pool = get_pool()
    async with pool.connection() as conn:
        yield conn


async def healthcheck() -> tuple[str, str]:
    try:
        async with get_conn() as conn:
            await conn.execute("SELECT 1")
        db = "ok"
    except Exception:
        db = "fail"
    try:
        import redis.asyncio as redis

        r = redis.from_url(settings.redis_url)
        await r.ping()
        await r.aclose()
        redis_status = "ok"
    except Exception:
        redis_status = "fail"
    return db, redis_status
