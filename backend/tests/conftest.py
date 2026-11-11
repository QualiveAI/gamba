import asyncio
import os
import sys
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import psycopg
import pytest
from psycopg import sql
from test_environment import configure_test_environment, validate_test_database_url

# До импорта app.* и сбора тестов: никогда не подхватываем рабочий .env.
try:
    TEST_DSN = configure_test_environment()
except ValueError as exc:
    raise pytest.UsageError(str(exc)) from exc

from app.db import close_pool, init_pool  # noqa: E402


@pytest.fixture(autouse=True)
def _backend_working_directory(monkeypatch):
    # Legacy игровые плагины читают configs/ относительно корня backend.
    monkeypatch.chdir(Path(__file__).resolve().parents[1])


def _assert_isolated_connection(conn) -> None:
    expected = validate_test_database_url(TEST_DSN)
    row = conn.execute(
        "SELECT current_database(), current_user, r.rolsuper, r.rolcreatedb, "
        "r.rolcreaterole FROM pg_roles r WHERE r.rolname = current_user"
    ).fetchone()
    if not row or row[0] != expected["dbname"] or row[1] != expected["user"]:
        raise pytest.UsageError("Подключение не соответствует выделенной тестовой БД")
    if any(row[2:]):
        raise pytest.UsageError("Тесты должны использовать ограниченную роль, не администратора БД")
    connections = conn.execute(
        "SELECT datname FROM pg_database WHERE datallowconn "
        "AND NOT datistemplate AND datname <> current_database() "
        "AND has_database_privilege(current_user, oid, 'CONNECT')"
    ).fetchall()
    if connections:
        raise pytest.UsageError("Тестовая роль имеет доступ к другим БД; очистка запрещена")


@pytest.fixture(autouse=True, scope="session")
def _clean_db_once():
    """Очищаем только выделенную *_test БД под изолированной ролью."""
    if os.getenv("DATABASE_URL") != TEST_DSN:
        raise pytest.UsageError("DATABASE_URL изменён после установки тестового окружения")
    with psycopg.connect(TEST_DSN, connect_timeout=3) as conn:
        _assert_isolated_connection(conn)
        cur = conn.execute(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname='public' AND tablename <> 'schema_migrations'"
        )
        tables = [r[0] for r in cur.fetchall()]
        if tables:
            conn.execute(
                sql.SQL("TRUNCATE TABLE {} RESTART IDENTITY CASCADE").format(
                    sql.SQL(", ").join(sql.Identifier(t) for t in tables)
                )
            )
    yield


@pytest.fixture(autouse=True)
async def _pool():
    await init_pool()
    try:
        yield
    finally:
        await close_pool()


@pytest.fixture(autouse=True)
def _no_external_http(monkeypatch):
    """HTTP в тестах только через явные fake/ASGI transports; настоящих PSP/ботов нет."""
    import httpx

    def reject(*args, **kwargs):
        raise RuntimeError("Внешний HTTP в тестах запрещён: используйте MockTransport")

    async def reject_async(*args, **kwargs):
        raise RuntimeError("Внешний HTTP в тестах запрещён: используйте MockTransport")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", reject)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", reject_async)
