from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.db import get_conn
from app.predictor.service import predict_mines, purchase_subscription

router = APIRouter(prefix="/predictor", tags=["predictor"])


class PredictRequest(BaseModel):
    session_id: int
    bet: int


class SubscribeRequest(BaseModel):
    days: int = 30


@router.post("/predict")
async def predict(body: PredictRequest, user=Depends(get_current_user)):  # noqa: E501, B008  # noqa: B008  # noqa: B008
    async with get_conn() as conn:
        try:
            return await predict_mines(conn, user["id"], body.session_id, body.bet)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))  # noqa: B904


@router.post("/subscribe")
async def subscribe(body: SubscribeRequest, user=Depends(get_current_user)):  # noqa: E501, B008  # noqa: B008  # noqa: B008
    async with get_conn() as conn:
        return await purchase_subscription(conn, user["id"], body.days)


@router.get("/status")
async def status(user=Depends(get_current_user)):  # noqa: B008  # noqa: B008  # noqa: B008
    async with get_conn() as conn:
        from app.predictor.service import check_subscription

        active = await check_subscription(conn, user["id"])
    return {"active": active}
