"""Уведомления игрокам в Telegram от лица бота (fire-and-forget).

Backend не держит aiogram-поллинг, поэтому просто зовём Bot API напрямую.
Токен берём из BOT_TOKEN (общий с ботом, уже есть в infra/.env).
"""

import os

import httpx

TG_API = "https://api.telegram.org"


async def notify_deposit(telegram_id: int, amount_minor: int, rail: str) -> None:
    token = os.getenv("BOT_TOKEN", "")
    if not token or not telegram_id:
        return
    text = (
        f"💸 Депозит зачислен: +{amount_minor / 100:.2f}\n"
        f"Способ: {rail}\nОткрывай WINDROP и играй!"
    )
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            await client.post(
                f"{TG_API}/bot{token}/sendMessage",
                json={"chat_id": telegram_id, "text": text},
            )
    except Exception:  # noqa: BLE001 — уведомление не должно ломать зачисление
        pass
