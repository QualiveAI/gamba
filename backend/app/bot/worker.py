"""Отдельный worker durable Telegram inbox/outbox; при импорте и disabled сети нет."""

import asyncio
import json
import logging
import sys
from contextlib import suppress

from app.bot.client import TelegramAPIError, TelegramClient
from app.bot.dispatcher import FeatureUnavailable, SettlementDeferred, dispatch_update
from app.bot.healthcheck import check_one, record_failure, send_one_alert
from app.bot.notifications import DeliveryUnavailable, deliver_notification
from app.bot.pool import get_bot
from app.bot.queue import claim, fail, finish
from app.bot.security import BotSecurityError, decrypt_secret
from app.config import settings
from app.db import close_pool, get_conn, init_pool

logger = logging.getLogger(__name__)


def _failure(exc: Exception) -> tuple[str, bool, int | None]:
    if isinstance(exc, TelegramAPIError):
        return exc.code, exc.retryable, exc.retry_after
    if isinstance(exc, BotSecurityError):
        # str arbitrary exception не допускается: сообщения тут создаёт только наш модуль.
        return "bot_security_rejected", False, None
    if isinstance(exc, FeatureUnavailable):
        return "feature_disabled", True, 60
    if isinstance(exc, DeliveryUnavailable):
        return "private_chat_unavailable", True, 60
    if isinstance(exc, SettlementDeferred):
        return "stars_settlement_pending", True, 30
    # GiftCardError/PaymentError: разрешённый machine code, не .message/response/payload.
    code = getattr(exc, "code", None)
    allowed = {
        "owner_mismatch",
        "not_found",
        "manual_review_required",
        "disabled",
        "storage_not_configured",
        "sku_unavailable",
        "stars_charge_conflict",
        "stars_amount_currency_mismatch",
        "stars_merchant_mismatch",
        "invalid_stars_charge",
        "invoice_not_found",
        "payment_kill_switch",
        "ledger_rejected",
        "settlement_failed",
    }
    if isinstance(code, str) and code in allowed:
        return (
            code,
            code
            in {
                "disabled",
                "storage_not_configured",
                "payment_kill_switch",
                "ledger_rejected",
                "settlement_failed",
            },
            60,
        )
    return "worker_error", True, None


async def _claim(table: str):
    async with get_conn() as conn, conn.transaction():
        return await claim(conn, table)


async def _finish(
    table: str, job: dict, *, dropped: bool = False, message_id=None, sent_bot_id=None
):
    async with get_conn() as conn, conn.transaction():
        if table == "bot_outbox" and message_id is not None:
            await conn.execute(
                "UPDATE bot_outbox SET telegram_message_id = %s, sent_bot_id = %s "
                "WHERE id = %s AND claim_token = %s",
                (message_id, sent_bot_id, job["id"], job["claim_token"]),
            )
        await finish(conn, table, job, dropped=dropped)


async def _fail(table: str, job: dict, exc: Exception):
    code, retryable, delay = _failure(exc)
    async with get_conn() as conn, conn.transaction():
        await fail(conn, table, job, code=code, retryable=retryable, retry_after=delay)
        if job.get("bot_id") is not None:
            await record_failure(
                conn, bot_id=job["bot_id"], code=code, auth_failed=code == "auth_failed"
            )
        else:
            await conn.execute(
                "UPDATE bot_registry SET alert_pending = TRUE, last_error_code = %s, "
                "health_status = 'degraded' WHERE kind = 'main'",
                (code,),
            )
    logger.warning("telegram_job_failed queue=%s job_id=%s code=%s", table, job["id"], code)


async def process_inbox_one(client) -> bool:
    job = await _claim("bot_inbox")
    if not job:
        return False
    try:
        async with get_conn() as conn:
            bot = await get_bot(conn, job["bot_id"])
        if (
            not bot
            or bot["status"] != "active"
            or bot["credential_version"] != job["credential_version"]
        ):
            await _finish("bot_inbox", job, dropped=True)
            return True
        update = json.loads(decrypt_secret(job["payload_encrypted"]))
        await dispatch_update(client, bot=bot, update=update)
        await _finish("bot_inbox", job)
    except Exception as exc:
        await _fail("bot_inbox", job, exc)
    return True


async def process_outbox_one(client) -> bool:
    job = await _claim("bot_outbox")
    if not job:
        return False
    try:
        message_id, bot_id = await deliver_notification(client, job=job)
        await _finish("bot_outbox", job, message_id=message_id, sent_bot_id=bot_id)
    except Exception as exc:
        await _fail("bot_outbox", job, exc)
    return True


async def readiness_probe(conn) -> dict:
    row = await (
        await conn.execute(
            "SELECT to_regclass('public.bot_registry') IS NOT NULL AS registry, "
            "to_regclass('public.bot_inbox') IS NOT NULL AS inbox, "
            "to_regclass('public.bot_outbox') IS NOT NULL AS outbox, "
            "to_regclass('public.bot_private_chats') IS NOT NULL AS private_chats"
        )
    ).fetchone()
    return {"ready": all(row.values()), "schema": dict(row)}


async def run_worker(*, stop: asyncio.Event | None = None, client=None):
    if getattr(settings, "bot_mode", "disabled") == "disabled":
        return
    if settings.bot_mode == "polling" and settings.env not in {"dev", "test"}:
        raise BotSecurityError("polling_dev_only")
    stop = stop or asyncio.Event()
    owns_client = client is None
    client = client or TelegramClient()
    loop = asyncio.get_running_loop()
    next_health = 0.0
    try:
        while not stop.is_set():
            try:
                inbox_work = await process_inbox_one(client)
                outbox_work = await process_outbox_one(client)
                if loop.time() >= next_health:
                    await check_one(client)
                    await send_one_alert(client)
                    next_health = loop.time() + 30
            except Exception:
                # DB/client исключения могут содержать данные; не выводим repr/traceback.
                logger.error("telegram_worker_iteration_failed code=worker_unavailable")
                inbox_work = outbox_work = False
            if not inbox_work and not outbox_work:
                with suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=1)
    finally:
        if owns_client:
            await client.aclose()


async def main():
    if getattr(settings, "bot_mode", "disabled") == "disabled":
        return
    await init_pool()
    try:
        await run_worker()
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
        logger.error("telegram_worker_stopped code=startup_failed")
        raise SystemExit(1) from None
