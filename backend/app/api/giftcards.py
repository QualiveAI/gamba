from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from app.api.deps import get_current_user, require_admin
from app.db import get_conn
from app.giftcards import service
from app.giftcards.security import (
    MAX_IMPORT_BYTES,
    MAX_SAFE_INTEGER,
    GiftCardError,
    authenticated_user,
)
from app.withdrawals import service as redemption_service


class SafeGiftcardRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def safe_handler(request: Request):
            try:
                return await original(request)
            except RequestValidationError:
                # Стандартный 422 отражает input; там может оказаться ошибочно вставленный code.
                return JSONResponse(
                    status_code=422,
                    content={
                        "detail": {"code": "invalid_request", "message": "Некорректный запрос."}
                    },
                )

        return safe_handler


router = APIRouter(tags=["giftcards"], route_class=SafeGiftcardRoute)


class RedemptionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku_id: StrictInt = Field(gt=0, le=MAX_SAFE_INTEGER)
    idempotency_key: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")


class SkuRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operator_sku: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9._:-]+$")
    brand: Literal["Roblox"]
    region: Literal["BR"]
    card_currency: Literal["BRL"]
    face_value_minor: StrictInt = Field(gt=0, le=MAX_SAFE_INTEGER)
    coin_cost: StrictInt = Field(gt=0, le=MAX_SAFE_INTEGER)
    sandbox: StrictBool


class SkuStateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active: StrictBool


def safe_http_error(exc: GiftCardError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)}
    )


async def giftcard_admin(admin=Depends(require_admin)):  # noqa: B008
    if admin.get("auth_scope") != "primary" or admin.get("is_guest") is not False:
        raise HTTPException(status_code=403, detail="Нужен администратор основного бота.")
    return admin


@router.get("/giftcards/catalog")
async def giftcard_catalog():
    async with get_conn() as conn:
        return await service.catalog(conn)


@router.post("/redemptions")
async def redeem_card(body: RedemptionRequest, user=Depends(get_current_user)):  # noqa: B008
    async with get_conn() as conn:
        try:
            return await redemption_service.redeem(
                conn, user, sku_id=body.sku_id, idempotency_key=body.idempotency_key
            )
        except GiftCardError as exc:
            raise safe_http_error(exc) from None


@router.get("/redemptions")
async def my_redemptions(user=Depends(get_current_user)):  # noqa: B008
    try:
        user_id, _, _, _ = authenticated_user(user)
        async with get_conn() as conn:
            return await service.list_owned_cards(conn, user_id=user_id)
    except GiftCardError as exc:
        raise safe_http_error(exc) from None


@router.get("/redemptions/{redemption_id}")
async def redemption_status(redemption_id: int, user=Depends(get_current_user)):  # noqa: B008
    try:
        user_id, _, _, _ = authenticated_user(user)
        async with get_conn() as conn:
            return await service.get_redemption(conn, redemption_id=redemption_id, user_id=user_id)
    except GiftCardError as exc:
        raise safe_http_error(exc) from None


@router.get("/admin/giftcards/skus")
async def list_skus(admin=Depends(giftcard_admin)):  # noqa: B008
    async with get_conn() as conn:
        return await service.list_skus(conn)


@router.post("/admin/giftcards/skus", status_code=201)
async def create_sku(body: SkuRequest, admin=Depends(giftcard_admin)):  # noqa: B008
    async with get_conn() as conn:
        try:
            return await service.create_sku(conn, **body.model_dump(), created_by=admin["id"])
        except GiftCardError as exc:
            raise safe_http_error(exc) from None


@router.patch("/admin/giftcards/skus/{sku_id}")
async def set_sku_active(sku_id: int, body: SkuStateRequest, admin=Depends(giftcard_admin)):  # noqa: B008
    async with get_conn() as conn:
        try:
            return await service.set_sku_active(conn, sku_id=sku_id, active=body.active)
        except GiftCardError as exc:
            raise safe_http_error(exc) from None


@router.post("/admin/giftcards/import")
async def import_giftcards(
    request: Request,
    sku_id: int = Query(gt=0, le=MAX_SAFE_INTEGER),
    supplier_name: str = Query(min_length=1, max_length=120),
    batch_reference: str = Query(min_length=1, max_length=160),
    provenance_reference: str = Query(min_length=1, max_length=240),
    distribution_agreement_reference: str | None = Query(
        default=None, min_length=1, max_length=240
    ),
    admin=Depends(giftcard_admin),  # noqa: B008
):
    # Не UploadFile: multipart spool способен записать незашифрованный код во временный файл.
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type not in ("text/csv", "application/octet-stream"):
        raise HTTPException(status_code=415, detail="Передайте CSV как тело запроса, не multipart.")
    length = request.headers.get("content-length")
    if length is not None:
        try:
            if int(length) < 0 or int(length) > MAX_IMPORT_BYTES:
                raise GiftCardError("import_too_large", 413)
        except ValueError:
            raise HTTPException(
                status_code=413, detail="Некорректный или слишком большой CSV."
            ) from None
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > MAX_IMPORT_BYTES:
            raise safe_http_error(GiftCardError("import_too_large", 413))
        content.extend(chunk)
    async with get_conn() as conn:
        try:
            return await service.import_csv(
                conn,
                bytes(content),
                sku_id=sku_id,
                supplier_name=supplier_name,
                batch_reference=batch_reference,
                provenance_reference=provenance_reference,
                distribution_agreement_reference=distribution_agreement_reference,
                imported_by=admin["id"],
            )
        except GiftCardError as exc:
            raise safe_http_error(exc) from None
        finally:
            content.clear()


@router.get("/admin/giftcards/stats")
async def giftcard_stats(admin=Depends(giftcard_admin)):  # noqa: B008
    async with get_conn() as conn:
        return await service.inventory_stats(conn)
