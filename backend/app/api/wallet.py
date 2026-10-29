from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.db import get_conn

router = APIRouter(tags=["wallet"])


@router.get("/wallet")
async def wallet(user=Depends(get_current_user)):  # noqa: B008  # noqa: B008  # noqa: B008
    async with get_conn() as conn:
        row = await (
            await conn.execute(
                "SELECT balance_units, balance_freebets FROM users WHERE id = %s", (user["id"],)
            )
        ).fetchone()
    return {"units_minor": row["balance_units"], "freebets_units": row["balance_freebets"]}


@router.get("/meta/limits")
async def limits():
    return {
        "min_deposit_minor": 10000,
        "withdraw_min_minor": 100000,
        "withdraw_fee_pct": 20,
        "hold_days": 1,
    }
