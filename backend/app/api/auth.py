import secrets

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.auth.jwt import issue_token
from app.auth.roblox_oauth import build_auth_url, exchange_code, generate_pkce, get_user_info
from app.auth.telegram import AuthError, validate_init_data
from app.bot.pool import get_bot, managed_owner_matches
from app.bot.security import BotSecurityError, decrypt_secret, main_bot_id
from app.bot.users import ensure_guest_user, ensure_telegram_user
from app.config import settings
from app.db import get_conn

router = APIRouter(prefix="/auth", tags=["auth"])


class TelegramAuthRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    init_data: str = Field(max_length=16384)
    auth_bot_id: int | None = Field(default=None, gt=0, lt=2**63, strict=True)


class RobloxCallbackRequest(BaseModel):
    code: str
    code_verifier: str


@router.post("/telegram")
async def auth_telegram(body: TelegramAuthRequest):
    if not body.init_data:
        if (
            body.auth_bot_id is not None
            or settings.env not in {"dev", "test"}
            or not getattr(settings, "allow_guest_auth", False)
        ):
            raise HTTPException(status_code=401, detail="telegram_auth_required")
        async with get_conn() as conn, conn.transaction():
            user = await ensure_guest_user(conn)
        return {"access_token": issue_token(user["id"], scope="guest"), "token_type": "bearer"}
    try:
        primary_id = main_bot_id()
        if body.auth_bot_id is None or body.auth_bot_id == primary_id:
            tg_user = validate_init_data(body.init_data, settings.bot_token)
            async with get_conn() as conn, conn.transaction():
                user = await ensure_telegram_user(
                    conn, telegram_id=tg_user.id, username=tg_user.username
                )
            token = issue_token(user["id"], scope="primary", auth_bot_id=primary_id)
        else:
            if not getattr(settings, "managed_bots_enabled", False):
                raise AuthError("managed_bots_disabled")
            async with get_conn() as conn, conn.transaction():
                bot = await get_bot(conn, body.auth_bot_id, lock=True)
                if not bot or not managed_owner_matches(bot, bot["owner_telegram_id"]):
                    raise AuthError("managed_bot_untrusted")
                tg_user = validate_init_data(
                    body.init_data,
                    decrypt_secret(bot["token_encrypted"]),
                    expected_owner_id=bot["owner_telegram_id"],
                )
                # Managed login не создаёт/переносит аккаунт и не меняет username пользователя.
                user = await (
                    await conn.execute(
                        "SELECT id FROM users WHERE id = %s AND telegram_id = %s "
                        "AND is_guest = FALSE",
                        (bot["owner_user_id"], tg_user.id),
                    )
                ).fetchone()
                if not user:
                    raise AuthError("managed_owner_unbound")
                token = issue_token(
                    user["id"],
                    scope="managed",
                    auth_bot_id=bot["bot_id"],
                    owner_telegram_id=bot["owner_telegram_id"],
                    credential_version=bot["credential_version"],
                )
    except (AuthError, BotSecurityError):
        raise HTTPException(status_code=401, detail="invalid_telegram_auth") from None
    return {"access_token": token, "token_type": "bearer"}


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
    return {"access_token": issue_token(user_id, scope="roblox"), "token_type": "bearer"}
