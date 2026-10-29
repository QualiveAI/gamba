from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class RiskScore:
    level: str = "low"
    reasons: list[str] = field(default_factory=list)


async def velocity(conn, user_id: int, window_minutes: int = 60) -> RiskScore:
    row = await (
        await conn.execute(
            "SELECT COUNT(*) AS c FROM withdrawals WHERE user_id = %s AND created_at > now() - make_interval(mins => %s)",  # noqa: E501
            (user_id, window_minutes),
        )
    ).fetchone()
    count = int(row["c"]) if row else 0
    if count >= 5:
        return RiskScore("high", [f"velocity:{count}"])
    if count >= 3:
        return RiskScore("medium", [f"velocity:{count}"])
    return RiskScore("low", [])


def new_account_cooldown(user) -> RiskScore:
    created = (
        user.get("created_at") if isinstance(user, dict) else getattr(user, "created_at", None)
    )  # noqa: E501
    if created is None:
        return RiskScore("low", [])
    if isinstance(created, str):
        created = datetime.fromisoformat(created.replace("Z", "+00:00"))
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    age_hours = (datetime.now(UTC) - created).total_seconds() / 3600.0
    if age_hours < 24:
        return RiskScore("medium", ["new_account_cooldown"])
    return RiskScore("low", [])


def region_mismatch(user, code_region) -> RiskScore:
    user_region = user.get("region") if isinstance(user, dict) else getattr(user, "region", None)
    if user_region and code_region and user_region != code_region:
        return RiskScore("medium", [f"region_mismatch:{user_region}!={code_region}"])
    return RiskScore("low", [])


async def activation_fail_rate(conn, user_id: int) -> RiskScore:
    row = await (
        await conn.execute(
            "SELECT COUNT(*) FILTER (WHERE status = 'rejected') AS rej, COUNT(*) AS tot FROM withdrawals WHERE user_id = %s",  # noqa: E501
            (user_id,),
        )
    ).fetchone()
    rej = int(row["rej"]) if row else 0
    tot = int(row["tot"]) if row else 0
    if tot >= 5 and (rej / tot) > 0.5:
        return RiskScore("high", [f"activation_fail_rate:{rej}/{tot}"])
    return RiskScore("low", [])


async def evaluate(conn, user, code_region=None) -> RiskScore:
    reasons = []
    level = "low"
    v = await velocity(conn, user["id"] if isinstance(user, dict) else user.id, 60)
    reasons += v.reasons
    if v.level == "high":
        level = "high"
    elif v.level == "medium":
        level = "medium"
    c = new_account_cooldown(user)
    reasons += c.reasons
    if c.level == "high":
        level = "high"
    elif c.level == "medium" and level != "high":
        level = "medium"
    r = region_mismatch(user, code_region)
    reasons += r.reasons
    if r.level == "high":
        level = "high"
    elif r.level == "medium" and level != "high":
        level = "medium"
    a = await activation_fail_rate(conn, user["id"] if isinstance(user, dict) else user.id)
    reasons += a.reasons
    if a.level == "high":
        level = "high"
    elif a.level == "medium" and level != "high":
        level = "medium"
    if not reasons:
        level = "low"
    return RiskScore(level, reasons)
