import asyncio
import os
import secrets
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

from app.api.admin import router as admin_router
from app.api.admin_ops import router as admin_ops_router
from app.api.admin_withdrawals import router as admin_withdrawals_router
from app.api.auth import router as auth_router
from app.api.bot_webhooks import management_router as bot_management_router
from app.api.bot_webhooks import router as bot_webhooks_router
from app.api.cases import router as cases_router
from app.api.games import router as games_router
from app.api.giftcards import router as giftcards_router
from app.api.media import router as media_router
from app.api.payments import router as payments_router
from app.api.predictor import router as predictor_router
from app.api.rewards import router as rewards_router
from app.api.wallet import router as wallet_router
from app.api.withdrawals import router as withdrawals_router
from app.config import settings
from app.db import close_pool, init_pool
from app.ops.health import readiness
from app.payments.stars import configure_main_bot_transport
from core.admin.case_builder.router import router as case_builder_router
from core.api.router import (
    deposits_router,
    webhooks_router,
)
from core.api.router import (
    router as meta_router,
)
from core.observability.metrics import render_prometheus
from core.registry.loader import discover_plugins

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@asynccontextmanager
async def lifespan(app: FastAPI):
    transport = None
    await init_pool()
    try:
        if (
            settings.bot_mode != "disabled"
            and settings.payments_mode != "disabled"
            and settings.stars_enabled
        ):
            from app.bot.client import MainStarsTransport

            # Конструктор не обращается к сети; disabled вообще не создаёт клиент.
            transport = MainStarsTransport()
            configure_main_bot_transport(transport)
        yield
    finally:
        configure_main_bot_transport(None)
        try:
            if transport is not None:
                await transport.aclose()
        finally:
            await close_pool()


app = FastAPI(title="roblox-case-platform", lifespan=lifespan)

# Регистрация плагинов не запускает polling, scheduler или очередь Telegram.
discover_plugins()

# CORS включается только при явном allowlist: same-origin deployment за Caddy
# не должен получать лишние заголовки и preflight-путь. Telegram webhook приходит
# без Origin и секретным заголовком, поэтому прокси-схема его не касается.
if settings.cors_origins:
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        # JWT передаётся в Authorization, не в cookie: credentials выключены.
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        max_age=600,
    )

app.include_router(auth_router)
app.include_router(bot_webhooks_router)
app.include_router(bot_management_router)
app.include_router(meta_router)
app.include_router(deposits_router)
app.include_router(webhooks_router)
app.include_router(cases_router)
app.include_router(games_router)
app.include_router(payments_router)
app.include_router(giftcards_router)
app.include_router(withdrawals_router)
app.include_router(rewards_router)
app.include_router(predictor_router)
app.include_router(media_router)
app.include_router(wallet_router)
app.include_router(admin_router)
app.include_router(case_builder_router)
app.include_router(admin_ops_router)
app.include_router(admin_withdrawals_router)


@app.get("/health/live")
async def liveness() -> dict[str, str]:
    # Никаких обращений к БД, Redis, Telegram и другим внешним сервисам.
    return {"status": "ok"}


@app.get("/health")
@app.get("/health/ready")
async def health(response: Response) -> dict[str, str]:
    checks = await readiness()
    response.status_code = 200 if checks["status"] == "ok" else 503
    response.headers["Cache-Control"] = "no-store"
    return checks


@app.get("/metrics")
async def metrics(request: Request):
    expected = os.getenv("METRICS_TOKEN", "").strip()
    provided = request.headers.get("X-Admin-Token", "")
    # IP и пустая строка не являются аутентификацией, в том числе за reverse proxy.
    if not expected or not secrets.compare_digest(provided.encode(), expected.encode()):
        return Response(status_code=404)
    return Response(
        content=render_prometheus(),
        media_type="text/plain",
        headers={"Cache-Control": "no-store"},
    )
