import os
from datetime import UTC

import yaml

from core.engine.ledger.ledger import post_entry


def _tier_for_deposit(amount_minor: int) -> int:
    path = "configs/referrals.yaml"
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        for tier in data.get("tiers", []):
            if amount_minor <= tier.get("max_minor", 0):
                return int(tier.get("referrer_units", 0))
    return 50


async def create_referral_link(user_id: int) -> str:
    return f"https://t.me/robloxcasebot?start=ref_{user_id}"


async def handle_signup(
    conn, new_user_id: int, referrer_id: int, signup_ip=None, device_fingerprint=None
):
    # anti-fraud: self-referral by ip/device
    # simple: if same user id
    if new_user_id == referrer_id:
        return {"status": "rejected"}
    await conn.execute(
        "INSERT INTO referrals (referrer_id, referee_id, status) VALUES (%s, %s, 'held')",
        (referrer_id, new_user_id),
    )
    await conn.commit()
    # grant referee freebets
    amount = 25
    path = "configs/referrals.yaml"
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        amount = int(data.get("referee_welcome_freebet_units", amount))
    await post_entry(conn, new_user_id, "freebets", amount, "welcome_freebet", f"ref:{referrer_id}")
    await conn.commit()
    return {"status": "held"}


async def qualify(conn, referrer_id: int, referee_id: int, first_deposit_minor: int):
    # check hold 7 days
    row = await (
        await conn.execute(
            "SELECT id, status, created_at FROM referrals WHERE referrer_id = %s AND referee_id = %s",  # noqa: E501
            (referrer_id, referee_id),
        )
    ).fetchone()
    if row is None or row["status"] != "held":
        return {"status": "not_qualified"}
    # 7 day hold
    from datetime import datetime

    if (datetime.now(UTC) - row["created_at"]).total_seconds() < 7 * 86400:
        return {"status": "holding"}
    # antifraud flags
    flag = await (
        await conn.execute("SELECT 1 FROM referral_flags WHERE user_id = %s LIMIT 1", (referee_id,))
    ).fetchone()
    if flag:
        await conn.execute("UPDATE referrals SET status = 'rejected' WHERE id = %s", (row["id"],))
        await conn.commit()
        return {"status": "rejected"}
    # check deposit
    dep = await (
        await conn.execute(
            "SELECT 1 FROM events WHERE user_id = %s AND event_type = 'deposit' LIMIT 1",
            (referee_id,),
        )
    ).fetchone()
    if not dep:
        return {"status": "not_qualified"}
    units = _tier_for_deposit(first_deposit_minor)
    await post_entry(conn, referrer_id, "units", units, "referral_units", f"referral:{referee_id}")
    await conn.execute(
        "UPDATE referrals SET status = 'released', bonus_released_at = now() WHERE id = %s",
        (row["id"],),
    )
    await conn.commit()
    return {"status": "released", "units": units}
