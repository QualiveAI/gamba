"""Прямые USDT TRC-20: уникальная сумма, казна обязательна, зачисление по сети."""

import pytest

from app.bot.users import ensure_telegram_user
from app.config import settings
from app.db import get_conn
from app.payments import onchain
from core.contracts.payment import PaymentError
from core.payments.intents import create_intent as create_payment_intent
from core.payments.quotes import build_quote, create_quote


def _user(uid: int = 890001) -> dict:
    return {
        "id": uid,
        "auth_scope": "primary",
        "is_guest": False,
        "auth_bot_id": 9182038651,
        "telegram_id": 8900001,
        "username": "tester",
    }


@pytest.fixture(autouse=True)
async def _flags():
    """Session-БД чистится: включаем флаги оплат для crypto."""
    async with get_conn() as conn, conn.transaction():
        for key in ("deposits_enabled", "payments_crypto_enabled"):
            await conn.execute(
                "INSERT INTO system_config (key, value) VALUES (%s, %s) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                (key, '{"value": true}'),
            )


@pytest.fixture(autouse=True)
def _treasury(monkeypatch):
    monkeypatch.setattr(settings, "payments_mode", "live")
    monkeypatch.setattr(settings, "treasury_asset", "USDT")
    monkeypatch.setattr(settings, "treasury_network", "tron")
    monkeypatch.setattr(
        settings, "treasury_address", "TXExampleTreasuryAddressForTests0001"
    )


def test_crypto_quote_uses_treasury_and_unique_tail():
    user = _user()
    quote = build_quote(user, 1000, "crypto", now=None)
    assert quote.provider_currency == "USDT"
    assert quote.provider_exponent == 6
    assert quote.chain == "tron"
    assert quote.token == "USDT"
    assert quote.address == "TXExampleTreasuryAddressForTests0001"
    # Хвост суммы — из id котировки: две котировки дают разные суммы.
    assert quote.provider_amount_atomic % 10_000 == int(quote.id, 16) % 10_000
    other = build_quote(user, 1000, "crypto", now=None)
    assert other.provider_amount_atomic != quote.provider_amount_atomic


def test_crypto_quote_requires_treasury(monkeypatch):
    monkeypatch.setattr(settings, "treasury_address", "")
    with pytest.raises(PaymentError) as exc:
        build_quote(_user(), 1000, "crypto", now=None)
    assert exc.value.code == "crypto_destination_not_configured"


@pytest.mark.asyncio
async def test_scan_credits_and_is_idempotent(monkeypatch):
    user = _user(890002)
    async with get_conn() as conn, conn.transaction():
        await ensure_telegram_user(conn, telegram_id=8900002, username="tester")
        user = dict(
            await (
                await conn.execute("SELECT * FROM users WHERE telegram_id = %s", (8900002,))
            ).fetchone()
        )
        user["auth_scope"] = "primary"
        user["is_guest"] = False
        user["auth_bot_id"] = 9182038651
        quote = await create_quote(conn, user=user, coins=1000, method="crypto")
        intent = await create_payment_intent(
            conn=conn,
            user=user,
            tenant="default",
            quote_id=quote.id,
            idempotency_key=f"test-onchain-{int(quote.id, 16)}",
        )
    assert intent.status == "pending"
    txid = "9f3a" + "0" * 60
    async def fake_transfers(address, timeout=None):
        return [{"txid": txid, "value_atoms": int(intent.provider_amount_atomic)}]

    monkeypatch.setattr(onchain, "fetch_recent_usdt_transfers", fake_transfers)
    credited = await onchain.scan_onchain_deposits()
    assert credited == 1
    async with get_conn() as conn:
        row = await (
            await conn.execute(
                "SELECT status, provider_ref FROM payment_intents WHERE id = %s", (intent.id,)
            )
        ).fetchone()
        assert row["status"] == "succeeded"
        balance = await (
            await conn.execute(
                "SELECT balance_units FROM users WHERE id = %s", (user["id"],)
            )
        ).fetchone()
        assert int(balance["balance_units"]) == 1000
    # Повторный проход: тот же txid не начисляет второй раз.
    credited_again = await onchain.scan_onchain_deposits()
    assert credited_again == 0


@pytest.mark.asyncio
async def test_scan_ignores_wrong_amount(monkeypatch):
    user = _user(890003)
    async with get_conn() as conn, conn.transaction():
        await ensure_telegram_user(conn, telegram_id=8900003, username="tester")
        user = dict(
            await (
                await conn.execute("SELECT * FROM users WHERE telegram_id = %s", (8900003,))
            ).fetchone()
        )
        user["auth_scope"] = "primary"
        user["is_guest"] = False
        user["auth_bot_id"] = 9182038651
        quote = await create_quote(conn, user=user, coins=1000, method="crypto")
        await create_payment_intent(
            conn=conn,
            user=user,
            tenant="default",
            quote_id=quote.id,
            idempotency_key=f"test-onchain-{int(quote.id, 16)}",
        )
    # Платёж другой суммой (не хвост котировки) не зачисляется.
    async def fake_transfers(address, timeout=None):
        return [{"txid": "a" * 64, "value_atoms": 123456789}]

    monkeypatch.setattr(onchain, "fetch_recent_usdt_transfers", fake_transfers)
    assert await onchain.scan_onchain_deposits() == 0