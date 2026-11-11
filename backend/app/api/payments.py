from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.api.deps import get_current_user, require_admin
from app.db import get_conn
from app.payments import gifts, stars
from core.contracts.payment import PaymentError

router = APIRouter(prefix="/payments", tags=["payments"])


class StarsInvoiceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent_id: str = Field(pattern=r"^[0-9a-f]{32}$")


class GiftReceiptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    gift_id: str = Field(min_length=1, max_length=160)
    custody_reference: str = Field(min_length=1, max_length=256)


class GiftReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    receipt_event_id: StrictInt = Field(gt=0)
    valued_brl_minor: StrictInt = Field(gt=0)


def _payment_error(exc: PaymentError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}
    )


@router.post("/stars/invoice")
async def stars_invoice(body: StarsInvoiceRequest, user=Depends(get_current_user)):  # noqa: B008
    try:
        async with get_conn() as conn, conn.transaction():
            return await stars.create_invoice_for_intent(conn, user=user, intent_id=body.intent_id)
    except PaymentError as exc:
        raise _payment_error(exc) from exc


@router.post("/gifts/{intent_id}/receipt")
async def gift_receipt(intent_id: str, body: GiftReceiptRequest, owner=Depends(require_admin)):  # noqa: B008
    try:
        async with get_conn() as conn, conn.transaction():
            event_id = await gifts.record_manual_gift_receipt(
                conn,
                intent_id=intent_id,
                owner=owner,
                gift_id=body.gift_id,
                custody_reference=body.custody_reference,
            )
        return {"receipt_event_id": event_id, "status": "pending_review"}
    except PaymentError as exc:
        raise _payment_error(exc) from exc


@router.post("/gifts/{intent_id}/review")
async def gift_review(intent_id: str, body: GiftReviewRequest, owner=Depends(require_admin)):  # noqa: B008
    try:
        async with get_conn() as conn, conn.transaction():
            result = await gifts.review_gift(
                conn,
                intent_id=intent_id,
                receipt_event_id=body.receipt_event_id,
                valued_brl_minor=body.valued_brl_minor,
                owner=owner,
            )
        return asdict(result)
    except PaymentError as exc:
        raise _payment_error(exc) from exc


@router.post("/stars/{intent_id}/refund-request")
async def stars_refund_request(intent_id: str, owner=Depends(require_admin)):  # noqa: B008
    try:
        async with get_conn() as conn, conn.transaction():
            return await stars.request_stars_refund(conn, intent_id=intent_id, owner=owner)
    except PaymentError as exc:
        raise _payment_error(exc) from exc


# Обходные legacy потоки отключены. Старые payload amount_rub/receipt_url не
# превращаются в coins и не попадают в yoomoney_sbp с его собственным settlement.
@router.post("/yoomoney/create")
@router.post("/yoomoney/webhook")
@router.get("/{payment_id}/status")
@router.post("/{payment_id}/manual-claim")
async def legacy_payment_disabled(request: Request):
    raise HTTPException(
        status_code=410,
        detail={
            "code": "legacy_payment_disabled",
            "message": "Use o novo fluxo de depósitos com cotação.",
        },
    )
