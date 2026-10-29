from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.db import get_conn
from app.economy.cases import open_case

router = APIRouter(prefix="/cases", tags=["cases"])


class OpenCaseRequest(BaseModel):
    client_seed: str = "default"


@router.get("")
async def list_cases(user=Depends(get_current_user)):  # noqa: B008  # noqa: B008  # noqa: B008
    async with get_conn() as conn:
        cases = await (
            await conn.execute(
                "SELECT id, name, price_units, rtp_profile FROM cases WHERE active = TRUE"
            )
        ).fetchall()
        out = []
        for c in cases:
            rewards = await (
                await conn.execute(
                    "SELECT id, reward_type, game_key, nominal_units, weight, region FROM case_rewards WHERE case_id = %s",  # noqa: E501
                    (c["id"],),
                )
            ).fetchall()
            out.append(
                {
                    "id": c["id"],
                    "name": c["name"],
                    "price_units": c["price_units"],
                    "rtp_profile": c["rtp_profile"],
                    "rewards": [dict(r) for r in rewards],
                }
            )
        return out


@router.post("/{case_id}/open")
async def open_case_endpoint(case_id: int, body: OpenCaseRequest, user=Depends(get_current_user)):  # noqa: E501, B008  # noqa: B008  # noqa: B008
    async with get_conn() as conn:
        try:
            result = await open_case(conn, user, case_id, body.client_seed)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))  # noqa: B904
        await _track(
            conn, user["id"], "case_open", {"case_id": case_id, "reward": result["nominal_units"]}
        )
        await conn.commit()
    return result


async def _track(conn, user_id, event_type, payload):
    from app.analytics.events import track

    await track(conn, user_id, event_type, payload)
