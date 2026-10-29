import secrets


async def create_invite_code(conn, user_id: int) -> str:
    code = secrets.token_urlsafe(6)[:8]
    return code


async def get_invite_progress(conn, user_id: int):
    row = await (
        await conn.execute(
            "SELECT COUNT(*) AS c FROM referrals WHERE referrer_id = %s AND status = 'released'",
            (user_id,),
        )
    ).fetchone()
    count = int(row["c"]) if row else 0
    # tiers
    tiers = [(1, 50), (5, 200), (20, 1000)]
    current = 0
    for threshold, bonus in tiers:
        if count >= threshold:
            current = bonus
    return {"qualified_invites": count, "tier_bonus": current}


async def handle_invite_signup(conn, new_user_id: int, invite_code: str):
    # link to referrer? placeholder: no lookup table; just grant referee freebets
    await conn.commit()
    return {"status": "held"}
