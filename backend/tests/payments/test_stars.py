import uuid

import pytest

from app.db import get_conn
from app.payments import notify, stars
from core.payments.intents import get_intent


class MainTransport:
    merchant_bot_id = 123456

    async def create_invoice(self, *, title, description, payload, currency, total_amount):
        assert currency == "XTR" and total_amount == 90
        return "https://t.me/$fixture"

    async def refund(self, *, telegram_id, charge_id):
        return True


@pytest.fixture
async def live_stars(payment_runtime):
    payment_runtime.payments_mode = "live"
    stars.configure_main_bot_transport(MainTransport())
    yield
    stars.configure_main_bot_transport(None)


@pytest.mark.asyncio
async def test_precheckout_owner_currency_amount_and_expiry(payment_factory, live_stars):
    user, _, intent = await payment_factory(method="stars")
    async with get_conn() as conn:
        validate = stars.validate_stars_precheckout
        common = {"invoice_payload": f"deposit:{intent.id}", "currency": "XTR", "total_amount": 90}
        assert await validate(conn, user_id=user["id"], **common)
        assert not await validate(conn, user_id=user["id"] + 1, **common)
        assert not await validate(conn, user_id=user["id"], **dict(common, total_amount=100))
        assert not await validate(conn, user_id=user["id"], **dict(common, currency="BRL"))


@pytest.mark.asyncio
async def test_stars_atomic_credit_and_dedupe(payment_factory, live_stars, monkeypatch):
    user, _, intent = await payment_factory(method="stars")
    notifications = []

    async def fake_enqueue(conn, **payload):
        notifications.append(payload)
        return 1

    monkeypatch.setattr(notify, "enqueue_deposit", fake_enqueue)
    args = {
        "user_id": user["id"],
        "invoice_payload": f"deposit:{intent.id}",
        "currency": "XTR",
        "total_amount": 90,
        "charge_id": uuid.uuid4().hex,
    }
    async with get_conn() as conn:
        first = await stars.settle_stars_payment(conn, **args)
        duplicate = await stars.settle_stars_payment(conn, **args)
        assert first.credited and first.status == "processed"
        assert not duplicate.credited and duplicate.status == "duplicate"
        wallet = await (
            await conn.execute("SELECT balance_units FROM users WHERE id=%s", (user["id"],))
        ).fetchone()
        assert wallet["balance_units"] == 100
    assert len(notifications) == 1 and notifications[0]["coins"] == 100
    assert (await get_intent(intent.id)).status == "succeeded"


@pytest.mark.asyncio
async def test_existing_ledger_mismatch_rolls_back(payment_factory, live_stars, monkeypatch):
    user, _, intent = await payment_factory(method="stars")
    async with get_conn() as conn:
        # Моделируем неоднозначный старый баланс без ledger; settlement не "чинит" его.
        await conn.execute("UPDATE users SET balance_units=123 WHERE id=%s", (user["id"],))
        result = await stars.settle_stars_payment(
            conn,
            user_id=user["id"],
            invoice_payload=f"deposit:{intent.id}",
            currency="XTR",
            total_amount=90,
            charge_id=uuid.uuid4().hex,
        )
        assert result.status == "ledger_rejected" and not result.credited
        row = await (
            await conn.execute("SELECT balance_units FROM users WHERE id=%s", (user["id"],))
        ).fetchone()
        assert row["balance_units"] == 123
        count = await (
            await conn.execute(
                "SELECT count(*) AS n FROM ledger_entries WHERE user_id=%s", (user["id"],)
            )
        ).fetchone()
        assert count["n"] == 0
    assert (await get_intent(intent.id)).status == "pending"


@pytest.mark.asyncio
async def test_outbox_failure_rolls_back_money(payment_factory, live_stars, monkeypatch):
    user, _, intent = await payment_factory(method="stars")

    async def failing_enqueue(conn, **kwargs):
        raise RuntimeError("fixture")

    monkeypatch.setattr(notify, "enqueue_deposit", failing_enqueue)
    async with get_conn() as conn:
        result = await stars.settle_stars_payment(
            conn,
            user_id=user["id"],
            invoice_payload=f"deposit:{intent.id}",
            currency="XTR",
            total_amount=90,
            charge_id=uuid.uuid4().hex,
        )
        assert result.status == "settlement_failed"
        wallet = await (
            await conn.execute("SELECT balance_units FROM users WHERE id=%s", (user["id"],))
        ).fetchone()
        assert wallet["balance_units"] == 0
    assert (await get_intent(intent.id)).status == "pending"


@pytest.mark.asyncio
async def test_refund_owner_hold_and_mock_transport(payment_factory, live_stars):
    from core.contracts.payment import PaymentError

    user, quote, intent = await payment_factory(method="stars")
    owner = dict(user, telegram_id=7654321)
    async with get_conn() as conn:
        paid = await stars.settle_stars_payment(
            conn,
            user_id=user["id"],
            invoice_payload=f"deposit:{intent.id}",
            currency="XTR",
            total_amount=90,
            charge_id=uuid.uuid4().hex,
        )
        assert paid.credited
        outbox = await (
            await conn.execute(
                "SELECT payload FROM bot_outbox WHERE dedupe_key=%s",
                (f"deposit_confirmed:{intent.id}",),
            )
        ).fetchone()
        assert outbox["payload"] == {"coins": quote.coins, "rail": "stars", "intent_id": intent.id}
        with pytest.raises(PaymentError):
            await stars.request_stars_refund(
                conn, intent_id=intent.id, owner=dict(owner, auth_scope="managed")
            )
        requested = await stars.request_stars_refund(conn, intent_id=intent.id, owner=owner)
        repeated = await stars.request_stars_refund(conn, intent_id=intent.id, owner=owner)
        assert requested == repeated == {"intent_id": intent.id, "refund_status": "requested"}
        wallet = await (
            await conn.execute(
                "SELECT balance_units FROM users WHERE id=%s",
                (user["id"],),
            )
        ).fetchone()
        assert wallet["balance_units"] == 0
    # Ни одного внешнего запроса: MainTransport.refund возвращает fixture True.
    result = await stars.execute_stars_refund(intent_id=intent.id, owner=owner)
    assert result["refund_status"] == "refunded"
    repeated = await stars.execute_stars_refund(intent_id=intent.id, owner=owner)
    assert repeated == result
    assert (await get_intent(intent.id)).status == "refunded"


@pytest.mark.asyncio
async def test_legacy_stars_credit_closed():
    from core.contracts.payment import PaymentError

    with pytest.raises(PaymentError):
        await stars.handle_successful_payment(None, 1, 100, "payload")
