"""Один scheduler на один PostgreSQL writer: python -m app.ops.scheduler.

Lock и ВСЕ запросы job выполняются в одной физической сессии. Потерянная
сессия не заменяется внутри job: повторное подключение возможно только после
отмены старых задач и нового advisory lock. Это не fencing между разными БД.
"""

import asyncio
import contextlib
import logging
import signal
import sys
from collections.abc import Awaitable, Callable
from math import ceil

import psycopg
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from psycopg.rows import dict_row

from app.config import settings
from app.db import ConnectionFence, fenced_connection
from core.catalog.analytics import auto_pause_all_cases

logger = logging.getLogger(__name__)
SCHEDULER_LOCK_KEY = 0x57494E4453434844
HEARTBEAT_SECONDS = 5
JOB_TIMEOUT_SECONDS = 60


def create_scheduler(
    job: Callable[[], Awaitable[object]] = auto_pause_all_cases,
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        job,
        "interval",
        minutes=10,
        id="auto_pause",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=30,
    )
    return scheduler


async def acquire_leadership(conn: psycopg.AsyncConnection) -> bool:
    async with asyncio.timeout(settings.db_connect_timeout_seconds):
        state = await (
            await conn.execute(
                "SELECT pg_is_in_recovery() AS recovery, "
                "current_setting('transaction_read_only') AS read_only"
            )
        ).fetchone()
        if state is None or state["recovery"] or state["read_only"] != "off":
            return False
        row = await (
            await conn.execute("SELECT pg_try_advisory_lock(%s) AS acquired", (SCHEDULER_LOCK_KEY,))
        ).fetchone()
        await conn.commit()
        return bool(row and row["acquired"])


async def _wait(stop: asyncio.Event, lost: asyncio.Event, delay: float) -> None:
    waiting = [asyncio.create_task(stop.wait()), asyncio.create_task(lost.wait())]
    try:
        await asyncio.wait(waiting, timeout=delay, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in waiting:
            task.cancel()
        await asyncio.gather(*waiting, return_exceptions=True)


async def serve_leader(conn: psycopg.AsyncConnection, stop: asyncio.Event) -> None:
    fence = ConnectionFence(conn)
    lost = asyncio.Event()
    job_lock = asyncio.Lock()
    jobs: set[asyncio.Task] = set()

    async def run_job() -> None:
        task = asyncio.current_task()
        if task is None or stop.is_set() or lost.is_set() or not fence.active:
            return
        jobs.add(task)
        try:
            async with job_lock, asyncio.timeout(JOB_TIMEOUT_SECONDS), fenced_connection(fence):
                await auto_pause_all_cases()
                # Закрываем read-only транзакцию, если job не делала собственный commit.
                await conn.commit()
        except asyncio.CancelledError:
            fence.revoke()
            lost.set()
            raise
        except Exception as exc:
            fence.revoke()
            lost.set()
            logger.warning("Задача остановлена; сессия отозвана (%s)", type(exc).__name__)
        finally:
            jobs.discard(task)

    scheduler = create_scheduler(run_job)
    scheduler.start()
    logger.info("Scheduler получил блокировку writer")
    try:
        while not stop.is_set() and not lost.is_set():
            await _wait(stop, lost, HEARTBEAT_SECONDS)
            if stop.is_set() or lost.is_set():
                break
            # Heartbeat не должен коммитить транзакцию одновременно работающей job.
            # У самой job есть отдельный timeout и нет переподключения.
            if not job_lock.locked():
                async with job_lock, asyncio.timeout(settings.db_connect_timeout_seconds):
                    row = await (
                        await conn.execute(
                            "SELECT pg_is_in_recovery() AS recovery, "
                            "current_setting('transaction_read_only') AS read_only"
                        )
                    ).fetchone()
                    if row is None or row["recovery"] or row["read_only"] != "off":
                        raise psycopg.OperationalError("Writer больше не доступен")
                    await conn.commit()
    finally:
        fence.revoke()
        scheduler.shutdown(wait=False)
        # AsyncIOScheduler завершает executor через callback event loop.
        await asyncio.sleep(0)
        running = list(jobs)
        for task in running:
            task.cancel()
        if running:
            await asyncio.gather(*running, return_exceptions=True)
        # Соединение закрывает run_scheduler до следующей попытки получить lock.


async def run_scheduler(stop: asyncio.Event | None = None) -> None:
    stop = stop if stop is not None else asyncio.Event()
    lost = asyncio.Event()
    while not stop.is_set():
        conn = None
        try:
            async with asyncio.timeout(settings.db_connect_timeout_seconds + 1):
                conn = await psycopg.AsyncConnection.connect(
                    settings.database_url,
                    row_factory=dict_row,
                    autocommit=False,
                    connect_timeout=ceil(settings.db_connect_timeout_seconds),
                    application_name="windrop-scheduler",
                    options=(
                        "-c statement_timeout=15000 -c idle_in_transaction_session_timeout=65000"
                    ),
                    keepalives=1,
                    keepalives_idle=10,
                    keepalives_interval=5,
                    keepalives_count=3,
                )
            if await acquire_leadership(conn):
                await serve_leader(conn, stop)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Сообщения драйвера и DSN могут содержать чувствительные данные.
            logger.warning("Scheduler недоступен; повтор после паузы (%s)", type(exc).__name__)
        finally:
            if conn is not None:
                await conn.close()
        if not stop.is_set():
            await _wait(stop, lost, HEARTBEAT_SECONDS)


async def _main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, stop.set)
        except NotImplementedError:
            signal.signal(signum, lambda *_: loop.call_soon_threadsafe(stop.set))
    await run_scheduler(stop)


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_main())
