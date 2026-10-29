import os
from datetime import UTC, date

import yaml


def _rewards_config():
    path = "configs/rewards.yaml"
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


async def record_deposit(conn, user_id: int, amount_minor: int):
    today = date.today()
    row = await (
        await conn.execute(
            "SELECT current_streak, last_deposit_date FROM deposit_streaks WHERE user_id = %s",
            (user_id,),
        )
    ).fetchone()
    if row is None:
        await conn.execute(
            "INSERT INTO deposit_streaks (user_id, current_streak, last_deposit_date) VALUES (%s, %s, %s)",  # noqa: E501
            (user_id, 1, today),
        )
    else:
        last = row["last_deposit_date"]
        streak = int(row["current_streak"])
        if last is not None and (today - last).days == 1:
            streak += 1
        elif last == today:
            pass
        else:
            streak = 1
        await conn.execute(
            "UPDATE deposit_streaks SET current_streak = %s, last_deposit_date = %s WHERE user_id = %s",  # noqa: E501
            (streak, today, user_id),
        )
    await conn.commit()


async def check_streak_bonus(conn, user_id: int):
    cfg = _rewards_config().get("deposit_streak", {})
    days_required = int(cfg.get("days_required", 3))
    bonus = int(cfg.get("bonus_freebet_units", 10))
    reset_hours = int(cfg.get("reset_after_hours", 48))
    row = await (
        await conn.execute(
            "SELECT current_streak, last_deposit_date FROM deposit_streaks WHERE user_id = %s",
            (user_id,),
        )
    ).fetchone()
    if row is None:
        return {"granted": False}
    streak = int(row["current_streak"])
    last = row["last_deposit_date"]
    # reset if gap
    if last is not None:
        from datetime import datetime

        # convert date to datetime
        last_dt = datetime.combine(last, datetime.min.time()).replace(tzinfo=UTC)
        if (datetime.now(UTC) - last_dt).total_seconds() > reset_hours * 3600:
            await conn.execute(
                "UPDATE deposit_streaks SET current_streak = 0 WHERE user_id = %s", (user_id,)
            )
            await conn.commit()
            return {"granted": False}
    if streak >= days_required:
        # idempotent: check ledger for deposit_streak_freebet ref_id window
        ref_id = f"streak:{user_id}:{last}"
        row2 = await (
            await conn.execute(
                "SELECT id FROM ledger_entries WHERE user_id = %s AND currency = 'freebets' AND reason = 'deposit_streak_freebet' AND ref_id = %s",  # noqa: E501
                (user_id, ref_id),
            )
        ).fetchone()
        if row2:
            return {"granted": False}
        from core.engine.ledger.ledger import post_entry

        await post_entry(conn, user_id, "freebets", bonus, "deposit_streak_freebet", ref_id)
        await conn.execute(
            "UPDATE deposit_streaks SET current_streak = 0 WHERE user_id = %s", (user_id,)
        )
        await conn.commit()
        return {"granted": True, "amount": bonus}
    return {"granted": False}
