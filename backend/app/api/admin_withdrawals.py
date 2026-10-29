from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import require_admin
from app.db import get_conn
from app.withdrawals import service

router = APIRouter(prefix="/admin/withdrawals", tags=["admin_withdrawals"])


@router.get("")
async def list_withdrawals(status: str | None = Query(default=None), admin=Depends(require_admin)):  # noqa: E501, B008  # noqa: B008  # noqa: B008
    async with get_conn() as conn:
        if status:
            rows = await (
                await conn.execute(
                    "SELECT id, user_id, amount_units, region, status, code_id, created_at FROM withdrawals WHERE status = %s ORDER BY id DESC",  # noqa: E501
                    (status,),
                )
            ).fetchall()
        else:
            rows = await (
                await conn.execute(
                    "SELECT id, user_id, amount_units, region, status, code_id, created_at FROM withdrawals ORDER BY id DESC"  # noqa: E501
                )
            ).fetchall()
    return [dict(r) for r in rows]


@router.post("/{withdrawal_id}/approve")
async def approve(withdrawal_id: int, admin=Depends(require_admin)):  # noqa: E501, B008  # noqa: B008  # noqa: B008
    async with get_conn() as conn:
        try:
            code = await service.approve(conn, withdrawal_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))  # noqa: B904
    return {"id": withdrawal_id, "status": "approved", "code": code}


@router.post("/{withdrawal_id}/reject")
async def reject(withdrawal_id: int, reason: str = "rejected", admin=Depends(require_admin)):  # noqa: E501, B008  # noqa: B008  # noqa: B008
    async with get_conn() as conn:
        try:
            await service.reject(conn, withdrawal_id, reason)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))  # noqa: B904
    return {"id": withdrawal_id, "status": "rejected"}


@router.post("/{withdrawal_id}/unfreeze")
async def unfreeze(withdrawal_id: int, admin=Depends(require_admin)):  # noqa: E501, B008  # noqa: B008  # noqa: B008
    async with get_conn() as conn:
        await service.unfreeze(conn, withdrawal_id)
    return {"id": withdrawal_id, "status": "pending"}
