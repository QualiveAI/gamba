"""Runtime только изолированной репетиции, не production entrypoint.

Все сетевые эффекты Telegram заменены явно внедрённым локальным sink. Сам worker,
API, giftcard services, очередь, DB transactions и lease используются настоящие.
"""

import argparse
import asyncio
import hashlib
import json
import os
import signal
import sys
from pathlib import Path

TARGET = os.getenv("WINDROP_DRILL_TARGET", "")
BOT_ID = 990000001
TELEGRAM_ID = 990000002


def guard() -> None:
    from urllib.parse import urlsplit

    if os.getenv("WINDROP_TESTING") != "1" or os.getenv("ENV") != "test":
        raise RuntimeError("Drill разрешён только с отключённым dotenv в test")
    if TARGET not in {"windrop_failover_drill_test", "windrop_failover_retry_test"}:
        raise RuntimeError("Неподтверждённый drill target")
    target = urlsplit(os.getenv("DATABASE_URL", ""))
    if (
        target.hostname != "drill-db"
        or target.port != 5432
        or target.path != f"/{TARGET}"
        or target.username != TARGET
    ):
        raise RuntimeError(
            "Нужен отдельный drill DB/role внутри internal Docker network"
        )
    if (
        os.getenv("PAYMENTS_MODE") != "disabled"
        or os.getenv("MANAGED_BOTS_ENABLED") != "false"
    ):
        raise RuntimeError("Внешние платежи и managed боты в drill запрещены")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def seed() -> dict:
    from app.bot.pool import confirm_private_chat, register_main
    from app.db import close_pool, get_conn, init_pool
    from app.giftcards import service
    from core.engine.ledger.ledger import post_entry

    await init_pool()
    try:
        async with get_conn() as conn, conn.transaction():
            row = await (
                await conn.execute(
                    "SELECT current_database() AS db, current_user AS role, rolsuper, "
                    "rolcreatedb, rolcreaterole, rolreplication, rolbypassrls "
                    "FROM pg_roles WHERE rolname = current_user"
                )
            ).fetchone()
            if (
                row["db"] != TARGET
                or row["role"] != TARGET
                or any(
                    row[key]
                    for key in (
                        "rolsuper",
                        "rolcreatedb",
                        "rolcreaterole",
                        "rolreplication",
                        "rolbypassrls",
                    )
                )
            ):
                raise RuntimeError("Небезопасная роль drill")
            count = await (
                await conn.execute("SELECT count(*) AS n FROM users")
            ).fetchone()
            if count["n"]:
                raise RuntimeError("Seed требует новую пустую пользовательскую таблицу")
            bot = await register_main(
                conn, {"id": BOT_ID, "is_bot": True, "username": "synthetic_drill_bot"}
            )
            user = await (
                await conn.execute(
                    "INSERT INTO users (telegram_id, region, is_guest) "
                    "VALUES (%s, 'BR', FALSE) RETURNING *",
                    (TELEGRAM_ID,),
                )
            ).fetchone()
            await post_entry(conn, user["id"], "units", 1000, "test_drill_funding")
            await confirm_private_chat(conn, bot=bot, user=user, chat_id=TELEGRAM_ID)
        async with get_conn() as conn:
            sku = await service.create_sku(
                conn,
                operator_sku="TEST-ONLY-FAILOVER-DRILL",
                brand="Roblox",
                region="BR",
                card_currency="BRL",
                face_value_minor=731,
                coin_cost=137,
                sandbox=True,
                created_by=user["id"],
            )
            await service.set_sku_active(conn, sku_id=sku["id"], active=True)
            # Только синтетические строки, никогда не выводятся в журнал или HTTP result.
            codes = "code\nTEST-ONLY-FAILOVER-DRILL-ONE\nTEST-ONLY-FAILOVER-DRILL-TWO\n"
            await service.import_csv(
                conn,
                codes.encode("ascii"),
                sku_id=sku["id"],
                supplier_name="TEST-ONLY-NOT-A-SUPPLIER",
                batch_reference="TEST-ONLY-DRILL",
                provenance_reference="TEST-ONLY-NOT-A-PURCHASE",
                distribution_agreement_reference=None,
                imported_by=user["id"],
            )
        return {
            "user_id": user["id"],
            "sku_id": sku["id"],
            "initial_coins": 1000,
            "cost": 137,
        }
    finally:
        await close_pool()


class SinkClient:
    def __init__(self, *, pause_after_send: bool):
        import httpx

        self.client = httpx.AsyncClient(trust_env=False, timeout=3)
        self.pause_after_send = pause_after_send

    async def call(self, _synthetic_token: str, method: str, **params):
        if method == "getMe":
            return {"id": BOT_ID, "is_bot": True, "username": "synthetic_drill_bot"}
        if method != "sendMessage":
            raise RuntimeError("Drill sink не допускает этот метод")
        # В sink уходит только digest синтетического текста, не code и не token.
        text = params["text"]
        response = await self.client.post(
            "http://drill-sink:18184/capture",
            json={
                "message_hash": hashlib.sha256(text.encode()).hexdigest(),
                "giftcard": "TEST-ONLY-FAILOVER-DRILL-" in text,
                "protected": params.get("protect_content", False),
            },
        )
        response.raise_for_status()
        receipt = response.json()
        if self.pause_after_send:
            # Внешний sink уже принял send, но worker не получил receipt для DB commit.
            # Оркестратор остановит ЭТОТ процесс SIGKILL; lease не изменяется вручную.
            await asyncio.Event().wait()
        return receipt

    async def aclose(self):
        await self.client.aclose()


async def worker(*, pause_after_send: bool) -> None:
    from app.bot.worker import run_worker
    from app.db import close_pool, init_pool

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)
    client = SinkClient(pause_after_send=pause_after_send)
    await init_pool()
    try:
        await run_worker(stop=stop, client=client)
    finally:
        await client.aclose()
        await close_pool()


def run_api(instance: str, port: int) -> None:
    import uvicorn
    from app.main import app

    @app.middleware("http")
    async def mark_instance(request, call_next):
        response = await call_next(request)
        response.headers["X-Drill-Instance"] = instance
        return response

    uvicorn.run(app, host="0.0.0.0", port=port, access_log=False, log_level="warning")


def run_sink() -> None:
    import uvicorn
    from fastapi import FastAPI

    sink = FastAPI()
    accepted = []

    @sink.post("/capture")
    async def capture(body: dict):
        if set(body) != {"message_hash", "giftcard", "protected"}:
            raise RuntimeError("Sink принимает только digest и флаги")
        accepted.append(body)
        return {"message_id": len(accepted)}

    @sink.get("/stats")
    async def stats():
        cards = [item for item in accepted if item["giftcard"]]
        return {
            "send_count": len(accepted),
            "giftcard_send_count": len(cards),
            "unique_giftcard_messages": len({item["message_hash"] for item in cards}),
            "all_giftcard_protected": all(item["protected"] for item in cards),
        }

    uvicorn.run(sink, host="0.0.0.0", port=18184, access_log=False, log_level="warning")


def controller() -> None:
    import httpx

    with httpx.Client(trust_env=False, timeout=3) as client:
        for line in sys.stdin:
            try:
                request = json.loads(line)
                response = client.request(
                    request["method"],
                    request["url"],
                    json=request.get("json"),
                    headers=request.get("headers"),
                )
                try:
                    body = response.json()
                except ValueError:
                    body = None
                result = {
                    "status": response.status_code,
                    "headers": dict(response.headers),
                    "body": body,
                }
            except (
                OSError,
                RuntimeError,
                ValueError,
                KeyError,
                httpx.HTTPError,
            ) as exc:
                result = {"error": type(exc).__name__}
            print(json.dumps(result, ensure_ascii=False), flush=True)


def main() -> None:
    guard()
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("api", "worker", "sink", "seed", "controller"))
    parser.add_argument("--instance", choices=("primary", "standby"), default="primary")
    parser.add_argument("--port", type=int, choices=(18181, 18182), default=18181)
    parser.add_argument("--pause-after-send", action="store_true")
    options = parser.parse_args()
    if options.mode == "controller":
        controller()
    elif options.mode == "api":
        run_api(options.instance, options.port)
    elif options.mode == "sink":
        run_sink()
    elif options.mode == "seed":
        print(json.dumps(asyncio.run(seed())))
    else:
        asyncio.run(worker(pause_after_send=options.pause_after_send))


if __name__ == "__main__":
    main()
