async def compute_segment(conn, user_id: int) -> str:
    row = await (
        await conn.execute("SELECT COUNT(*) AS c FROM case_openings WHERE user_id = %s", (user_id,))
    ).fetchone()
    count = int(row["c"]) if row else 0
    if count < 10:
        return "new"
    if count < 50:
        return "active"
    return "veteran"
