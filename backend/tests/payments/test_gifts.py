import uuid

import pytest

from app.db import get_conn
from app.payments import gifts, notify
from core.contracts.payment import PaymentError


@pytest.mark.asyncio
async def test_gift_needs_custody_and_operator_valuation(
    payment_runtime, payment_factory, monkeypatch
):
    payment_runtime.payments_mode = "live"
    user, quote, intent = await payment_factory(method="gift")
    owner = {
        "id": user["id"],
        "telegram_id": 7654321,
        "auth_scope": "primary",
        "auth_bot_id": 123456,
        "is_guest": False,
    }

    async def enqueue(conn, **kwargs):
        return 1

    monkeypatch.setattr(notify, "enqueue_deposit", enqueue)
    async with get_conn() as conn:
        with pytest.raises(PaymentError):
            await gifts.record_manual_gift_receipt(
                conn,
                intent_id=intent.id,
                owner=owner,
                gift_id=uuid.uuid4().hex,
                custody_reference="https://receipt.invalid/screenshot.png",
            )
        receipt_id = await gifts.record_manual_gift_receipt(
            conn,
            intent_id=intent.id,
            owner=owner,
            gift_id=uuid.uuid4().hex,
            custody_reference="inventory-confirmed-123",
        )
        with pytest.raises(PaymentError):
            await gifts.review_gift(
                conn,
                intent_id=intent.id,
                receipt_event_id=receipt_id,
                valued_brl_minor=quote.gross_brl_minor + 1,
                owner=owner,
            )
        result = await gifts.review_gift(
            conn,
            intent_id=intent.id,
            receipt_event_id=receipt_id,
            valued_brl_minor=quote.gross_brl_minor,
            owner=owner,
        )
        duplicate = await gifts.review_gift(
            conn,
            intent_id=intent.id,
            receipt_event_id=receipt_id,
            valued_brl_minor=quote.gross_brl_minor,
            owner=owner,
        )
        assert result.credited and not duplicate.credited
        wallet = await (
            await conn.execute("SELECT balance_units FROM users WHERE id=%s", (user["id"],))
        ).fetchone()
        assert wallet["balance_units"] == quote.coins


@pytest.mark.asyncio
async def test_legacy_priced_gift_never_credits(payment_factory):
    user, _, _ = await payment_factory()
    gift_id = uuid.uuid4().hex
    async with get_conn() as conn:
        await conn.execute(
            "INSERT INTO gift_conversions(user_id,gift_id,status,price_rub) VALUES (%s,%s,'priced',1000)",
            (user["id"], gift_id),
        )
        result = await gifts.handle_gift(conn, user["id"], gift_id)
        assert result["status"] == "pending_review" and not result["credited"]
        wallet = await (
            await conn.execute("SELECT balance_units FROM users WHERE id=%s", (user["id"],))
        ).fetchone()
        assert wallet["balance_units"] == 0
