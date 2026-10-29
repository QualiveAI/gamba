from fastapi import Depends, Header, HTTPException

from app.auth.jwt import JWTError, verify_token
from app.config import settings
from app.db import get_conn


async def _fetch_user(conn, user_id: int):
    return await (
        await conn.execute(
            "SELECT id, telegram_id, roblox_user_id, roblox_username, username, balance_units, region, segment, predictor_mode, created_at FROM users WHERE id = %s",  # noqa: E501
            (user_id,),
        )
    ).fetchone()


async def get_current_user(authorization: str | None = Header(default=None)):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing token")  # noqa: B904
    token = authorization.split(" ", 1)[1].strip()
    try:
        user_id = verify_token(token)
    except JWTError:
        raise HTTPException(status_code=401, detail="invalid token")  # noqa: B904
    async with get_conn() as conn:
        user = await _fetch_user(conn, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="user not found")  # noqa: B904
    return user


async def require_admin(user=Depends(get_current_user)):  # noqa: B008  # noqa: B008  # noqa: B008
    if user.get("telegram_id") not in settings.admin_ids:
        raise HTTPException(status_code=403, detail="admin only")  # noqa: B904
    return user
