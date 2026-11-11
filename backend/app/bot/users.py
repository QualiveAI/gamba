"""Единый upsert Telegram-пользователей и идемпотентный Welcome без скрытых commit."""

import re

from app.bot.security import BotSecurityError, positive_id
from app.referrals.service import handle_referral
from core.engine.ledger.ledger import post_entry
from core.rewards.welcome import _welcome_amount

_CAMPAIGNS = frozenset({"organic", "telegram", "social", "creator", "launch-br"})


async def ensure_telegram_user(conn, *, telegram_id: int, username: str = "") -> dict:
    if not positive_id(telegram_id) or not isinstance(username, str):
        raise BotSecurityError("telegram_user_invalid")
    user = await (
        await conn.execute(
            "INSERT INTO users (telegram_id, username, is_guest) VALUES (%s, %s, FALSE) "
            "ON CONFLICT (telegram_id) DO UPDATE SET username = EXCLUDED.username "
            "WHERE users.is_guest = FALSE RETURNING *",
            (telegram_id, username[:64]),
        )
    ).fetchone()
    if not user:
        raise BotSecurityError("guest_identity_collision")
    # ON CONFLICT UPDATE держит users row lock до конца внешней транзакции.
    # Существующий grant_welcome сам делает commit, поэтому здесь только его ledger primitive.
    granted = await (
        await conn.execute(
            "SELECT id FROM ledger_entries WHERE user_id = %s AND currency = 'freebets' "
            "AND reason = 'welcome_freebet' AND ref_id = %s",
            (user["id"], str(user["id"])),
        )
    ).fetchone()
    if not granted:
        await post_entry(
            conn, user["id"], "freebets", _welcome_amount(), "welcome_freebet", str(user["id"])
        )
    return dict(user)


async def ensure_guest_user(conn) -> dict:
    # NULL Telegram identity не может совпасть с реальным игроком/администратором.
    await conn.execute("SELECT pg_advisory_xact_lock(782591320)")
    user = await (
        await conn.execute(
            "SELECT * FROM users WHERE is_guest = TRUE AND telegram_id IS NULL "
            "ORDER BY id LIMIT 1 FOR UPDATE"
        )
    ).fetchone()
    if not user:
        user = await (
            await conn.execute(
                "INSERT INTO users (username, is_guest) VALUES ('convidado', TRUE) RETURNING *"
            )
        ).fetchone()
    return dict(user)


async def apply_start_attribution(conn, *, user: dict, source_bot_id: int, payload: str):
    # Реферальный ID — внутренний users.id, никогда не Telegram ID.
    match = re.fullmatch(r"ref_([1-9][0-9]{0,18})", payload)
    if match:
        referrer_id = int(match.group(1))
        if positive_id(referrer_id):
            await handle_referral(conn, user["id"], referrer_id, commit=False)
        return
    if not payload.startswith("lp_") or len(payload) > 32 or not payload.isascii():
        return
    campaign = payload[3:]
    if campaign not in _CAMPAIGNS or not re.fullmatch(
        r"[a-z0-9](?:[a-z0-9-]{0,27}[a-z0-9])?", campaign
    ):
        return
    await conn.execute(
        "INSERT INTO bot_user_attribution (user_id, campaign, source_bot_id) VALUES (%s, %s, %s) "
        "ON CONFLICT (user_id) DO NOTHING",
        (user["id"], campaign, source_bot_id),
    )
