import asyncio
import os
import sys
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import psycopg
import pytest
from psycopg import sql

from app.db import close_pool, init_pool


def _dsn() -> str:
    dsn = os.getenv("DATABASE_URL", "")
    if dsn:
        return dsn
    env_path = Path(__file__).resolve().parent.parent / ".env"
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("DATABASE_URL не найден")


@pytest.fixture(autouse=True, scope="session")
def _clean_db_once():
    """Очистка БД один раз за прогон: тесты не изолированы между файлами
    (общие telegram_id, события) и требуют чистую схему на старте."""
    with psycopg.connect(_dsn()) as conn:
        cur = conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename <> 'schema_migrations'"
        )
        tables = [r[0] for r in cur.fetchall()]
        if tables:
            with conn.transaction():
                conn.execute(
                    sql.SQL("TRUNCATE TABLE {} RESTART IDENTITY CASCADE").format(
                        sql.SQL(", ").join(sql.Identifier(t) for t in tables)
                    )
                )
    yield


@pytest.fixture(autouse=True)
async def _pool():
    await init_pool()
    yield
    await close_pool()
