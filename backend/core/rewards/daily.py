import os
from datetime import UTC, datetime

import yaml

from core.engine.ledger.ledger import post_entry


def _daily_amount(segment):
    path = "configs/rewards.yaml"
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        amounts = data.get("daily_freebet_units", {})
        return int(amounts.get(segment, amounts.get("new", 5)))
    return 5


async def claim_daily(conn, user):
    user_id = user["id"] if isinstance(user, dict) else user.id
    segment = user.get("segment") if isinstance(user, dict) else getattr(user, "segment", "new")
    amount = _daily_amount(segment)
    row = await (
        await conn.execute(
            "SELECT claimed_at FROM daily_rewards WHERE user_id = %s ORDER BY claimed_at DESC LIMIT 1",  # noqa: E501
            (user_id,),
        )
    ).fetchone()
    if row and (datetime.now(UTC) - row["claimed_at"]).total_seconds() < 86400:
        raise ValueError("cooldown")  # noqa: B904
    await conn.execute(
        "INSERT INTO daily_rewards (user_id, amount_units) VALUES (%s, %s)", (user_id, amount)
    )
    await post_entry(
        conn,
        user_id,
        "freebets",
        amount,
        "daily_freebet",
        str(user_id) + str(datetime.now(UTC).date()),
    )
    await conn.execute("UPDATE users SET last_claim_at = now() WHERE id = %s", (user_id,))
    await conn.commit()
    return {"currency": "freebets", "amount": amount}
