import csv
import os
from datetime import UTC, datetime, timedelta


def load_pool(path: str):
    rows = []
    if not path or not os.path.exists(path):
        return rows
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append({"token": r.get("token"), "name": r.get("name")})
    return rows


async def register_bot(conn, token: str, name: str | None = None):
    await conn.execute(
        "INSERT INTO bot_pool (token, name, warmup_until) VALUES (%s, %s, %s)",
        (token, name, datetime.now(UTC) + timedelta(hours=24)),
    )
    await conn.commit()


async def is_warmup(conn, token: str) -> bool:
    row = await (
        await conn.execute("SELECT warmup_until FROM bot_pool WHERE token = %s", (token,))
    ).fetchone()
    if row is None:
        return True
    return row["warmup_until"] is not None and row["warmup_until"] > datetime.now(UTC)
