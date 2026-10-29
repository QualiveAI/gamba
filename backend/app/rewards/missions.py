from datetime import date

from psycopg.types.json import Json

MISSION_CODE = "daily_chain"


async def get_or_create_mission(conn):
    row = await (
        await conn.execute("SELECT id FROM missions WHERE code = %s", (MISSION_CODE,))
    ).fetchone()  # noqa: E501
    if row:
        return row["id"]
    cur = await conn.execute(
        "INSERT INTO missions (code, title, steps) VALUES (%s, %s, %s) RETURNING id",
        (
            MISSION_CODE,
            "Daily chain",
            Json([{"step": "open_case"}, {"step": "mines_reveal"}, {"step": "claim_daily"}]),
        ),  # noqa: E501
    )
    return (await cur.fetchone())["id"]


async def get_today_progress(conn, user_id: int):
    mid = await get_or_create_mission(conn)
    today = date.today()
    row = await (
        await conn.execute(
            "SELECT id, progress, completed, reward_claimed FROM mission_progress WHERE user_id = %s AND mission_id = %s AND day = %s",  # noqa: E501
            (user_id, mid, today),
        )
    ).fetchone()
    if row is None:
        cur = await conn.execute(
            "INSERT INTO mission_progress (user_id, mission_id, progress, day) VALUES (%s, %s, %s, %s) RETURNING id, progress, completed, reward_claimed",  # noqa: E501
            (user_id, mid, Json({}), today),
        )
        row = await cur.fetchone()
        await conn.commit()
    return {
        "mission_id": mid,
        "progress": row["progress"],
        "completed": row["completed"],
        "reward_claimed": row["reward_claimed"],
    }  # noqa: E501


async def update_progress(conn, user_id: int, step: str):
    mp = await get_today_progress(conn, user_id)
    progress = dict(mp["progress"] or {})
    progress[step] = True
    mid = mp["mission_id"]
    completed = (
        progress.get("open_case") and progress.get("mines_reveal") and progress.get("claim_daily")
    )  # noqa: E501
    await conn.execute(
        "UPDATE mission_progress SET progress = %s, completed = %s WHERE user_id = %s AND mission_id = %s AND day = %s",  # noqa: E501
        (Json(progress), bool(completed), user_id, mid, date.today()),
    )
    await conn.commit()
    if completed and not mp["reward_claimed"]:
        await conn.execute(
            "UPDATE users SET balance_units = balance_units + 10 WHERE id = %s", (user_id,)
        )
        await conn.execute(
            "UPDATE mission_progress SET reward_claimed = TRUE WHERE user_id = %s AND mission_id = %s AND day = %s",  # noqa: E501
            (user_id, mid, date.today()),
        )
        await conn.commit()
        from app.analytics.events import track

        await track(conn, user_id, "mission_complete", {"mission": MISSION_CODE})
        await conn.commit()
    return await get_today_progress(conn, user_id)
