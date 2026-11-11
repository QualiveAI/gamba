"""Явный setup основного бота и единственный dev poller; импорт без side effects."""

import asyncio
import logging
import sys
from contextlib import suppress

from app.bot.client import TelegramAPIError, TelegramClient, retry_delay
from app.bot.inbox import save_update
from app.bot.pool import get_bot, register_main, trusted_main
from app.bot.security import BotSecurityError, main_bot_id
from app.bot.setup import configure_bot
from app.config import settings
from app.db import close_pool, get_conn, init_pool

logger = logging.getLogger(__name__)


async def configure_main_bot(client):
    if getattr(settings, "bot_mode", "disabled") not in {"polling", "webhook"}:
        raise BotSecurityError("bot_disabled")
    if settings.bot_mode == "polling" and settings.env not in {"dev", "test"}:
        raise BotSecurityError("polling_dev_only")
    me = await client.call(settings.bot_token, "getMe")
    async with get_conn() as conn, conn.transaction():
        bot = await register_main(conn, me)
    await configure_bot(
        client, bot=bot, token=settings.bot_token, webhook=settings.bot_mode == "webhook"
    )
    return bot


async def poll_main(client, *, stop: asyncio.Event | None = None):
    if (
        settings.env not in {"dev", "test"}
        or getattr(settings, "bot_mode", "disabled") != "polling"
    ):
        raise BotSecurityError("polling_dev_only")
    stop = stop or asyncio.Event()
    bot_id = main_bot_id()
    # Session advisory lock держится весь poller. Второй process не получает тот же token.
    async with get_conn() as lease_conn:
        locked = await (
            await lease_conn.execute("SELECT pg_try_advisory_lock(%s) AS locked", (bot_id,))
        ).fetchone()
        await lease_conn.commit()
        if not locked or not locked["locked"]:
            raise BotSecurityError("poller_already_running")
        try:
            info = await client.call(settings.bot_token, "getWebhookInfo")
            if not isinstance(info, dict) or info.get("url"):
                # Никогда автоматически deleteWebhook/drop_pending_updates для живого бота.
                raise BotSecurityError("webhook_active_polling_forbidden")
            await configure_main_bot(client)
            attempt = 0
            while not stop.is_set():
                async with get_conn() as conn:
                    bot = await get_bot(conn, bot_id)
                if not trusted_main(bot):
                    raise BotSecurityError("main_source_untrusted")
                try:
                    updates = await client.call(
                        settings.bot_token,
                        "getUpdates",
                        offset=bot["poll_offset"],
                        timeout=25,
                        limit=20,
                        allowed_updates=["message", "pre_checkout_query", "managed_bot"],
                    )
                    if not isinstance(updates, list):
                        raise TelegramAPIError("updates_response_invalid", retryable=True)
                    async with get_conn() as conn, conn.transaction():
                        current = await get_bot(conn, bot_id, lock=True)
                        if (
                            not trusted_main(current)
                            or current["credential_version"] != bot["credential_version"]
                        ):
                            raise BotSecurityError("polling_credentials_changed")
                        offset = current["poll_offset"]
                        for update in updates:
                            await save_update(conn, bot=current, update=update)
                            offset = max(offset, update["update_id"] + 1)
                        await conn.execute(
                            "UPDATE bot_registry SET poll_offset = %s WHERE bot_id = %s",
                            (offset, bot_id),
                        )
                    # Следующий getUpdates ACK только после durable commit.
                    attempt = 0
                except TelegramAPIError as exc:
                    attempt += 1
                    if not exc.retryable or attempt >= 8:
                        raise
                    with suppress(TimeoutError):
                        await asyncio.wait_for(
                            stop.wait(), timeout=retry_delay(attempt, exc.retry_after)
                        )
        finally:
            await lease_conn.execute("SELECT pg_advisory_unlock(%s)", (bot_id,))
            await lease_conn.commit()


async def main():
    if getattr(settings, "bot_mode", "disabled") == "disabled":
        return
    await init_pool()
    try:
        async with TelegramClient() as client:
            if settings.bot_mode == "webhook":
                await configure_main_bot(client)
                return
            await poll_main(client)
    finally:
        await close_pool()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception:
        logger.error("telegram_main_stopped code=bot_startup_failed")
        raise SystemExit(1) from None
