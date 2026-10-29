from psycopg.types.json import Json

from app.config import settings


async def check_subscription(conn, user_id: int) -> bool:
    row = await (
        await conn.execute(
            "SELECT 1 FROM user_subscriptions WHERE user_id = %s AND active = TRUE AND ends_at > now() LIMIT 1",  # noqa: E501
            (user_id,),
        )
    ).fetchone()
    return row is not None


async def purchase_subscription(conn, user_id: int, days: int = 30):
    await conn.execute(
        "INSERT INTO user_subscriptions (user_id, ends_at, active) VALUES (%s, now() + make_interval(days => %s), TRUE)",  # noqa: E501
        (user_id, days),
    )
    await conn.commit()
    return {"active": True, "days": days}


async def expire_old(conn):
    await conn.execute("UPDATE user_subscriptions SET active = FALSE WHERE ends_at <= now()")
    await conn.commit()


async def predict_mines(conn, user_id: int, session_id: int, bet: int):
    # load session
    row = await (
        await conn.execute(
            "SELECT id, user_id, mines, revealed, grid_size, status FROM mines_sessions WHERE id = %s",  # noqa: E501
            (session_id,),  # noqa: E501
        )
    ).fetchone()
    if row is None:
        raise ValueError("session not found")  # noqa: B904
    mines = set(row["mines"])
    revealed = set(row["revealed"])
    grid_size = int(row["grid_size"])
    safe_cells = [c for c in range(grid_size) if c not in mines and c not in revealed]

    user = await (
        await conn.execute("SELECT predictor_mode FROM users WHERE id = %s", (user_id,))
    ).fetchone()
    mode = "admin" if (user and user["predictor_mode"] == "admin") else "regular"
    is_sub = await check_subscription(conn, user_id)

    if mode == "admin":
        accuracy = 1.0
        suggested = safe_cells
        confidence = 1.0
    else:
        low = settings.predictor_low_bet_threshold
        high = settings.predictor_high_bet_threshold
        if bet <= low:
            accuracy = 0.80
        elif bet >= high:
            accuracy = 0.20
        else:
            accuracy = 0.80 - (0.60 * (bet - low) / (high - low))
        n_cells = max(1, round(5 * accuracy))
        suggested = safe_cells[:n_cells]
        confidence = accuracy
        if is_sub:
            # subscription bonus to RTP handled elsewhere; predictor accuracy unchanged
            pass

    mode_label = (
        "silent" if (mode == "regular" and bet >= settings.predictor_high_bet_threshold) else mode
    )  # noqa: E501
    await conn.execute(
        "INSERT INTO mines_predictions (session_id, user_id, suggested_cells, confidence, mode) VALUES (%s, %s, %s, %s, %s)",  # noqa: E501
        (session_id, user_id, Json(suggested), confidence, mode_label),
    )
    await conn.commit()
    from app.analytics.events import track

    await track(
        conn,
        user_id,
        "predictor_predict",
        {"session_id": session_id, "bet": bet, "mode": mode_label},
    )  # noqa: E501
    await conn.commit()
    return {"suggested_cells": suggested, "confidence": confidence, "mode": mode_label}
