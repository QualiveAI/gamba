from fastapi import APIRouter, Depends

from app.api.deps import require_admin
from app.db import get_conn
from core.ops.flags import get_flag, set_flag

router = APIRouter(prefix="/admin/ops", tags=["ops"])


@router.get("/status")
async def status(admin=Depends(require_admin)):  # noqa: B008  # noqa: B008  # noqa: B008
    async with get_conn() as conn:
        trading = await get_flag(conn, "trading_enabled", True)
        deposits = await get_flag(conn, "deposits_enabled", True)
        withdrawals = await get_flag(conn, "withdrawals_enabled", True)
        growth = await get_flag(conn, "growth_enabled", True)
    return {
        "trading_enabled": trading,
        "deposits_enabled": deposits,
        "withdrawals_enabled": withdrawals,
        "growth_enabled": growth,
    }


@router.post("/flags")
async def flags(payload: dict, admin=Depends(require_admin)):  # noqa: E501, B008  # noqa: B008  # noqa: B008
    key = payload.get("key")
    value = bool(payload.get("value", False))
    async with get_conn() as conn:
        await set_flag(conn, key, value, str(admin.get("id")))
    return {"ok": True}
