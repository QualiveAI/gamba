"""Watchdog: структурированные состояния и ограниченные повторные оповещения без секретов."""

import asyncio
from contextlib import suppress

from app.bot.client import TelegramAPIError, TelegramClient, retry_delay
from app.bot.pool import get_bot, trusted_main
from app.bot.security import MAX_ATTEMPTS, BotSecurityError, decrypt_secret, positive_id
from app.config import settings
from app.db import get_conn


async def record_failure(conn, *, bot_id: int, code: str, auth_failed: bool = False):
    await conn.execute(
        "UPDATE bot_registry SET health_status = %s, "
        "consecutive_failures = consecutive_failures + 1, "
        "last_error_code = %s, "
        "next_alert_at = CASE WHEN last_alert_at IS NULL AND NOT alert_pending "
        "THEN now() ELSE next_alert_at END, "
        "alert_pending = TRUE, updated_at = now() WHERE bot_id = %s",
        ("auth_failed" if auth_failed else "degraded", code, bot_id),
    )
    if auth_failed:
        # Не ротация аккаунтов и не обход блокировки: только отзыв сессий данного token.
        await conn.execute(
            "UPDATE bot_registry SET status = 'revoked', token_encrypted = NULL, "
            "credential_version = credential_version + 1, health_status = 'auth_failed' "
            "WHERE bot_id = %s AND kind = 'managed' AND status <> 'revoked'",
            (bot_id,),
        )


async def check_one(client) -> bool:
    async with get_conn() as conn, conn.transaction():
        bot = await (
            await conn.execute(
                "SELECT * FROM bot_registry WHERE status = 'active' AND next_health_at <= now() "
                "ORDER BY next_health_at LIMIT 1 FOR UPDATE SKIP LOCKED"
            )
        ).fetchone()
        if not bot:
            return False
        await conn.execute(
            "UPDATE bot_registry SET next_health_at = now() + interval '5 minutes' "
            "WHERE bot_id = %s",
            (bot["bot_id"],),
        )
    error = None
    try:
        if bot["kind"] == "main":
            if not trusted_main(bot):
                raise BotSecurityError("main_source_untrusted")
            token = settings.bot_token
        else:
            if not getattr(settings, "managed_bots_enabled", False):
                return False
            token = decrypt_secret(bot["token_encrypted"])
        me = await client.call(token, "getMe")
        if (
            not isinstance(me, dict)
            or me.get("id") != bot["bot_id"]
            or me.get("is_bot") is not True
        ):
            raise BotSecurityError("bot_identity_mismatch")
    except TelegramAPIError as exc:
        error = exc
    except BotSecurityError:
        error = TelegramAPIError("bot_identity_untrusted")
    async with get_conn() as conn, conn.transaction():
        current = await get_bot(conn, bot["bot_id"], lock=True)
        if not current or current["credential_version"] != bot["credential_version"]:
            return True
        if error is None:
            await conn.execute(
                "UPDATE bot_registry SET health_status = 'ok', last_health_at = now(), "
                "consecutive_failures = 0, updated_at = now() WHERE bot_id = %s",
                (bot["bot_id"],),
            )
        else:
            await record_failure(
                conn,
                bot_id=bot["bot_id"],
                code=error.code,
                auth_failed=error.code == "auth_failed",
            )
            await conn.execute(
                "UPDATE bot_registry SET last_health_at = now(), "
                "next_health_at = now() + %s * interval '1 second' WHERE bot_id = %s",
                (
                    retry_delay(current["consecutive_failures"] + 1, error.retry_after),
                    bot["bot_id"],
                ),
            )
    return True


async def send_one_alert(client) -> bool:
    token = getattr(settings, "healthcheck_bot_token", "")
    target = getattr(settings, "healthcheck_target_chat_id", "")
    if not token or not target:
        return False
    async with get_conn() as conn, conn.transaction():
        bot = await (
            await conn.execute(
                "SELECT bot_id, health_status, last_error_code, alert_attempts FROM bot_registry "
                "WHERE alert_pending = TRUE AND alert_attempts < %s AND next_alert_at <= now() "
                "ORDER BY next_alert_at LIMIT 1 FOR UPDATE SKIP LOCKED",
                (MAX_ATTEMPTS,),
            )
        ).fetchone()
        if not bot:
            return False
        await conn.execute(
            "UPDATE bot_registry SET alert_attempts = alert_attempts + 1, "
            "next_alert_at = now() + interval '5 minutes' WHERE bot_id = %s",
            (bot["bot_id"],),
        )
    error = None
    try:
        message = await client.call(
            token,
            "sendMessage",
            chat_id=target,
            text=f"WINDROP: bot_id={bot['bot_id']} state={bot['health_status']} "
            f"error={bot['last_error_code'] or 'none'}. Verifique as filas e o acesso.",
        )
        if not isinstance(message, dict) or not positive_id(message.get("message_id")):
            raise TelegramAPIError("alert_receipt_missing", retryable=True)
    except TelegramAPIError as exc:
        error = exc
    except BotSecurityError:
        error = TelegramAPIError("alert_configuration_invalid")
    async with get_conn() as conn, conn.transaction():
        if error is None:
            await conn.execute(
                "UPDATE bot_registry SET alert_pending = FALSE, alert_attempts = 0, "
                "last_alert_at = now(), last_alert_error_code = NULL, "
                "next_alert_at = now() + interval '15 minutes' WHERE bot_id = %s "
                "AND last_error_code IS NOT DISTINCT FROM %s",
                (bot["bot_id"], bot["last_error_code"]),
            )
        else:
            await conn.execute(
                "UPDATE bot_registry SET last_alert_error_code = %s, "
                "next_alert_at = now() + %s * interval '1 second' WHERE bot_id = %s",
                (
                    error.code,
                    retry_delay(bot["alert_attempts"] + 1, error.retry_after),
                    bot["bot_id"],
                ),
            )
    return True


async def run_healthcheck(*, stop: asyncio.Event | None = None, client=None):
    if getattr(settings, "bot_mode", "disabled") == "disabled":
        return
    stop = stop or asyncio.Event()
    owned_client = client is None
    client = client or TelegramClient()
    try:
        while not stop.is_set():
            await check_one(client)
            await send_one_alert(client)
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=30)
    finally:
        if owned_client:
            await client.aclose()
