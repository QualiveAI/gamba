from fastapi import Depends, Header, HTTPException

from app.auth.jwt import AuthClaims, JWTError, verify_claims
from app.bot.pool import get_bot, managed_owner_matches
from app.bot.security import BotSecurityError, main_bot_id
from app.config import settings
from app.db import get_conn


async def _fetch_user(conn, user_id: int):
    return await (
        await conn.execute(
            "SELECT id, telegram_id, roblox_user_id, roblox_username, username, balance_units, "
            "balance_freebets, region, segment, predictor_mode, created_at, is_guest "
            "FROM users WHERE id = %s",
            (user_id,),
        )
    ).fetchone()


def validate_managed_session(claims: AuthClaims, user: dict, bot: dict | None) -> None:
    if (
        not bot
        or not managed_owner_matches(bot, user.get("telegram_id"))
        or user.get("is_guest")
        or claims.scope != "managed"
        or claims.auth_bot_id != bot["bot_id"]
        or bot["owner_user_id"] != user["id"]
        or claims.owner_telegram_id != bot["owner_telegram_id"]
        or claims.credential_version != bot["credential_version"]
    ):
        raise HTTPException(status_code=401, detail="managed_session_revoked")


async def get_current_user(authorization: str | None = Header(default=None)):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing_token")
    try:
        claims = verify_claims(authorization.split(" ", 1)[1].strip())
    except JWTError:
        raise HTTPException(status_code=401, detail="invalid_token") from None
    async with get_conn() as conn:
        user = await _fetch_user(conn, claims.user_id)
        if user is None:
            raise HTTPException(status_code=401, detail="user_not_found")
        user = dict(user)
        if claims.scope == "managed":
            if not getattr(settings, "managed_bots_enabled", False):
                raise HTTPException(status_code=401, detail="managed_session_revoked")
            bot = await get_bot(conn, claims.auth_bot_id)
            validate_managed_session(claims, user, bot)
            user["auth_owner_telegram_id"] = bot["owner_telegram_id"]
            user["auth_credential_version"] = bot["credential_version"]
        elif claims.scope == "guest":
            if (
                settings.env not in {"dev", "test"}
                or not getattr(settings, "allow_guest_auth", False)
                or not user["is_guest"]
                or user["telegram_id"] is not None
            ):
                raise HTTPException(status_code=401, detail="guest_auth_disabled")
        elif user["is_guest"]:
            raise HTTPException(status_code=401, detail="invalid_auth_scope")
        elif claims.scope == "primary":
            try:
                valid_primary = claims.auth_bot_id == main_bot_id()
            except BotSecurityError:
                valid_primary = False
            if not valid_primary or not user["telegram_id"]:
                raise HTTPException(status_code=401, detail="primary_auth_required")
        elif claims.scope == "roblox" and not user["roblox_user_id"]:
            raise HTTPException(status_code=401, detail="invalid_auth_scope")
    user["auth_scope"] = claims.scope
    user["auth_bot_id"] = claims.auth_bot_id
    return user


async def require_primary(user=Depends(get_current_user)):  # noqa: B008
    if user.get("auth_scope") != "primary" or user.get("is_guest"):
        raise HTTPException(status_code=403, detail="primary_auth_required")
    return user


async def require_admin(user=Depends(get_current_user)):  # noqa: B008
    if (
        user.get("auth_scope") != "primary"
        or user.get("is_guest")
        or user.get("telegram_id") not in settings.admin_ids
    ):
        raise HTTPException(status_code=403, detail="admin_only")
    return user
