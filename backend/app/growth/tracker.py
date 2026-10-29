async def record_click(conn, account_id: int, post_id: int):
    await conn.execute("UPDATE growth_posts SET clicks = clicks + 1 WHERE id = %s", (post_id,))
    await conn.commit()


async def record_signup(conn, post_id: int):
    await conn.execute("UPDATE growth_posts SET signups = signups + 1 WHERE id = %s", (post_id,))
    await conn.commit()
