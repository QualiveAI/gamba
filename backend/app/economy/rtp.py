from app.config import settings


async def has_active_subscription(conn, user_id: int) -> bool:
    row = await (
        await conn.execute(
            "SELECT 1 FROM user_subscriptions WHERE user_id = %s AND active = TRUE AND ends_at > now() LIMIT 1",  # noqa: E501
            (user_id,),
        )
    ).fetchone()
    return row is not None


async def resolve_rtp(conn, user, case) -> float:
    profile = (
        case.get("rtp_profile") if isinstance(case, dict) else getattr(case, "rtp_profile", None)
    )
    if profile is None:
        profile = {}
    segment = user.get("segment") if isinstance(user, dict) else getattr(user, "segment", "new")
    base = profile.get(segment, profile.get("standard", 0.8))
    if await has_active_subscription(conn, user["id"] if isinstance(user, dict) else user.id):
        base = float(base) + settings.predictor_sub_rtp_bonus
    return float(base)
