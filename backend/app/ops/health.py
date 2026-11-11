"""Ограниченные по времени probes; ответы не содержат DSN и ошибок драйверов."""

import asyncio

import redis.asyncio as redis

from app.config import settings
from app.db import get_pool


async def check_database() -> dict[str, str]:
    result = {"db": "fail", "schema": "fail", "outbox": "fail"}
    timeout = settings.readiness_timeout_seconds
    try:
        async with asyncio.timeout(timeout), get_pool().connection(timeout=timeout) as conn:
            await conn.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (str(max(1, int(timeout * 1000))),),
            )
            state = await (
                await conn.execute(
                    "SELECT pg_is_in_recovery() AS recovery, "
                    "current_setting('transaction_read_only') AS read_only"
                )
            ).fetchone()
            if state is None or state["recovery"] or state["read_only"] != "off":
                return result
            result["db"] = "ok"
            tables = await (
                await conn.execute(
                    "SELECT to_regclass('public.schema_migrations') IS NOT NULL AS migrations, "
                    "to_regclass('public.bot_registry') IS NOT NULL AS registry, "
                    "to_regclass('public.bot_inbox') IS NOT NULL AS inbox, "
                    "to_regclass('public.bot_outbox') IS NOT NULL AS outbox"
                )
            ).fetchone()
            if tables is None:
                return result
            if tables["migrations"] and settings.expected_schema_version:
                migration = await (
                    await conn.execute(
                        "SELECT 1 FROM public.schema_migrations WHERE filename = %s",
                        (settings.expected_schema_version,),
                    )
                ).fetchone()
                guest_column = await (
                    await conn.execute(
                        "SELECT 1 FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND table_name = 'users' "
                        "AND column_name = 'is_guest'"
                    )
                ).fetchone()
                if migration and guest_column:
                    result["schema"] = "ok"
            if tables["registry"] and tables["inbox"] and tables["outbox"]:
                # Реальное SELECT проверяет доступ роли приложения, не только имя таблицы.
                # Длина очереди и dead-letter требуют отдельных алертов, не рестартов API.
                for table in ("bot_registry", "bot_inbox", "bot_outbox"):
                    await conn.execute(f"SELECT status FROM public.{table} LIMIT 0")
                result["outbox"] = "ok"
    except Exception:
        # Даже частичный успех не означает готовность после timeout/ошибки соединения.
        return {"db": "fail", "schema": "fail", "outbox": "fail"}
    return result


async def check_redis() -> str:
    timeout = settings.readiness_timeout_seconds
    client = None
    try:
        async with asyncio.timeout(timeout):
            client = redis.from_url(
                settings.redis_url,
                socket_connect_timeout=timeout,
                socket_timeout=timeout,
                retry_on_timeout=False,
                decode_responses=True,
            )
            return "ok" if await client.ping() else "fail"
    except Exception:
        return "fail"
    finally:
        if client is not None:
            try:
                async with asyncio.timeout(min(timeout, 0.5)):
                    await client.aclose()
            except Exception:
                pass


async def readiness() -> dict[str, str]:
    database, redis_status = await asyncio.gather(check_database(), check_redis())
    checks = {**database, "redis": redis_status}
    return {"status": "ok" if all(v == "ok" for v in checks.values()) else "fail", **checks}
