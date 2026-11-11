"""Отдельный bounded worker платёжного inbox, без фоновой задачи внутри API."""

import argparse
import asyncio
import contextlib
import logging
import signal
import sys

logger = logging.getLogger("payments.worker")


async def run_worker(
    *,
    once: bool = False,
    interval: float = 5,
    batch_size: int = 100,
    max_attempts: int = 12,
    stop: asyncio.Event | None = None,
) -> int:
    from app.db import close_pool, init_pool
    from core.payments.events import process_pending
    from core.payments.policy import runtime_settings
    from core.registry import loader

    if getattr(runtime_settings(), "payments_mode", "disabled") not in ("sandbox", "live"):
        logger.info("Платёжный worker выключен: соединения не открыты")
        return 0
    if not 1 <= batch_size <= 1000 or not 1 <= max_attempts <= 100 or interval < 1:
        raise ValueError("Некорректные параметры worker")
    stop = stop or asyncio.Event()
    loop = asyncio.get_running_loop()
    for name in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError, RuntimeError):
            loop.add_signal_handler(name, stop.set)
    errors = 0
    loader.discover_plugins()
    try:
        await init_pool()
        while not stop.is_set():
            if getattr(runtime_settings(), "payments_mode", "disabled") not in ("sandbox", "live"):
                break
            try:
                results = await process_pending(batch_size, max_attempts=max_attempts)
                logger.info("Heartbeat payment inbox: обработано=%s", len(results))
                errors = 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Только тип ошибки: provider body/секреты не попадают в лог.
                logger.error("Heartbeat payment inbox: ошибка=%s", type(exc).__name__)
                errors += 1
                if once:
                    return 1
            if once:
                return 0
            delay = min(60, interval * (2 ** min(errors, 4)))
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=delay)
    finally:
        await close_pool()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Обработка durable payment inbox")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=5)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--max-attempts", type=int, default=12)
    options = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        return asyncio.run(
            run_worker(
                once=options.once,
                interval=options.interval,
                batch_size=options.batch_size,
                max_attempts=options.max_attempts,
            )
        )
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
