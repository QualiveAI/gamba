import os

import redis.asyncio as redis

from .config import allowed_modifiers
from .modifiers import f_admin, f_bet, f_chase, f_win

MODIFIER_FUNCS = {
    "f_win": f_win,
    "f_bet": f_bet,
    "f_chase": f_chase,
    "f_admin": f_admin,
}


class RtpDecision:
    def __init__(
        self,
        rtp_effective: float,
        modifiers_applied: list[str],
        reason: str,
        override: bool = False,
    ):
        self.rtp_effective = rtp_effective
        self.modifiers_applied = modifiers_applied
        self.reason = reason
        self.override = override


async def _redis():
    url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    return redis.from_url(url)


async def effective_rtp(base_rtp=None, game_key: str = '', user=None, session_ctx: dict = None, base: float = None):
    if base is not None:
        base_rtp = base
    if base_rtp is None:
        base_rtp = 0.9
    base = float(base_rtp)
    allowed = allowed_modifiers(game_key)
    modifiers_applied = []
    value = base
    # session context defaults
    streak = session_ctx.get("streak", 0)
    losses_5m = session_ctx.get("losses_5m", 0)
    stakes_since_loss = session_ctx.get("stakes_since_loss", 0)
    avg_stake = session_ctx.get("avg_stake", 0.0)
    p50 = session_ctx.get("p50", 0.0)
    p90 = session_ctx.get("p90", 0.0)
    bet = session_ctx.get("bet", 0.0)
    is_admin = session_ctx.get("is_admin", False)
    promo_override = session_ctx.get("promo_override", False)

    user_id = user.get("id") if isinstance(user, dict) else getattr(user, "id", None)

    # f_admin
    if "f_admin" in allowed:
        if is_admin and promo_override:
            # forced win
            return RtpDecision(1.0, ["f_admin"], "admin_promo_override", override=True)
        val = f_admin(is_admin, promo_override)
        value *= val
        if val != 1.0:
            modifiers_applied.append("f_admin")

    # f_win
    if "f_win" in allowed:
        val = f_win(streak)
        value *= val
        if val != 1.0:
            modifiers_applied.append("f_win")

    # f_bet
    if "f_bet" in allowed:
        val = f_bet(bet, p50, p90)
        value *= val
        if val != 1.0:
            modifiers_applied.append("f_bet")

    # f_chase with guard
    if "f_chase" in allowed and losses_5m >= 3:
        r = await _redis()
        key = f"rtp:chase:{user_id}"
        count = await r.incr(key)
        if count == 1:
            await r.expire(key, 3600)
        # allow at most once per 10 openings: if count % 10 == 1
        if count % 10 == 1:
            val = f_chase(losses_5m, stakes_since_loss, avg_stake)
            value *= val
            if val != 1.0:
                modifiers_applied.append("f_chase")
        await r.aclose()

    # clamp
    value = max(0.80, min(0.95, value))
    reason = "ok"
    return RtpDecision(value, modifiers_applied, reason)
