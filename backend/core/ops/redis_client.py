"""Общий Redis-клиент на процесс.

Upstash free считает и команды, и соединения: прежний код делал redis.from_url()
на каждый вызов, то есть новое TCP+TLS-соединение на каждое чтение флага/кэша.
Здесь — ленивый singleton с явными таймаутами; закрывается на shutdown API.
"""

import asyncio
import contextlib
import os

import redis.asyncio as redis

_client: redis.Redis | None = None
_lock = asyncio.Lock()


def _url() -> str:
    return os.getenv("REDIS_URL", "redis://localhost:6379/0")


async def get_redis() -> redis.Redis:
    global _client
    if _client is not None:
        return _client
    async with _lock:
        if _client is None:
            _client = redis.from_url(
                _url(),
                socket_connect_timeout=3,
                socket_timeout=3,
                retry_on_timeout=False,
                decode_responses=True,
            )
    return _client


async def close_redis() -> None:
    global _client
    client, _client = _client, None
    if client is not None:
        with contextlib.suppress(Exception):
            await client.aclose()
