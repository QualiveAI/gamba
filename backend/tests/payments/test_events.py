import asyncio
import uuid
from dataclasses import replace

import pytest

from app.db import get_conn
from core.contracts.payment import PaymentError
from core.payments.apply import apply_event
from core.payments.events import ingest, process_event, record_verified_event
from core.payments.intents import get_intent
from core.payments.sandbox import SandboxAdapter


def evidence_for(intent, **changes):
    adapter = SandboxAdapter()
    adapter.rail_key = intent.rail
    return replace(adapter.sandbox_evidence(intent), **changes)


@pytest.mark.asyncio
async def test_ingest_immutable_payload(payment_runtime):
    key = uuid.uuid4().hex
    first = await ingest("paygate", key, {"x": 1}, mode="sandbox")
    assert await ingest("paygate", key, {"x": 1}, mode="sandbox") == first
    with pytest.raises(PaymentError) as exc:
        await ingest("paygate", key, {"x": 2}, mode="sandbox")
    assert exc.value.code == "event_payload_conflict"


@pytest.mark.asyncio
async def test_raw_success_untrusted(payment_factory):
    user, _, intent = await payment_factory()
    eid = await ingest(
        "paygate",
        uuid.uuid4().hex,
        {"status": "succeeded", "verified": True, "amount_minor": 100, "user_id": user["id"]},
        intent.id,
        mode="sandbox",
    )
    async with get_conn() as conn:
        result = await process_event(conn, eid)
        assert result.status == "rejected_unverified" and not result.credited
        refused = await apply_event(
            conn, {"amount_minor": 100, "currency": "units", "user_id": user["id"]}
        )
        assert refused.status == "rejected_unverified"
    assert (await get_intent(intent.id)).status == "pending"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "failed", "expired"])
async def test_non_success_never_credits(payment_factory, status):
    user, _, intent = await payment_factory()
    evidence = evidence_for(intent, status=status)
    async with get_conn() as conn:
        event_id = await record_verified_event(conn, evidence)
        result = await process_event(conn, event_id)
        assert not result.credited and result.status == status
        balance = await (
            await conn.execute("SELECT balance_units FROM users WHERE id=%s", (user["id"],))
        ).fetchone()
        assert balance["balance_units"] == 0


@pytest.mark.asyncio
async def test_sandbox_guest_never_touches_live_balance(payment_factory):
    user, _, intent = await payment_factory(guest=True)
    async with get_conn() as conn:
        event_id = await record_verified_event(conn, evidence_for(intent))
        result = await process_event(conn, event_id)
        assert result.status == "sandbox_processed" and not result.credited and result.sandbox
        wallet = await (
            await conn.execute("SELECT balance_units FROM users WHERE id=%s", (user["id"],))
        ).fetchone()
        ledger = await (
            await conn.execute(
                "SELECT count(*) AS n FROM ledger_entries WHERE user_id=%s", (user["id"],)
            )
        ).fetchone()
        assert wallet["balance_units"] == 0 and ledger["n"] == 0
    assert (await get_intent(intent.id)).status == "sandbox_succeeded"


@pytest.mark.asyncio
async def test_two_events_one_intent_only_one_settlement(payment_factory):
    _, _, intent = await payment_factory()
    ids = []
    async with get_conn() as conn:
        for suffix in ("poll", "webhook"):
            ids.append(
                await record_verified_event(
                    conn,
                    evidence_for(
                        intent,
                        provider_event_id=f"event:{intent.id}:{suffix}",
                    ),
                )
            )

    async def process(event_id):
        async with get_conn() as conn, conn.transaction():
            return await process_event(conn, event_id)

    results = await asyncio.gather(*(process(eid) for eid in ids))
    assert sorted(item.status for item in results) == ["duplicate", "sandbox_processed"]
    async with get_conn() as conn:
        row = await (
            await conn.execute(
                "SELECT count(*) AS n FROM events WHERE idempotency_key=%s",
                (f"deposit:{intent.id}",),
            )
        ).fetchone()
        assert row["n"] == 1


@pytest.mark.asyncio
async def test_wrong_amount_and_destination_rejected(payment_factory):
    _, _, intent = await payment_factory(method="crypto")
    async with get_conn() as conn:
        eid = await record_verified_event(conn, evidence_for(intent, address="different"))
        result = await process_event(conn, eid)
        assert result.status == "crypto_destination_mismatch"
        eid = await record_verified_event(
            conn,
            evidence_for(
                intent,
                provider_event_id="amount:" + intent.id,
                amount_atomic=intent.provider_amount_atomic + 1,
            ),
        )
        result = await process_event(conn, eid)
        assert result.status == "payment_amount_currency_mismatch"


@pytest.mark.asyncio
async def test_kill_switch_retains_verified_inbox(payment_factory):
    _, _, intent = await payment_factory()
    async with get_conn() as conn:
        eid = await record_verified_event(conn, evidence_for(intent))
        await conn.execute(
            "UPDATE system_config SET value='{\"value\":false}' WHERE key='deposits_enabled'"
        )
        result = await process_event(conn, eid)
        row = await (
            await conn.execute("SELECT processed_at FROM payment_events WHERE id=%s", (eid,))
        ).fetchone()
        assert result.status == "payment_kill_switch" and row["processed_at"] is None
    assert (await get_intent(intent.id)).status == "pending"
