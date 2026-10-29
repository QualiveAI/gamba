from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.db import get_conn
from app.withdrawals import service

router = APIRouter(prefix="/withdrawals", tags=["withdrawals"])


class WithdrawalRequest(BaseModel):
    amount: int
    region: str


@router.post("")
async def create_withdrawal(body: WithdrawalRequest, user=Depends(get_current_user)):  # noqa: E501, B008  # noqa: B008  # noqa: B008
    async with get_conn() as conn:
        try:
            wid = await service.request(conn, user, body.amount, body.region)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))  # noqa: B904
    return {"id": wid, "status": "pending"}


@router.get("/mine")
async def my_withdrawals(user=Depends(get_current_user)):  # noqa: B008  # noqa: B008  # noqa: B008
    async with get_conn() as conn:
        rows = await (
            await conn.execute(
                "SELECT id, amount_units, region, status, created_at, decided_at, reason FROM withdrawals WHERE user_id = %s ORDER BY id DESC",  # noqa: E501
                (user["id"],),
            )
        ).fetchall()
    return [dict(r) for r in rows]
