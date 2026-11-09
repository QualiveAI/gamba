from datetime import UTC

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.db import get_conn
from app.rewards.daily import claim_daily
from app.rewards.missions import get_today_progress, update_progress
from app.rewards.winfeed import get_feed

router = APIRouter(prefix="/rewards", tags=["rewards"])


@router.post("/daily/claim")
async def daily_claim(user=Depends(get_current_user)):  # noqa: B008  # noqa: B008  # noqa: B008
    async with get_conn() as conn:
        return await claim_daily(conn, user)


@router.get("/streak")
async def streak(user=Depends(get_current_user)):  # noqa: B008  # noqa: B008  # noqa: B008
    async with get_conn() as conn:
        row = await (
            await conn.execute(
                "SELECT current_streak, bonus_percent FROM deposit_streaks WHERE user_id = %s",
                (user["id"],),  # noqa: E501
            )
        ).fetchone()
    return dict(row) if row else {"current_streak": 0, "bonus_percent": 0}


@router.get("/missions/today")
async def missions_today(user=Depends(get_current_user)):  # noqa: B008  # noqa: B008  # noqa: B008
    async with get_conn() as conn:
        return await get_today_progress(conn, user["id"])


@router.post("/missions/progress")
async def missions_progress(step: str, user=Depends(get_current_user)):  # noqa: E501, B008  # noqa: B008  # noqa: B008
    async with get_conn() as conn:
        return await update_progress(conn, user["id"], step)


@router.get("/winfeed")
async def winfeed(limit: int = 50):
    async with get_conn() as conn:
        return await get_feed(conn, limit)


class ConvertRequest(BaseModel):
    amount_copper: int


@router.post("/convert_freebets")
async def convert_freebets(body: ConvertRequest, user=Depends(get_current_user)):  # noqa: B008
    """Медные монетки (фрибеты) -> золотые, курс 100:1."""
    from core.engine.ledger.ledger import post_entry

    amount = int(body.amount_copper)
    if amount <= 0 or amount % 100 != 0:
        raise HTTPException(  # noqa: B904
            status_code=400, detail="amount must be a multiple of 100"
        )
    gold = amount // 100
    async with get_conn() as conn:
        try:
            conv_ref = f"conv:{amount}:{user['id']}"
            await post_entry(conn, user["id"], "freebets", -amount, "convert_out", conv_ref)
            await post_entry(conn, user["id"], "units", gold, "convert_in", conv_ref)
            await conn.commit()
        except ValueError as e:
            await conn.rollback()
            raise HTTPException(status_code=400, detail=str(e))  # noqa: B904
    return {"converted_copper": amount, "gold": gold}


@router.get("/daily/status")
async def daily_status(user=Depends(get_current_user)):  # noqa: B008
    """Доступна ли ежедневная награда (500 медных) и streak."""
    from datetime import datetime

    async with get_conn() as conn:
        rows = await (
            await conn.execute(
                "SELECT claimed_at FROM daily_rewards WHERE user_id = %s "
                "ORDER BY claimed_at DESC LIMIT 7",
                (user["id"],),
            )
        ).fetchall()
    can_claim = True
    if rows:
        elapsed = (datetime.now(UTC) - rows[0]["claimed_at"]).total_seconds()
        can_claim = elapsed >= 86400
    return {"can_claim": can_claim, "reward": 500, "streak": len(rows)}
