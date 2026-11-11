"""Неоднозначные legacy withdrawals нельзя автоматически проверять, выдавать или возвращать."""

import uuid

import pytest

from app.db import get_conn
from app.giftcards import service as cards
from app.giftcards import verify
from app.giftcards.security import GiftCardError
from app.withdrawals import service


async def setup_legacy(conn, *, status="approved", amount=1_000, nominal=800, fee=200):
    user = await (
        await conn.execute(
            "INSERT INTO users (telegram_id, region) VALUES (%s, 'BR') RETURNING id",
            (20_000_000_000 + uuid.uuid4().int % 1_000_000_000_000,),
        )
    ).fetchone()
    card = await (
        await conn.execute(
            "INSERT INTO gift_codes (code, region, nominal_units, status, reserved_by, "
            "reserved_at, issued_at) VALUES (%s, 'BR', %s, 'issued', %s, "
            "now() - interval '30 days', now() - interval '30 days') RETURNING id",
            ("TEST-ONLY-LEGACY-" + uuid.uuid4().hex, nominal, user["id"]),
        )
    ).fetchone()
    order = await (
        await conn.execute(
            "INSERT INTO withdrawals (user_id, amount_units, region, status, code_id, fee_units) "
            "VALUES (%s, %s, 'BR', %s, %s, %s) RETURNING id",
            (user["id"], amount, status, card["id"], fee),
        )
    ).fetchone()
    return user["id"], order["id"], card["id"]


@pytest.mark.parametrize(
    "status", ["pending", "approved", "pending_supplier", "manual_review", "issued"]
)
async def test_finalize_legacy_is_read_only_manual_review(status, monkeypatch):
    async def forbidden_supplier_call(*args, **kwargs):
        raise AssertionError("Старые заявки не должны вызывать поставщика.")

    monkeypatch.setattr("core.delivery.router.verify_delivery", forbidden_supplier_call)
    async with get_conn() as conn:
        async with conn.transaction():
            _, withdrawal_id, card_id = await setup_legacy(conn, status=status)
        result = await service.finalize(conn, withdrawal_id)
        assert result == {"status": "manual_review", "legacy": True, "read_only": True}
        stored = await (
            await conn.execute(
                "SELECT status, fee_units FROM withdrawals WHERE id = %s", (withdrawal_id,)
            )
        ).fetchone()
        card = await (
            await conn.execute("SELECT status FROM gift_codes WHERE id = %s", (card_id,))
        ).fetchone()
    assert stored == {"status": status, "fee_units": 200}
    assert card["status"] == "issued"


async def test_legacy_fee_or_matching_amount_is_not_an_operator_sku_mapping():
    async with get_conn() as conn:
        async with conn.transaction():
            _, withdrawal_id, _ = await setup_legacy(conn, amount=1_000, nominal=1_000, fee=0)
        assert (await service.finalize(conn, withdrawal_id))["status"] == "manual_review"


async def test_legacy_mutations_are_closed_and_never_refund_or_return_stock():
    async with get_conn() as conn:
        async with conn.transaction():
            user_id, withdrawal_id, card_id = await setup_legacy(conn, status="pending")
        calls = [
            lambda: service.approve(conn, withdrawal_id),
            lambda: service.reject(conn, withdrawal_id, "rejected"),
            lambda: service.unfreeze(conn, withdrawal_id),
            lambda: cards.issue(conn, card_id),
            lambda: service.request(conn, {"id": user_id}, 1_000, "BR"),
        ]
        for call in calls:
            with pytest.raises(GiftCardError) as error:
                await call()
            assert error.value.code == "legacy_read_only"
        row = await (
            await conn.execute("SELECT status FROM withdrawals WHERE id = %s", (withdrawal_id,))
        ).fetchone()
        ledger = await (
            await conn.execute(
                "SELECT COUNT(*) AS c FROM ledger_entries WHERE user_id = %s", (user_id,)
            )
        ).fetchone()
    assert row["status"] == "pending"
    assert ledger["c"] == 0


async def test_expired_reservation_and_old_verifier_never_recycle_assigned_legacy_code():
    async with get_conn() as conn:
        async with conn.transaction():
            _, _, card_id = await setup_legacy(conn)
        assert await cards.release_expired(conn) == 0
        assert (await verify.run_verification(conn, card_id))["status"] == "manual_review"
        await verify.schedule_verify(conn, card_id)
        card = await (
            await conn.execute("SELECT status FROM gift_codes WHERE id = %s", (card_id,))
        ).fetchone()
    assert card["status"] == "issued"
