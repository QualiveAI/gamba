from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.api.deps import get_current_user
from app.api.giftcards import SafeGiftcardRoute, safe_http_error
from app.db import get_conn
from app.giftcards.security import MAX_SAFE_INTEGER, GiftCardError, authenticated_user
from app.withdrawals import service

router = APIRouter(prefix="/withdrawals", tags=["withdrawals"], route_class=SafeGiftcardRoute)


class WithdrawalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku_id: StrictInt = Field(gt=0, le=MAX_SAFE_INTEGER)
    idempotency_key: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")


@router.post("")
async def create_withdrawal(body: WithdrawalRequest, user=Depends(get_current_user)):  # noqa: B008
    # Старые amount/region/quantity/fee отклоняются: автоматического mapping нет.
    async with get_conn() as conn:
        try:
            result = await service.request(
                conn, user, sku_id=body.sku_id, idempotency_key=body.idempotency_key
            )
        except GiftCardError as exc:
            raise safe_http_error(exc) from None
    return {**result, "redemption_id": result["id"], "status_url": f"/redemptions/{result['id']}"}


@router.get("/mine")
async def my_withdrawals(user=Depends(get_current_user)):  # noqa: B008
    try:
        user_id, _, _, _ = authenticated_user(user)
    except GiftCardError as exc:
        raise safe_http_error(exc) from None
    async with get_conn() as conn:
        rows = await (
            await conn.execute(
                "SELECT id, amount_units, region, status, created_at, decided_at "
                "FROM withdrawals WHERE user_id = %s ORDER BY id DESC LIMIT 100",
                (user_id,),
            )
        ).fetchall()
    return [{**dict(row), "legacy": True, "read_only": True} for row in rows]


@router.get("/{wid}/status")
async def withdrawal_status(wid: int, user=Depends(get_current_user)):  # noqa: B008
    try:
        user_id, _, _, _ = authenticated_user(user)
    except GiftCardError as exc:
        raise safe_http_error(exc) from None
    async with get_conn() as conn:
        row = await (
            await conn.execute(
                "SELECT id, status FROM withdrawals WHERE id = %s AND user_id = %s",
                (wid, user_id),
            )
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Заявка не найдена.")
    return {"withdrawal_id": row["id"], "status": row["status"], "legacy": True, "read_only": True}
