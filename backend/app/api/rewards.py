from fastapi import APIRouter, Depends

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
