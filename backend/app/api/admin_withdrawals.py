from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict

from app.api.giftcards import SafeGiftcardRoute, giftcard_admin, safe_http_error
from app.db import get_conn
from app.giftcards.security import GiftCardError
from app.withdrawals import service

router = APIRouter(tags=["admin_withdrawals"], route_class=SafeGiftcardRoute)


class RejectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Literal["operator_rejected", "requested_by_owner", "risk_review"] = "operator_rejected"


@router.get("/admin/redemptions")
async def list_redemptions(
    status: str | None = Query(default=None),
    admin=Depends(giftcard_admin),  # noqa: B008
):
    async with get_conn() as conn:
        try:
            return await service.admin_redemptions(conn, status=status)
        except GiftCardError as exc:
            raise safe_http_error(exc) from None


@router.post("/admin/redemptions/{redemption_id}/reject")
async def reject_redemption(
    redemption_id: int,
    body: RejectionRequest,
    admin=Depends(giftcard_admin),  # noqa: B008
):
    async with get_conn() as conn:
        try:
            return await service.reject_redemption(
                conn, redemption_id=redemption_id, reason=body.reason
            )
        except GiftCardError as exc:
            # Нельзя прятать exception до commit: delivering должен остаться manual_review.
            error = safe_http_error(exc)
    raise error


@router.get("/admin/withdrawals")
async def list_withdrawals(
    status: str | None = Query(default=None),
    admin=Depends(giftcard_admin),  # noqa: B008
):
    query = (
        "SELECT id, user_id, amount_units, region, status, created_at, decided_at FROM withdrawals"
    )
    parameters = ()
    if status:
        query += " WHERE status = %s"
        parameters = (status,)
    async with get_conn() as conn:
        rows = await (
            await conn.execute(query + " ORDER BY id DESC LIMIT 200", parameters)
        ).fetchall()
    return [{**dict(row), "legacy": True, "read_only": True} for row in rows]


@router.post("/admin/withdrawals/{withdrawal_id}/approve")
async def approve(withdrawal_id: int, admin=Depends(giftcard_admin)):  # noqa: B008
    raise safe_http_error(GiftCardError("legacy_read_only", 409))


@router.post("/admin/withdrawals/{withdrawal_id}/reject")
async def reject(withdrawal_id: int, admin=Depends(giftcard_admin)):  # noqa: B008
    raise safe_http_error(GiftCardError("legacy_read_only", 409))


@router.post("/admin/withdrawals/{withdrawal_id}/unfreeze")
async def unfreeze(withdrawal_id: int, admin=Depends(giftcard_admin)):  # noqa: B008
    raise safe_http_error(GiftCardError("legacy_read_only", 409))


@router.post("/admin/withdrawals/{withdrawal_id}/finalize")
async def finalize(withdrawal_id: int, admin=Depends(giftcard_admin)):  # noqa: B008
    async with get_conn() as conn:
        try:
            result = await service.finalize(conn, withdrawal_id)
        except GiftCardError as exc:
            raise safe_http_error(exc) from None
    return {"id": withdrawal_id, **result}
