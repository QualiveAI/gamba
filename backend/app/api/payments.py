from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.db import get_conn
from app.payments import stars, yoomoney_sbp

router = APIRouter(prefix="/payments", tags=["payments"])


class StarsInvoiceRequest(BaseModel):
    title: str
    description: str
    payload: str
    amount_stars: int


class YooMoneyCreateRequest(BaseModel):
    amount_rub: float


class ManualClaimRequest(BaseModel):
    receipt_url: str


@router.post("/stars/invoice")
async def stars_invoice(body: StarsInvoiceRequest, user=Depends(get_current_user)):  # noqa: E501, B008  # noqa: B008  # noqa: B008
    url = await stars.create_invoice_link(
        body.title, body.description, body.payload, body.amount_stars
    )
    return {"invoice_link": url}


@router.post("/yoomoney/create")
async def yoomoney_create(body: YooMoneyCreateRequest, user=Depends(get_current_user)):  # noqa: E501, B008  # noqa: B008  # noqa: B008
    async with get_conn() as conn:
        return await yoomoney_sbp.create_payment(conn, user["id"], body.amount_rub)


@router.get("/{payment_id}/status")
async def payment_status(payment_id: int, user=Depends(get_current_user)):  # noqa: E501, B008  # noqa: B008  # noqa: B008
    async with get_conn() as conn:
        row = await (
            await conn.execute(
                "SELECT id, status, amount_units, metadata FROM payment_polling WHERE id = %s",
                (payment_id,),
            )
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="not found")  # noqa: B904
    return dict(row)


@router.post("/yoomoney/webhook")
async def yoomoney_webhook(request: Request):
    body = await request.body()
    sig = request.headers.get("X-YooMoney-Signature", "")
    if not yoomoney_sbp.verify_webhook(body, sig):
        raise HTTPException(status_code=400, detail="bad signature")  # noqa: B904
    payload = await request.json()
    async with get_conn() as conn:
        return await yoomoney_sbp.handle_webhook(conn, payload)


@router.post("/{payment_id}/manual-claim")
async def manual_claim(payment_id: int, body: ManualClaimRequest, user=Depends(get_current_user)):  # noqa: E501, B008  # noqa: B008  # noqa: B008
    async with get_conn() as conn:
        return await yoomoney_sbp.manual_claim(conn, payment_id, body.receipt_url)
