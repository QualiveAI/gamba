"""Durable inbox: validate, encrypt, insert, затем ACK у HTTP/polling адаптера."""

from app.bot.pool import managed_owner_matches, observe_managed_update, trusted_main
from app.bot.security import BotSecurityError, encode_update, positive_id

_PAYMENT_FIELDS = frozenset(
    {
        "successful_payment",
        "refunded_payment",
        "gift",
        "unique_gift",
        "gift_upgrade_sent",
        "gift_upgrade_received",
        "paid_media",
        "paid_message_price_changed",
    }
)


def validate_update(update: dict) -> None:
    if not isinstance(update, dict):
        raise BotSecurityError("update_invalid")
    value = update.get("update_id")
    if type(value) is not int or not 0 <= value < 2**63:
        raise BotSecurityError("update_id_invalid")


def event_allowed(bot: dict, update: dict) -> bool:
    if bot["kind"] == "main":
        return trusted_main(bot)
    # Managed updates не источник merchant-платежей и не канал регистрации других ботов.
    if (
        "managed_bot" in update
        or "pre_checkout_query" in update
        or "purchased_paid_media" in update
    ):
        return False
    message = update.get("message")
    if not isinstance(message, dict) or any(key in message for key in _PAYMENT_FIELDS):
        return False
    sender, chat = message.get("from"), message.get("chat")
    return bool(
        isinstance(sender, dict)
        and isinstance(chat, dict)
        and sender.get("is_bot") is False
        and positive_id(sender.get("id"))
        and managed_owner_matches(bot, sender["id"])
        and chat.get("type") == "private"
        and chat.get("id") == sender["id"]
        and not message.get("sender_chat")
    )


async def save_update(conn, *, bot: dict, update: dict) -> tuple[int, bool]:
    """Без commit; даже отклонённое событие получает дедупликационный ключ."""
    validate_update(update)
    allowed = event_allowed(bot, update)
    # У отклонённого payload нет полезных данных; не сохраняем чужие PII/платежи.
    payload = update if allowed else {"update_id": update["update_id"]}
    row = await (
        await conn.execute(
            "INSERT INTO bot_inbox (bot_id, update_id, credential_version, payload_encrypted, "
            "status, last_error_code, finished_at) VALUES (%s, %s, %s, %s, %s, %s, "
            "CASE WHEN %s THEN NULL ELSE now() END) ON CONFLICT (bot_id, update_id) "
            "DO NOTHING RETURNING id",
            (
                bot["bot_id"],
                update["update_id"],
                bot["credential_version"],
                encode_update(payload),
                "pending" if allowed else "dropped",
                None if allowed else "untrusted_event",
                allowed,
            ),
        )
    ).fetchone()
    if row:
        if allowed and "managed_bot" in update:
            # Отзываем managed-сессии до ACK manager update, не ждём backlog worker.
            await observe_managed_update(conn, source=bot, update=update)
        return int(row["id"]), True
    row = await (
        await conn.execute(
            "SELECT id FROM bot_inbox WHERE bot_id = %s AND update_id = %s",
            (bot["bot_id"], update["update_id"]),
        )
    ).fetchone()
    return int(row["id"]), False
