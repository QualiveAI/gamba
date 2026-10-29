from psycopg.types.json import Json


async def track(conn, user_id, event_type, payload=None, idempotency_key=None):
    if idempotency_key:
        row = await (
            await conn.execute(
                "SELECT id FROM events WHERE idempotency_key = %s", (idempotency_key,)
            )
        ).fetchone()
        if row:
            return row["id"]
    cur = await conn.execute(
        "INSERT INTO events (user_id, event_type, payload, idempotency_key) VALUES (%s, %s, %s, %s) RETURNING id",  # noqa: E501
        (user_id, event_type, Json(payload or {}), idempotency_key),
    )
    row = await cur.fetchone()
    return row["id"]
