async def health_check(conn, proxy_id: int):
    await conn.execute(
        "UPDATE growth_proxies SET last_checked_at = now(), status = 'active' WHERE id = %s",
        (proxy_id,),
    )
    await conn.commit()


async def rotate_on_ban(conn, proxy_id: int):
    await conn.execute("UPDATE growth_proxies SET status = 'dead' WHERE id = %s", (proxy_id,))
    await conn.commit()
