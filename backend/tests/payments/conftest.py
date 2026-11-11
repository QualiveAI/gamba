"""Фикстуры только для выделенной тестовой БД, управляемой корневым conftest."""

import uuid
from types import SimpleNamespace

import pytest

from app.db import get_conn
from app.payments import gifts, stars
from core.payments import policy
from core.payments.intents import create_intent
from core.payments.quotes import create_quote


@pytest.fixture
async def payment_runtime(monkeypatch):
    settings = SimpleNamespace(
        payments_mode="sandbox",
        payment_web_enabled=True,
        bot_token="123456:fixture",
        coin_usd_price="0.015",
        usd_brl_rate="5.4",
        payment_fee_percent="20",
        stars_usd_price="0.02",
        quote_ttl_seconds=900,
        payments_max_coins=1000000,
        stars_enabled=True,
        gifts_enabled=True,
        stars_refunds_enabled=True,
        admin_ids={7654321},
        paymento_secret_key="",
        paymento_api_key="",
    )
    monkeypatch.setattr(policy, "runtime_settings", lambda: settings)
    monkeypatch.setattr(stars, "runtime_settings", lambda: settings)
    monkeypatch.setattr(gifts, "runtime_settings", lambda: settings)
    monkeypatch.setattr(stars, "_transport", None)
    async with get_conn() as conn:
        for name in (
            "deposits_enabled",
            "payments_stars_enabled",
            "payments_gift_enabled",
            "payments_card_enabled",
            "payments_crypto_enabled",
            "payments_stars_refunds_enabled",
        ):
            await conn.execute(
                "INSERT INTO system_config(key,value) VALUES (%s,'{\"value\":true}') "
                "ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value",
                (name,),
            )
    yield settings
    async with get_conn() as conn:
        await conn.execute(
            "UPDATE system_config SET value='{\"value\":false}' "
            "WHERE key='deposits_enabled' OR key LIKE 'payments_%_enabled'"
        )


@pytest.fixture
async def payment_factory(payment_runtime):
    async def factory(*, guest=False, method="card", coins=100, key=None, user=None):
        async with get_conn() as conn, conn.transaction():
            if user is None:
                tg = 8000000000 + uuid.uuid4().int % 1000000000
                row = await (
                    await conn.execute(
                        "INSERT INTO users(telegram_id,balance_units,is_guest) VALUES (%s,0,%s) RETURNING id",
                        (tg, guest),
                    )
                ).fetchone()
                user = {
                    "id": int(row["id"]),
                    "telegram_id": tg,
                    "is_guest": guest,
                    "auth_scope": "guest" if guest else "primary",
                    "auth_bot_id": None if guest else 123456,
                }
            quote = await create_quote(conn, user=user, coins=coins, method=method)
            intent = await create_intent(
                conn=conn,
                user=user,
                quote_id=quote.id,
                idempotency_key=key or uuid.uuid4().hex,
            )
        return user, quote, intent

    return factory
