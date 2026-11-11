"""Явное применение миграций. DATABASE_URL обязателен; --status ничего не меняет."""

import argparse
import hashlib
import os
import sys
from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
MIGRATION_LOCK = 894102415


def get_dsn() -> str:
    dsn = os.getenv("DATABASE_URL", "")
    if not dsn:
        raise SystemExit("Задайте DATABASE_URL явно; рабочий .env автоматически не читается")
    return dsn


def tracking_exists(conn: psycopg.Connection) -> bool:
    return conn.execute("SELECT to_regclass('public.schema_migrations')").fetchone()[0] is not None


def ensure_tracking_table(conn: psycopg.Connection) -> None:
    if not tracking_exists(conn):
        existing = conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' LIMIT 1"
        ).fetchone()
        if existing:
            raise RuntimeError(
                "БД не пустая, но schema_migrations отсутствует. "
                "Сначала сверка существующей схемы и явный baseline администратором"
            )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "filename TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now(), sha256 TEXT)"
    )
    conn.execute("ALTER TABLE schema_migrations ADD COLUMN IF NOT EXISTS sha256 TEXT")


def applied(conn: psycopg.Connection) -> set[str]:
    if not tracking_exists(conn):
        return set()
    return {row[0] for row in conn.execute("SELECT filename FROM schema_migrations").fetchall()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", action="store_true", help="только чтение статуса")
    args = parser.parse_args()
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        raise SystemExit("Файлы миграций не найдены")

    with psycopg.connect(get_dsn(), autocommit=True, connect_timeout=5) as conn:
        if args.status:
            done = applied(conn)
            for migration in files:
                print(f"[{'OK' if migration.name in done else 'PENDING'}] {migration.name}")
            return 0
        if not conn.execute("SELECT pg_try_advisory_lock(%s)", (MIGRATION_LOCK,)).fetchone()[0]:
            raise SystemExit("Другой процесс уже применяет миграции")
        try:
            ensure_tracking_table(conn)
            done = dict(conn.execute("SELECT filename, sha256 FROM schema_migrations").fetchall())
            count = 0
            for migration in files:
                text = migration.read_text(encoding="utf-8")
                digest = hashlib.sha256(text.replace("\r\n", "\n").encode()).hexdigest()
                if migration.name in done:
                    if done[migration.name] and done[migration.name] != digest:
                        raise RuntimeError(f"Изменена применённая миграция: {migration.name}")
                    continue
                with conn.transaction():
                    conn.execute(text)
                    conn.execute(
                        "INSERT INTO schema_migrations (filename, sha256) VALUES (%s, %s)",
                        (migration.name, digest),
                    )
                count += 1
                print(f"Применено: {migration.name}")
            print(f"Готово: {count} новых миграций")
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK,))
    return 0


if __name__ == "__main__":
    sys.exit(main())
