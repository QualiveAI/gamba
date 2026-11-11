from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from core.api.schemas import DepositQuoteRequest, DepositRequest
from core.contracts.payment import PaymentError
from core.payments.policy import PricingConfig, flag_enabled
from core.payments.quotes import build_quote


def config(mode="sandbox"):
    return PricingConfig(
        mode, Decimal("0.015"), Decimal("5.4"), Decimal("20"), Decimal("0.02"), 900, 1000000
    )


def actor(guest=False):
    return {
        "id": 1,
        "is_guest": guest,
        "auth_scope": "guest" if guest else "primary",
        "auth_bot_id": None if guest else 123456,
    }


def test_quote_pins_coins_brl_fee_and_version():
    now = datetime(2026, 11, 11, tzinfo=UTC)
    quote = build_quote(actor(), 100, "card", config=config(), now=now)
    assert quote.coins == 100
    assert (quote.net_brl_minor, quote.fee_brl_minor, quote.gross_brl_minor) == (810, 162, 972)
    assert quote.expires_at == now + timedelta(seconds=900)
    assert quote.public()["provider_amount_atomic"] == "972"
    assert len(quote.config_version) == 64
    changed = build_quote(actor(), 100, "card", config=replace(config(), usd_brl_rate=Decimal("6")))
    assert changed.config_version != quote.config_version
    assert quote.gross_brl_minor == 972


def test_stars_is_distinct_from_wallet_coins():
    quote = build_quote(actor(), 100, "stars", config=config())
    assert quote.provider_currency == "XTR"
    assert quote.provider_exponent == 0
    assert quote.provider_amount_atomic == 90
    assert quote.coins == 100


def test_crypto_uses_test_asset_and_no_live_address():
    quote = build_quote(actor(True), 100, "crypto", config=config())
    assert quote.chain == "sandbox" and quote.token == "TEST-USDT"
    assert quote.address.startswith("sandbox-wallet:")
    assert quote.provider_amount_atomic == 1800000
    assert quote.public()["provider_amount_atomic"] == "1800000"


def test_guest_live_and_telegram_channel_fail_closed():
    with pytest.raises(PaymentError):
        build_quote(actor(True), 100, "card", config=config("live"))
    with pytest.raises(PaymentError):
        build_quote(actor(True), 100, "card", config=config(), channel="telegram")


@pytest.mark.parametrize("coins", [0, -1, 1.1, True, "100", 1000001])
def test_integer_only_coins(coins):
    with pytest.raises(PaymentError):
        build_quote(actor(), coins, "card", config=config())


def test_legacy_api_body_and_client_prices_forbidden():
    with pytest.raises(ValidationError):
        DepositRequest(rail="paygate", amount_minor=100, currency="units")
    with pytest.raises(ValidationError):
        DepositQuoteRequest(coins=100, method="card", rate="0.01")
    with pytest.raises(ValidationError):
        DepositQuoteRequest(coins=True, method="card")


def test_disabled_default_and_strict_flags():
    assert PricingConfig.load(SimpleNamespace()).mode == "disabled"
    assert flag_enabled({"value": True}) and flag_enabled({"enabled": True})
    assert not flag_enabled({"value": "true"})
    assert not flag_enabled({"value": 1})
    assert not flag_enabled({})
