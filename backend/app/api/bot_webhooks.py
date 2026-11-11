import json
import re

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.deps import get_current_user
from app.bot.inbox import save_update
from app.bot.pool import get_bot, trusted_main
from app.bot.security import MAX_UPDATE_BYTES, BotSecurityError, secret_matches
from app.config import settings
from app.db import get_conn

router = APIRouter(prefix="/bot/webhook", tags=["bot-webhooks"])
management_router = APIRouter(prefix="/bots", tags=["managed-bots"])


async def _bounded_update(request: Request) -> dict:
    length = request.headers.get("content-length")
    if length is not None:
        try:
            size = int(length)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid_content_length") from None
        if size < 0 or size > MAX_UPDATE_BYTES:
            raise HTTPException(status_code=413, detail="update_too_large")
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_UPDATE_BYTES:
            raise HTTPException(status_code=413, detail="update_too_large")
        raw.extend(chunk)
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError):
        raise HTTPException(status_code=400, detail="invalid_update") from None
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="invalid_update")
    return data


@router.post("/{bot_id}")
async def telegram_webhook(bot_id: int, request: Request):
    if getattr(settings, "bot_mode", "disabled") != "webhook":
        raise HTTPException(status_code=404, detail="webhook_disabled")
    secret = request.headers.get("x-telegram-bot-api-secret-token", "")
    # До request.stream/body/json: неавторизованный клиент не заставляет читать большой payload.
    if not secret or len(secret) > 256 or not 0 < bot_id < 2**63:
        raise HTTPException(status_code=403, detail="invalid_webhook_secret")
    async with get_conn() as conn:
        bot = await get_bot(conn, bot_id)
    if (
        not bot
        or bot["status"] != "active"
        or not secret_matches(secret, bot["webhook_secret_hash"])
    ):
        raise HTTPException(status_code=403, detail="invalid_webhook_secret")
    if bot["kind"] == "managed" and not getattr(settings, "managed_bots_enabled", False):
        raise HTTPException(status_code=403, detail="managed_bots_disabled")
    if bot["kind"] == "main" and not trusted_main(bot):
        raise HTTPException(status_code=403, detail="main_source_untrusted")
    update = await _bounded_update(request)
    try:
        async with get_conn() as conn, conn.transaction():
            # Ротация во время чтения тела не даёт принять update старым secret.
            current = await get_bot(conn, bot_id, lock=True)
            if (
                not current
                or current["status"] != "active"
                or current["credential_version"] != bot["credential_version"]
                or not secret_matches(secret, current["webhook_secret_hash"])
            ):
                raise HTTPException(status_code=403, detail="webhook_revoked")
            await save_update(conn, bot=current, update=update)
    except BotSecurityError:
        raise HTTPException(status_code=400, detail="invalid_update") from None
    # Транзакция и connection закрыты до 200; Telegram retry при DB failure безопасен.
    return {"ok": True}


@management_router.get("/me")
async def my_bots(user=Depends(get_current_user)):  # noqa: B008
    username = getattr(settings, "bot_username", "").lstrip("@")
    username = username if re.fullmatch(r"[A-Za-z0-9_]{5,32}", username) else ""
    enabled = bool(
        getattr(settings, "managed_bots_enabled", False)
        and username
        and getattr(settings, "bot_mode", "disabled") == "webhook"
        and user.get("auth_scope") in {"primary", "managed"}
        and not user.get("is_guest")
    )
    rows = []
    if user.get("auth_scope") in {"primary", "managed"} and not user.get("is_guest"):
        async with get_conn() as conn:
            rows = await (
                await conn.execute(
                    "SELECT bot_id, username, status FROM bot_registry WHERE kind = 'managed' "
                    "AND owner_telegram_id = %s AND (owner_user_id = %s OR owner_user_id IS NULL) "
                    "ORDER BY bot_id",
                    (user["telegram_id"], user["id"]),
                )
            ).fetchall()
    return {
        "enabled": enabled,
        "main_bot_username": username,
        "managed_bots": [dict(row) for row in rows],
        "create_url": f"https://t.me/{username}?start=managed" if enabled else None,
    }
