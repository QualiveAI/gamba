"""Регрессии: PayGate без неподтверждённой оплаты, legacy Coinso вне нового pipeline."""

from decimal import Decimal

import pytest

from core.contracts.payment import PaymentError
from core.payments.quotes import compute_client_fee
from plugins.payments.paygate.adapter import PayGateAdapter


def test_fee_decimal_ceil():
    assert compute_client_fee(10000, Decimal("0")) == 0
    assert compute_client_fee(1000, Decimal("4")) == 40
    assert compute_client_fee(1, Decimal("1")) == 1
    assert compute_client_fee(810, Decimal("20")) == 162


@pytest.mark.parametrize("mode", ["disabled", "live"])
def test_paygate_no_fake_live_url(mode):
    with pytest.raises(PaymentError) as exc:
        PayGateAdapter().create_payment(1, 1000, "BRL", "a" * 32, mode=mode)
    assert exc.value.code == "provider_live_not_configured"


def test_paygate_sandbox_explicit():
    intent = PayGateAdapter().create_payment(1, 1000, "BRL", "a" * 32, mode="sandbox")
    assert intent.intent_id == "a" * 32
    assert intent.mode == "sandbox"
    assert "payment_url" not in intent.client_payload


def test_unsigned_callback_cannot_credit():
    with pytest.raises(PaymentError) as exc:
        PayGateAdapter().handle_webhook({}, b'{"intent_id":"x","value_coin":"1000","txid_in":"tx"}')
    assert exc.value.code == "paygate_unverified_callback"


def test_paygate_official_request_contract_only():
    request = PayGateAdapter.wallet_request(
        intent_id="a" * 32,
        treasury_address="0x" + "1" * 40,
        callback_base="https://merchant.invalid",
    )
    assert request["url"] == "https://api.paygate.to/control/wallet.php"
    assert "intent_id=" + "a" * 32 in request["params"]["callback"]
    link = PayGateAdapter.checkout_url(
        encrypted_address="ENC",
        amount_minor=10378,
        currency="USD",
        email="fixture@invalid.test",
        provider="moonpay",
    )
    assert "amount=103.78" in link


def test_unverified_poll_is_pending():
    polled = PayGateAdapter().poll_payment("x", "ref")
    assert polled.status == "pending" and polled.evidence is None
