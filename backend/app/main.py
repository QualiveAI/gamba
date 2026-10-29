import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

from app.api.admin import router as admin_router
from app.api.admin_ops import router as admin_ops_router
from app.api.admin_withdrawals import router as admin_withdrawals_router
from app.api.auth import router as auth_router
from app.api.cases import router as cases_router
from app.api.games import router as games_router
from app.api.giftcards import router as giftcards_router
from app.api.media import router as media_router
from app.api.payments import router as payments_router
from app.api.predictor import router as predictor_router
from app.api.rewards import router as rewards_router
from app.api.wallet import router as wallet_router
from app.api.withdrawals import router as withdrawals_router
from app.db import close_pool, healthcheck, init_pool
from core.admin.case_builder.router import router as case_builder_router
from core.api.router import (
    deposits_router,
    webhooks_router,
)
from core.api.router import (
    games_router as core_games_router,
)
from core.api.router import (
    router as meta_router,
)
from core.api.router import (
    withdrawals_router as core_withdrawals_router,
)
from core.observability.metrics import render_prometheus


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool()
    yield
    await close_pool()


app = FastAPI(title="roblox-case-platform", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(meta_router)
app.include_router(deposits_router)
app.include_router(webhooks_router)
app.include_router(core_games_router)
app.include_router(core_withdrawals_router)
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
app.include_router(admin_withdrawals_router)


@app.get("/health")
async def health() -> dict[str, str]:
    db, redis_status = await healthcheck()
    return {"db": db, "redis": redis_status}


@app.get("/metrics")
async def metrics(request: Request):
    import os

    token = request.headers.get("X-Admin-Token", "")
    allow = os.getenv("METRICS_ALLOW_IPS", "127.0.0.1").split(",")
    if token != os.getenv("METRICS_TOKEN", "") and request.client.host not in allow:
        return Response(status_code=404)
    return Response(content=render_prometheus(), media_type="text/plain")
