import os

import yaml

from core.engine.ledger.ledger import post_entry


def _welcome_amount():
    path = "configs/rewards.yaml"
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return int(data.get("welcome_freebet_units", 50))
    return 50


async def grant_welcome(conn, user):
    user_id = user["id"] if isinstance(user, dict) else user.id
    # idempotent
    row = await (
        await conn.execute(
            "SELECT id FROM ledger_entries WHERE user_id = %s AND currency = 'freebets' AND reason = 'welcome_freebet' AND ref_id = %s",  # noqa: E501
            (user_id, str(user_id)),
        )
    ).fetchone()
    if row:
        return {"granted": False}
    amount = _welcome_amount()
    await post_entry(conn, user_id, "freebets", amount, "welcome_freebet", str(user_id))
    await conn.commit()
    return {"granted": True, "amount": amount}
