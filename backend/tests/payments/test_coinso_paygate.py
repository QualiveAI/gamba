"""Тесты адаптеров Coinso (крипта) и PayGate (карты) + комиссия на клиенте."""

import json

from core.api.router import compute_client_fee
from plugins.payments.coinso.adapter import CoinsoAdapter
from plugins.payments.paygate.adapter import PayGateAdapter

# ---------- комиссия на клиенте ----------


def test_fee_zero_when_percent_zero():
    assert compute_client_fee(10000, 0.0) == 0


def test_fee_rounds_up():
    # 4% от 10.00 = 0.40
    assert compute_client_fee(1000, 4.0) == 40
    # 1% от 0.01 = 0.0001 -> округление вверх до 1 minor
    assert compute_client_fee(1, 1.0) == 1


def test_adapters_have_client_fee():
    assert CoinsoAdapter().client_fee_percent() > 0
    assert PayGateAdapter().client_fee_percent() > 0


# ---------- Coinso ----------


def test_coinso_create_mock_without_keys(monkeypatch):
    monkeypatch.delenv("COINSO_SECRET_KEY", raising=False)
    monkeypatch.delenv("COINSO_PROJECT_ID", raising=False)
    intent = CoinsoAdapter().create_payment(1, 1000, "units", "idem-1")
    assert intent.intent_id == "idem-1"
    assert intent.rail == "coinso"
    assert intent.client_payload["mock"] is True
    assert intent.client_payload["payment_url"]


def test_coinso_create_real_request(monkeypatch):
    monkeypatch.setenv("COINSO_SECRET_KEY", "sk-test")
    monkeypatch.setenv("COINSO_PROJECT_ID", "123")
    monkeypatch.setenv("COINSO_USD_RUB_RATE", "90.0")
    captured = {}

    class FakeResp:
        def json(self):
            return {"success": True, "invoice_id": "AbCdEf12", "payment_url": "https://coinso.io/p/1"}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured.update({"url": url, "json": json, "headers": headers})
        return FakeResp()

    import plugins.payments.coinso.adapter as mod

    monkeypatch.setattr(mod.httpx, "post", fake_post)
    intent = CoinsoAdapter().create_payment(7, 1000, "units", "idem-2")
    # amount: 10.00 units -> 10 USD -> 900 RUB
    assert captured["json"]["amount"] == 900.0
    assert captured["json"]["custom"] == "idem-2"
    assert captured["json"]["method"] == "crypto"
    assert captured["json"]["client_telegram_id"] == "7"
    assert captured["headers"]["Authorization"] == "Bearer sk-test"
    assert intent.client_payload["invoice_id"] == "AbCdEf12"


def test_coinso_webhook_success_and_failed():
    a = CoinsoAdapter()
    ok = a.handle_webhook({}, json.dumps({"event": "payment.success", "invoice_id": "I1", "custom": "int-1"}))
    assert ok.status == "succeeded" and ok.intent_id == "int-1" and ok.event_id == "I1"
    bad = a.handle_webhook({}, json.dumps({"event": "payment.failed", "invoice_id": "I2", "custom": "int-1"}))
    assert bad.status == "failed"


# ---------- PayGate ----------


def test_paygate_create_mock_without_wallet(monkeypatch):
    monkeypatch.delenv("PAYGATE_WALLET", raising=False)
    intent = PayGateAdapter().create_payment(1, 1000, "units", "idem-3")
    assert intent.client_payload["mock"] is True
    assert intent.client_payload["expected_usdc"] == 10.0


def test_paygate_create_two_step(monkeypatch):
    monkeypatch.setenv("PAYGATE_WALLET", "0xABC")
    monkeypatch.setenv("PAYGATE_CALLBACK_BASE", "https://api.windrop.local")
    captured = {}

    class FakeResp:
        def json(self):
            return {
                "address_in": "ENC",
                "polygon_address_in": "0xTEMP",
                "callback_url": "cb",
                "ipn_token": "t",
            }

    def fake_get(url, params=None, timeout=None):
        captured.update({"url": url, "params": params})
        return FakeResp()

    import plugins.payments.paygate.adapter as mod

    monkeypatch.setattr(mod.httpx, "get", fake_get)
    intent = PayGateAdapter().create_payment(7, 1000, "units", "idem-4")
    assert "wallet.php" in captured["url"]
    assert captured["params"]["address"] == "0xABC"
    assert "intent_id=idem-4" in captured["params"]["callback"]
    assert intent.client_payload["polygon_address_in"] == "0xTEMP"
    assert "process-payment.php" in intent.client_payload["payment_url"]
    assert "amount=10.0" in intent.client_payload["payment_url"]


def test_paygate_callback_parse():
    a = PayGateAdapter()
    ok = a.handle_webhook(
        {},
        {
            "intent_id": "int-9",
            "value_coin": "10.6",
            "value_forwarded_coin": "10.0",
            "txid_in": "0xdead",
            "txid_out": "0xbeef",
            "address_in": "0xTEMP",
        },
    )
    assert ok.status == "succeeded" and ok.intent_id == "int-9" and ok.event_id == "0xdead"
    empty = a.handle_webhook({}, {"intent_id": "int-9"})
    assert empty.status == "failed"


def test_paygate_no_status_endpoint():
    st = PayGateAdapter().poll_payment("x", "ref")
    assert st.status == "pending"
