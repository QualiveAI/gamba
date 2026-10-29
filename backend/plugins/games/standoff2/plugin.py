import math

from core.contracts.game import (
    AccountValidation,
    DeliveryResult,
    DeliveryStatus,
    PrizeQuote,
    PrizeSpec,
)


class Standoff2Adapter:
    MANIFEST = {
        "key": "standoff2",
        "type": "game",
        "geo": None,
        "version": "1",
        "enabled_env": None,
    }
    game_key = "standoff2"
    display_name = "Standoff 2"
    supported_currencies = ["units"]

    def __init__(self):
        self.catalog = [
            {"prize_id": "skin_ak", "name": "AK Skin", "market_price_units": 100},
        ]

    def prize_catalog(self):
        return [PrizeSpec(p["prize_id"], p["name"], p["market_price_units"]) for p in self.catalog]

    def quote_prize(self, prize_id, amount_units):
        for p in self.catalog:
            if p["prize_id"] == prize_id:
                return PrizeQuote(prize_id, p["market_price_units"])
        raise ValueError("unknown prize")  # noqa: B904

    def deliver(self, user_ref, prize_quote, idempotency_key):
        math.ceil(prize_quote.amount_units / 0.8)
        # create moderator_buy task in withdrawals_queue? We'll store in a list
        return DeliveryResult(f"listing_{idempotency_key}", "listed")

    def poll_delivery(self, delivery_id):
        return DeliveryStatus(delivery_id, "listed")

    def validate_account(self, user_ref):
        return AccountValidation(valid=True, message="standoff uid accepted")


def register(reg):
    reg.register(Standoff2Adapter())
