import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextvars import ContextVar
from dataclasses import dataclass
from math import ceil

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.config import settings

_pool: AsyncConnectionPool | None = None


class _SafePoolLog(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # psycopg_pool включает raw exception/connection repr в записи своего logger.
        # Даже malformed DSN не должен раскрывать пароль; оставляем уровень события.
        record.msg = "Событие пула PostgreSQL; состояние доступно через readiness"
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        return True


_safe_pool_log = _SafePoolLog()


async def _restart_reconnect(pool: AsyncConnectionPool) -> None:
    # После reconnect_timeout драйвер прекращает текущую попытку. Пустой pool
    # запускаем снова без рестарта API; backoff остаётся внутри psycopg_pool.
    if not pool.closed and pool.get_stats().get("pool_size", 0) == 0:
        await pool.check()


@dataclass
class ConnectionFence:
    """Соединение владельца DB-lock; после отзыва нельзя переходить в общий pool."""

    connection: psycopg.AsyncConnection
    active: bool = True

    def revoke(self) -> None:
        self.active = False


_fence: ContextVar[ConnectionFence | None] = ContextVar("db_connection_fence", default=None)


async def init_pool() -> None:
    global _pool
    if _pool is not None:
        return
    logging.getLogger("psycopg.pool").addFilter(_safe_pool_log)
    pool = AsyncConnectionPool(
        conninfo=settings.database_url,
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
        timeout=settings.db_pool_timeout_seconds,
        reconnect_timeout=30,
        reconnect_failed=_restart_reconnect,
        kwargs={
            "row_factory": dict_row,
            "autocommit": False,
            "connect_timeout": ceil(settings.db_connect_timeout_seconds),
        },
        open=False,
        name="api",
    )
    # API поднимается без ожидания БД: liveness не зависит от внешних сервисов.
    await pool.open(wait=False)
    _pool = pool


async def close_pool() -> None:
    global _pool
    pool, _pool = _pool, None
    if pool is not None:
        await pool.close(timeout=settings.db_pool_timeout_seconds)


def get_pool() -> AsyncConnectionPool:
    if _pool is None:
        raise RuntimeError("Пул БД не инициализирован")
    return _pool


@contextlib.asynccontextmanager
async def fenced_connection(fence: ConnectionFence) -> AsyncIterator[None]:
    """Все get_conn внутри задачи используют только сессию с advisory lock."""
    if not fence.active or fence.connection.closed or fence.connection.broken:
        raise psycopg.OperationalError("Сессия фоновой задачи недействительна")
    token = _fence.set(fence)
    try:
        yield
    finally:
        _fence.reset(token)


@contextlib.asynccontextmanager
async def get_conn() -> AsyncIterator[psycopg.AsyncConnection]:
    fence = _fence.get()
    if fence is not None:
        # Нельзя переподключиться здесь: это допустило бы запись старого владельца lock.
        if not fence.active or fence.connection.closed or fence.connection.broken:
            raise psycopg.OperationalError("Сессия фоновой задачи потеряла владение")
        yield fence.connection
        return
    async with get_pool().connection() as conn:
        yield conn


async def healthcheck() -> tuple[str, str]:
    """Совместимый probe без утечки DSN и текста ошибок зависимостей."""
    from app.ops.health import check_database, check_redis

    database, redis_status = await asyncio.gather(check_database(), check_redis())
    return database["db"], redis_status
