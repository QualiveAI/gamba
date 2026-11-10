"""Раннер миграций: применяет migrations/*.sql по порядку, ведёт schema_migrations.

Использование:
    python tools/migrate.py            # применить недостающие миграции
    python tools/migrate.py --status   # только показать статус
"""
import argparse
import sys
from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def get_dsn() -> str:
    import os

    dsn = os.getenv("DATABASE_URL", "")
    if dsn:
        return dsn
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip()
    raise SystemExit("DATABASE_URL не найден (env или .env)")


def ensure_tracking_table(conn: psycopg.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            filename TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def applied(conn: psycopg.Connection) -> set[str]:
    rows = conn.execute("SELECT filename FROM schema_migrations").fetchall()
    return {r[0] for r in rows}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", action="store_true", help="показать статус и выйти")
    args = parser.parse_args()

    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        print(f"Нет миграций в {MIGRATIONS_DIR}")
        return 1

    with psycopg.connect(get_dsn()) as conn:
        ensure_tracking_table(conn)
        done = applied(conn)

        if args.status:
            for f in files:
                mark = "OK " if f.name in done else "PENDING"
                print(f"[{mark}] {f.name}")
            return 0

        new_files = [f for f in files if f.name not in done]
        if not new_files:
            print("Схема актуальна, применять нечего.")
            return 0

        for f in new_files:
            sql = f.read_text(encoding="utf-8")
            with conn.transaction():
                conn.execute(sql)
                conn.execute(
                    "INSERT INTO schema_migrations (filename) VALUES (%s)", (f.name,)
                )
            print(f"применено: {f.name}")

    print(f"Готово: {len(new_files)} миграций.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
