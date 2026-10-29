THRESHOLD = 100


async def record_win(conn, user_id: int, amount: int, game: str):
    if amount < THRESHOLD:
        return None
    await conn.execute(
        "INSERT INTO win_feed (user_id, game, amount_units) VALUES (%s, %s, %s)",
        (user_id, game, amount),  # noqa: E501
    )
    # keep last 50
    await conn.execute(
        "DELETE FROM win_feed WHERE id NOT IN (SELECT id FROM win_feed ORDER BY id DESC LIMIT 50)"
    )
    await conn.commit()
    return True


async def get_feed(conn, limit: int = 50):
    rows = await (
        await conn.execute(
            "SELECT id, user_id, game, amount_units, created_at FROM win_feed ORDER BY id DESC LIMIT %s",  # noqa: E501
            (limit,),  # noqa: E501
        )
    ).fetchall()
    return [dict(r) for r in rows]
