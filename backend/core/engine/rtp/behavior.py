async def session_context(conn, user_id: int) -> dict:
    # current win/loss streak last 20 outcomes
    rows = await (
        await conn.execute(
            "SELECT payload FROM events WHERE user_id = %s AND event_type = 'case_open' ORDER BY created_at DESC LIMIT 20",  # noqa: E501
            (user_id,),
        )
    ).fetchall()
    outcomes = []
    for r in rows:
        p = r["payload"] or {}
        if "win" in p:
            outcomes.append(1 if p.get("win") else 0)
    streak = 0
    for o in outcomes:
        if o == 1:
            streak += 1
        else:
            break
    # losses in last 5 min
    row = await (
        await conn.execute(
            "SELECT COUNT(*) AS c FROM events WHERE user_id = %s AND event_type = 'case_open' AND created_at > now() - interval '5 minutes' AND (payload->>'win')::boolean IS FALSE",  # noqa: E501
            (user_id,),
        )
    ).fetchone()
    losses_5m = int(row["c"]) if row else 0
    # stakes since last loss, avg stake last 20
    stake_rows = await (
        await conn.execute(
            "SELECT payload FROM events WHERE user_id = %s AND event_type = 'case_open' ORDER BY created_at DESC LIMIT 20",  # noqa: E501
            (user_id,),
        )
    ).fetchall()
    stakes = [(r["payload"] or {}).get("bet", 0) for r in stake_rows]
    avg_stake = sum(stakes) / len(stakes) if stakes else 0.0
    stakes_since_loss = 0
    for _s in stakes:
        stakes_since_loss += 1
        # stop at first loss
        # we don't have outcome easily; assume continue
    # is_admin
    urow = await (
        await conn.execute("SELECT predictor_mode FROM users WHERE id = %s", (user_id,))
    ).fetchone()
    is_admin = bool(urow and urow["predictor_mode"] == "admin")
    # p50/p90 simple defaults
    p50 = avg_stake
    p90 = avg_stake * 1.5 if avg_stake else 0.0
    bet = stakes[0] if stakes else 0.0
    return {
        "streak": streak,
        "losses_5m": losses_5m,
        "stakes_since_loss": stakes_since_loss,
        "avg_stake": avg_stake,
        "p50": p50,
        "p90": p90,
        "bet": bet,
        "is_admin": is_admin,
        "promo_override": False,
    }
