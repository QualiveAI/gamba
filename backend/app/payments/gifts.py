from core.engine.ledger.ledger import post_entry


async def handle_gift(conn, user_id: int, gift_id: str):
    row = await (
        await conn.execute(
            "SELECT id, price_rub, status FROM gift_conversions WHERE user_id = %s AND gift_id = %s",  # noqa: E501
            (user_id, gift_id),
        )
    ).fetchone()
    if row is None:
        cur = await conn.execute(
            "INSERT INTO gift_conversions (user_id, gift_id, status) VALUES (%s, %s, 'pending_review') RETURNING id",  # noqa: E501
            (user_id, gift_id),
        )
        await conn.commit()
        return {"status": "pending_review", "id": (await cur.fetchone())["id"]}
    if row["status"] != "priced":
        return {"status": row["status"], "id": row["id"]}
    # credit 90%
    credited = int(float(row["price_rub"]) * 0.9)
    await post_entry(conn, user_id, "units", credited, "deposit_gift", gift_id)
    await conn.execute(
        "UPDATE gift_conversions SET status = 'credited', credited_units = %s, decided_at = now() WHERE id = %s",
        (credited, row["id"]),
    )
    from app.analytics.events import track

    await track(conn, user_id, "deposit", {"provider": "gift", "units": credited})
    await conn.commit()
    return {"status": "credited", "units": credited}