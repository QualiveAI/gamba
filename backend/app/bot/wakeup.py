"""Событийное пробуждение worker вместо постоянного опроса БД.

Neon free засыпает только при отсутствии запросов, а free-квота считается в
compute-hours. Опрос каждую секунду не даёт базе уснуть и выжигает квоту за
неделю, поэтому worker ждёт сигнал в Redis (BLPOP), а БД трогает только когда
есть работа. Redis здесь — не источник истины: сигнал best-effort, durable
очередь остаётся в bot_inbox/bot_outbox.

Если Redis недоступен, notify/wait деградируют в no-op, и worker возвращается к
обычному интервальному опросу — доставка не теряется, но растёт нагрузка.
"""

import asyncio
import contextlib

from core.ops.redis_client import get_redis

INBOX_SIGNAL_KEY = "windrop:bot:inbox:signal"
_MAX_SIGNALS = 64


async def notify_inbox() -> None:
    """Best-effort сигнал после durable commit; ошибки Redis не ломают webhook."""
    with contextlib.suppress(Exception):
        r = await get_redis()
        await r.lpush(INBOX_SIGNAL_KEY, "1")
        # Сигналы не накапливаем: одного достаточно, чтобы разбудить worker.
        await r.ltrim(INBOX_SIGNAL_KEY, 0, _MAX_SIGNALS - 1)


async def wait_for_work(timeout: float) -> bool:
    """True — пришёл сигнал; False — таймаут или Redis недоступен."""
    try:
        r = await get_redis()
        result = await r.blpop(INBOX_SIGNAL_KEY, timeout=max(1, int(timeout)))
        return bool(result)
    except Exception:
        # Без Redis не крутим busy-loop: минимальная пауза, затем обычный опрос.
        await asyncio.sleep(min(2.0, max(0.5, timeout)))
        return False


def event_wait_enabled(settings) -> bool:
    return bool(getattr(settings, "bot_worker_event_wait", False))
