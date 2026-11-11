import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import psycopg
import pytest

from app import db
from app.ops import scheduler


@pytest.mark.parametrize("state", ["revoked", "closed", "broken"])
async def test_fence_never_falls_back_to_pool(monkeypatch, state):
    conn = SimpleNamespace(closed=False, broken=False)
    fence = db.ConnectionFence(conn)
    pool = Mock(side_effect=AssertionError("Fenced job не должна использовать pool"))
    monkeypatch.setattr(db, "get_pool", pool)
    async with db.fenced_connection(fence):
        if state == "revoked":
            fence.revoke()
        else:
            setattr(conn, state, True)
        with pytest.raises(psycopg.OperationalError):
            async with db.get_conn():
                pytest.fail("Потерянный fence разрешил доступ к БД")
    pool.assert_not_called()


async def test_job_connections_stay_on_lock_session_and_context_resets(monkeypatch):
    conn = SimpleNamespace(closed=False, broken=False)
    pool = Mock(side_effect=RuntimeError("Общий pool вне контекста"))
    monkeypatch.setattr(db, "get_pool", pool)
    async with db.fenced_connection(db.ConnectionFence(conn)):
        for _ in range(2):
            async with db.get_conn() as actual:
                assert actual is conn
    with pytest.raises(RuntimeError, match="Общий pool"):
        async with db.get_conn():
            pytest.fail("Fence не был сброшен")
    pool.assert_called_once()


async def test_child_task_inherits_revocable_fence(monkeypatch):
    conn = SimpleNamespace(closed=False, broken=False)
    fence = db.ConnectionFence(conn)
    released = asyncio.Event()

    async def child():
        await released.wait()
        with pytest.raises(psycopg.OperationalError):
            async with db.get_conn():
                pytest.fail("Старая дочерняя задача переподключилась")

    monkeypatch.setattr(db, "get_pool", Mock(side_effect=AssertionError("Нельзя менять сессию")))
    async with db.fenced_connection(fence):
        task = asyncio.create_task(child())
    fence.revoke()
    released.set()
    await task


@pytest.mark.parametrize("acquired", [False, True])
async def test_leadership_uses_nonblocking_advisory_lock(acquired):
    conn = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                SimpleNamespace(
                    fetchone=AsyncMock(return_value={"recovery": False, "read_only": "off"})
                ),
                SimpleNamespace(fetchone=AsyncMock(return_value={"acquired": acquired})),
            ]
        ),
        commit=AsyncMock(),
    )
    assert await scheduler.acquire_leadership(conn) is acquired
    assert "pg_try_advisory_lock" in conn.execute.call_args_list[1].args[0]
    assert conn.execute.call_args_list[1].args[1] == (scheduler.SCHEDULER_LOCK_KEY,)
    conn.commit.assert_awaited_once()


async def test_read_replica_never_leads():
    conn = SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(
                fetchone=AsyncMock(return_value={"recovery": True, "read_only": "on"})
            )
        )
    )
    assert await scheduler.acquire_leadership(conn) is False
    conn.execute.assert_awaited_once()


async def test_graceful_reconnect_closes_old_session_before_new_lock(monkeypatch):
    stop = asyncio.Event()
    order = []
    first = SimpleNamespace(close=AsyncMock(side_effect=lambda: order.append("close-first")))
    second = SimpleNamespace(close=AsyncMock(side_effect=lambda: order.append("close-second")))
    connections = iter((first, second))

    async def connect(*args, **kwargs):
        conn = next(connections)
        order.append("connect-first" if conn is first else "connect-second")
        return conn

    async def lead(conn, event):
        if conn is first:
            raise psycopg.OperationalError("Сессия оборвана")
        event.set()

    monkeypatch.setattr(scheduler.psycopg.AsyncConnection, "connect", connect)
    monkeypatch.setattr(scheduler, "acquire_leadership", AsyncMock(return_value=True))
    monkeypatch.setattr(scheduler, "serve_leader", lead)
    monkeypatch.setattr(scheduler, "_wait", AsyncMock())
    await scheduler.run_scheduler(stop)
    assert order == ["connect-first", "close-first", "connect-second", "close-second"]
    assert scheduler.acquire_leadership.await_count == 2


async def test_failed_lock_never_starts_jobs(monkeypatch):
    stop = asyncio.Event()
    conn = SimpleNamespace(close=AsyncMock())

    async def lock(_conn):
        stop.set()
        return False

    serve = AsyncMock(side_effect=AssertionError("Нельзя работать без DB lock"))
    monkeypatch.setattr(scheduler.psycopg.AsyncConnection, "connect", AsyncMock(return_value=conn))
    monkeypatch.setattr(scheduler, "acquire_leadership", lock)
    monkeypatch.setattr(scheduler, "serve_leader", serve)
    await scheduler.run_scheduler(stop)
    serve.assert_not_called()
    conn.close.assert_awaited_once()


def test_scheduler_is_separate_and_limits_job_instances():
    from app import main

    assert not hasattr(main, "scheduler")
    jobs = scheduler.create_scheduler().get_jobs()
    assert len(jobs) == 1
    assert jobs[0].id == "auto_pause"
    assert jobs[0].max_instances == 1
    assert jobs[0].coalesce is True
