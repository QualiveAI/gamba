"""Локальные signed fixtures официального Paymento API IPN, без API-вызовов."""

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from core.contracts.payment import PaymentError
from plugins.payments.paymento.adapter import PaymentoAdapter, parse_json, verify_ipn_signature

SECRET = "test-only-secret"
RAW = b'{"Token":"token","PaymentId":"42","OrderId":"order","OrderStatus":7,"AdditionalData":[]}'


def signed(body=RAW):
    return {
        "X-HMAC-SHA256-Signature": hmac.new(SECRET.encode(), body, hashlib.sha256)
        .hexdigest()
        .upper()
    }


def payment():
    return SimpleNamespace(
        id="order",
        provider_ref="token",
        mode="live",
        rail="paymento",
        provider_amount_atomic=1000000,
        provider_currency="USDT",
        provider_exponent=6,
        chain="Tron",
        token="contract",
        address="T-fixture",
    )


def verified_response():
    return {
        "success": True,
        "body": {
            "token": "token",
            "orderId": "order",
            "orderStatus": 8,
            "settlement": {
                "expectedCryptoAmount": "1.000000",
                "receivedCryptoAmount": "1.000000",
                "asset": "USDT",
                "network": "Tron",
                "contractAddress": "contract",
                "toAddress": "T-fixture",
                "transactions": [
                    {
                        "status": 3,
                        "txHash": "tx-1",
                        "amount": "1.000000",
                        "confirmations": 19,
                        "requiredConfirmations": 19,
                        "toAddress": "T-fixture",
                        "confirmedAt": "2026-11-11T00:00:00Z",
                    }
                ],
            },
        },
    }


def test_official_raw_hmac_and_mutation():
    assert verify_ipn_signature(signed(), RAW, SECRET)
    assert not verify_ipn_signature(signed(), RAW + b" ", SECRET)
    assert not verify_ipn_signature({}, RAW, SECRET)
    assert not verify_ipn_signature(signed(), RAW, "other")
    callback = PaymentoAdapter(secret_key=SECRET).authenticate_webhook(signed(), RAW)
    assert callback.reference == "order" and callback.mode == "live"
    outcome = PaymentoAdapter(secret_key=SECRET).handle_webhook(signed(), RAW)
    assert outcome.evidence is None and not outcome.credited and outcome.status == "pending"


def test_reject_different_payment_links_signature():
    assert not verify_ipn_signature(
        {"X-Paymento-Signature": signed()["X-HMAC-SHA256-Signature"]}, RAW, SECRET
    )


def test_paymento_parser_exact_decimals_and_duplicate_keys():
    parsed = parse_json(b'{"amount":0.000001}')
    assert parsed["amount"] == Decimal("0.000001")
    with pytest.raises(PaymentError):
        parse_json(b'{"Token":"a","Token":"b"}')


def test_authoritative_verify_checks_money_destination_confirmations():
    result = PaymentoAdapter.verify_response(
        verified_response(), intent=payment(), event_id="event", token="token"
    )
    assert (
        result.status == "succeeded"
        and result.amount_atomic == 1000000
        and result.source == "provider_poll"
    )
    for field, value in (
        ("receivedCryptoAmount", "0.999999"),
        ("toAddress", "other"),
        ("network", "Ethereum"),
        ("contractAddress", "other"),
        ("asset", "USDC"),
    ):
        body = verified_response()
        body["body"]["settlement"][field] = value
        with pytest.raises(PaymentError):
            PaymentoAdapter.verify_response(body, intent=payment(), event_id="event", token="token")
    body = verified_response()
    body["body"]["settlement"]["transactions"][0]["confirmations"] = 1
    with pytest.raises(PaymentError):
        PaymentoAdapter.verify_response(body, intent=payment(), event_id="event", token="token")


@pytest.mark.parametrize("status", [0, 1, 2, 3, 4, 5, 7, 9, 10])
def test_non_approved_never_becomes_paid(status):
    body = verified_response()
    body["body"]["orderStatus"] = status
    body["success"] = False
    with pytest.raises(PaymentError) as exc:
        PaymentoAdapter.verify_response(body, intent=payment(), event_id="event", token="token")
    assert exc.value.code == "paymento_not_approved"


@pytest.mark.asyncio
async def test_verify_transport_mock_requires_authenticated_durable_event():
    calls = []

    class FakeTransport:
        async def post_json(self, url, *, headers, payload):
            calls.append((url, headers, payload))
            return json.dumps(verified_response()).encode()

    adapter = PaymentoAdapter(secret_key=SECRET, api_key="fake-key", transport=FakeTransport())
    event = {
        "authenticated": True,
        "verification_source": "signed_webhook",
        "rail": "paymento",
        "mode": "live",
        "raw_body": RAW,
        "provider_event_id": "event",
    }
    result = await adapter.reconcile_event(event, payment())
    assert result.reference == "order"
    assert calls[0][0] == "https://api.paymento.io/v1/payment/verify"
    assert calls[0][2] == {"token": "token"}
    event["authenticated"] = False
    with pytest.raises(PaymentError):
        await adapter.reconcile_event(event, payment())
    assert len(calls) == 1


def test_request_contract_uses_canonical_order_and_decimal_string():
    request = PaymentoAdapter.request_contract(
        intent_id="a" * 32,
        amount_atomic=972,
        currency="BRL",
        exponent=2,
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )
    assert request["json"]["orderId"] == "a" * 32
    assert request["json"]["fiatAmount"] == "9.72"
