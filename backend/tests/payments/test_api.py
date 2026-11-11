import hashlib
import hmac
import uuid

import httpx
import pytest
from fastapi import FastAPI

from app.api.deps import get_current_user
from app.db import get_conn
from core.api import router as routes
from core.registry.registry import PluginRegistry
from plugins.payments.paymento.adapter import PaymentoAdapter


@pytest.fixture
async def payment_api(payment_factory):
    user, _, _ = await payment_factory(guest=True)
    app = FastAPI()
    app.include_router(routes.router)
    app.include_router(routes.deposits_router)
    app.include_router(routes.webhooks_router)
    app.dependency_overrides[get_current_user] = lambda: user
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client, user


@pytest.mark.asyncio
async def test_http_quote_intent_status_and_idempotency(payment_api):
    client, _ = payment_api
    methods = (await client.get("/meta/payment-methods")).json()
    assert methods["mode"] == "sandbox"
    assert {m["method"] for m in methods["methods"]} == {"stars", "gift", "card", "crypto"}
    response = await client.post(
        "/deposits/quote", json={"coins": 100, "method": "card", "channel": "web"}
    )
    assert response.status_code == 200
    quote = response.json()
    assert quote["gross_brl_minor"] == 972 and quote["provider_amount_atomic"] == "972"
    request = {"quote_id": quote["quote_id"], "idempotency_key": uuid.uuid4().hex}
    first = await client.post("/deposits", json=request)
    second = await client.post("/deposits", json=request)
    assert first.status_code == second.status_code == 200
    intent = first.json()
    assert (
        intent["intent_id"] == second.json()["intent_id"] == intent["client_payload"]["intent_id"]
    )
    status = (await client.get("/deposits/" + intent["intent_id"])).json()
    assert status["quote"]["quote_id"] == quote["quote_id"] and status["status"] == "pending"
    sandbox = await client.post(f"/deposits/{intent['intent_id']}/sandbox-settle")
    assert sandbox.json()["status"] == "sandbox_processed" and not sandbox.json()["credited"]
    assert (await client.get("/deposits/" + intent["intent_id"])).json()[
        "status"
    ] == "sandbox_succeeded"


@pytest.mark.asyncio
async def test_http_rejects_legacy_prices_and_channel_bypass(payment_api):
    client, _ = payment_api
    assert (
        await client.post(
            "/deposits", json={"rail": "paygate", "amount_minor": 100, "currency": "units"}
        )
    ).status_code == 422
    assert (
        await client.post(
            "/deposits/quote", json={"coins": 100, "method": "card", "channel": "telegram"}
        )
    ).status_code == 403


@pytest.mark.asyncio
async def test_http_raw_signed_ipn_is_durable_not_credited(payment_api, monkeypatch):
    client, _ = payment_api
    registry = PluginRegistry()
    registry.register(PaymentoAdapter(secret_key="fixture-secret", api_key="fixture-key"))
    monkeypatch.setattr(routes, "registry", registry)
    payment_id = uuid.uuid4().hex
    body = (
        '{ "Token":"token","PaymentId":"' + payment_id + '","OrderId":"missing",'
        '"OrderStatus":7,"AdditionalData":[]}'
    ).encode()
    signature = hmac.new(b"fixture-secret", body, hashlib.sha256).hexdigest().upper()
    headers = {"X-HMAC-SHA256-Signature": signature, "Content-Type": "application/json"}
    stored = await client.post("/webhooks/paymento", content=body, headers=headers)
    assert stored.status_code == 200 and stored.json()["status"] == "stored"
    assert not stored.json()["credited"]
    replay = await client.put("/webhooks/paymento", content=body, headers=headers)
    assert replay.status_code == 200
    invalid = await client.post("/webhooks/paymento", content=body + b" ", headers=headers)
    assert invalid.status_code == 401
    async with get_conn() as conn:
        row = await (
            await conn.execute(
                "SELECT raw_body,authenticated,verification_state,processed_at FROM payment_events "
                "WHERE reference_id='missing' AND provider_event_id LIKE %s",
                (f"ipn:{payment_id}:%",),
            )
        ).fetchone()
        assert bytes(row["raw_body"]) == body
        assert row["authenticated"] and row["verification_state"] == "authenticated"
        assert row["processed_at"] is None
