import json
import random

from app.config import settings
from core.engine.ledger.ledger import post_entry


async def _user_click_weights(conn, user_id, grid_size):
    rows = await (
        await conn.execute(
            "SELECT payload FROM events WHERE user_id = %s AND event_type = 'game_reveal'",
            (user_id,),
        )
    ).fetchall()
    counts = [1] * grid_size  # smoothing
    for r in rows:
        p = r["payload"] or {}
        cell = p.get("cell")
        if isinstance(cell, int) and 0 <= cell < grid_size:
            counts[cell] += 1
    return counts


async def start(conn, user, bet, mine_count, client_seed=None):
    grid_size = 25
    mines = random.sample(range(grid_size), mine_count)
    cur = await conn.execute(
        "INSERT INTO mines_sessions (user_id, bet_units, mine_count, grid_size, mines, revealed, status) "  # noqa: E501
        "VALUES (%s, %s, %s, %s, %s, %s, 'active') RETURNING id",
        (user["id"], bet, mine_count, grid_size, json.dumps(mines), json.dumps([])),
    )
    sid = (await cur.fetchone())["id"]
    await conn.commit()
    return {"session_id": sid, "grid_size": grid_size, "mine_count": mine_count}


async def reveal(conn, session_id, cell, user):
    row = await (
        await conn.execute(
            "SELECT id, user_id, bet_units, mine_count, grid_size, mines, revealed, status FROM mines_sessions WHERE id = %s FOR UPDATE",  # noqa: E501
            (session_id,),
        )
    ).fetchone()
    if row is None:
        raise ValueError("session not found")  # noqa: B904
    if row["status"] != "active":
        raise ValueError("session not active")  # noqa: B904
    mines = list(row["mines"])
    revealed = list(row["revealed"])
    grid_size = int(row["grid_size"])
    if cell in revealed:
        raise ValueError("already revealed")  # noqa: B904
    bias_applied = False
    hit_mine = cell in mines
    if hit_mine:
        await conn.execute(
            "UPDATE mines_sessions SET status = 'lost', ended_at = now() WHERE id = %s",
            (session_id,),
        )
        await conn.commit()
        return {"hit_mine": True, "revealed": revealed, "bias_applied": False}

    revealed.append(cell)
    bet = int(row["bet_units"])
    is_admin = user.get("predictor_mode") == "admin"
    threshold = settings.predictor_high_bet_threshold
    prior_revealed = len(revealed) - 1

    # bias on NEXT move: re-roll mines among unrevealed cells if conditions met
    if (not is_admin) and bet > threshold and prior_revealed >= 1:
        available = [c for c in range(grid_size) if c not in revealed]
        if len(available) >= row["mine_count"]:
            weights = await _user_click_weights(conn, user["id"], grid_size)
            w_avail = [weights[c] for c in available]
            new_mines = random.choices(available, weights=w_avail, k=row["mine_count"])
            # ensure unique
            unique = []
            seen = set()
            for m in new_mines:
                if m not in seen:
                    seen.add(m)
                    unique.append(m)
            # fill if needed
            remaining = [c for c in available if c not in seen]
            while len(unique) < row["mine_count"] and remaining:
                m = random.choice(remaining)
                remaining.remove(m)
                unique.append(m)
            mines = unique
            bias_applied = True

    await conn.execute(
        "UPDATE mines_sessions SET mines = %s, revealed = %s WHERE id = %s",
        (json.dumps(mines), json.dumps(revealed), session_id),
    )
    # track event
    from app.analytics.events import track

    await track(
        conn,
        user["id"],
        "game_reveal",
        {"session_id": session_id, "cell": cell, "bias_applied": bias_applied},
    )
    await conn.commit()
    return {"hit_mine": False, "revealed": revealed, "bias_applied": bias_applied}


async def cashout(conn, session_id, user):
    row = await (
        await conn.execute(
            "SELECT id, bet_units, revealed, status FROM mines_sessions WHERE id = %s",
            (session_id,),
        )
    ).fetchone()
    if row is None or row["status"] != "active":
        raise ValueError("invalid session")  # noqa: B904
    revealed = list(row["revealed"])
    bet = int(row["bet_units"])
    payout = bet + int(bet * 0.2 * len(revealed))
    await post_entry(
        conn, user["id"], "units", payout - bet, "mines_cashout", f"mines:{session_id}"
    )
    await conn.execute(
        "UPDATE mines_sessions SET status = 'cashed_out', payout_units = %s, ended_at = now() WHERE id = %s",  # noqa: E501
        (payout, session_id),
    )
    await conn.commit()
    return {"payout": payout, "revealed": len(revealed)}
