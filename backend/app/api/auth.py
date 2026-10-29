import secrets

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.auth.jwt import issue_token
from app.auth.roblox_oauth import build_auth_url, exchange_code, generate_pkce, get_user_info
from app.auth.telegram import AuthError, validate_init_data
from app.config import settings
from app.db import get_conn

router = APIRouter(prefix="/auth", tags=["auth"])


class TelegramAuthRequest(BaseModel):
    init_data: str


class RobloxCallbackRequest(BaseModel):
    code: str
    code_verifier: str


@router.post("/telegram")
async def auth_telegram(body: TelegramAuthRequest):
    try:
        tg_user = validate_init_data(body.init_data, settings.bot_token)
    except AuthError as e:
        raise HTTPException(status_code=401, detail=str(e))  # noqa: B904
    async with get_conn() as conn:
        row = await (
            await conn.execute("SELECT id FROM users WHERE telegram_id = %s", (tg_user.id,))
        ).fetchone()
        if row is None:
            cur = await conn.execute(
                "INSERT INTO users (telegram_id, username) VALUES (%s, %s) RETURNING id",
                (tg_user.id, tg_user.username),
            )
            row = await cur.fetchone()
            user_id = row["id"]
            from core.rewards.welcome import grant_welcome

            await grant_welcome(conn, {"id": user_id})
        else:
            user_id = row["id"]
            await conn.execute(
                "UPDATE users SET username = %s WHERE id = %s", (tg_user.username, user_id)
            )
        await conn.commit()
    return {"access_token": issue_token(user_id), "token_type": "bearer"}


@router.get("/roblox/url")
async def roblox_url():
    state = secrets.token_urlsafe(16)
    verifier, challenge = generate_pkce()
    url = build_auth_url(state, challenge)
    return {"url": url, "state": state, "code_verifier": verifier}


@router.post("/roblox/callback")
async def roblox_callback(body: RobloxCallbackRequest):
    try:
        token_data = await exchange_code(body.code, body.code_verifier)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))  # noqa: B904
    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(status_code=400, detail="no access token")  # noqa: B904
    try:
        info = await get_user_info(access_token)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))  # noqa: B904
    roblox_id = info.get("sub") or info.get("id")
    roblox_username = info.get("preferred_username") or info.get("name")
    async with get_conn() as conn:
        row = await (
            await conn.execute("SELECT id FROM users WHERE roblox_user_id = %s", (roblox_id,))
        ).fetchone()
        if row is None:
            cur = await conn.execute(
                "INSERT INTO users (roblox_user_id, roblox_username) VALUES (%s, %s) RETURNING id",
                (roblox_id, roblox_username),
            )
            row = await cur.fetchone()
            user_id = row["id"]
        else:
            user_id = row["id"]
            await conn.execute(
                "UPDATE users SET roblox_username = %s WHERE id = %s", (roblox_username, user_id)
            )
        await conn.commit()
    return {"access_token": issue_token(user_id), "token_type": "bearer"}
