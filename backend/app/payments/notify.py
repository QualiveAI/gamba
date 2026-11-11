"""Уведомление о депозите — только transactional outbox, никаких fire-and-forget HTTP."""

from core.contracts.payment import PaymentError


async def enqueue_deposit(conn, *, user_id: int, coins: int, rail: str, intent_id: str) -> int:
    from app.bot.outbox import enqueue

    return await enqueue(
        conn,
        kind="deposit_confirmed",
        user_id=user_id,
        payload={"coins": coins, "rail": rail, "intent_id": intent_id},
        dedupe_key=f"deposit_confirmed:{intent_id}",
        bot_id=None,
    )


async def notify_deposit(telegram_id: int, amount_minor: int, rail: str) -> None:
    # У прежней функции нет conn/intent_id и неоднозначная сумма. Молчаливый
    # fallback обошёл бы transactional outbox и повторно отправил уведомление.
    raise PaymentError("legacy_notification_forbidden")
