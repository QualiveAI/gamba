import yaml

from core.contracts.game import (
    AccountValidation,
    PrizeQuote,
    PrizeSpec,
)
from core.registry.registry import registry


class RobloxAdapter:
    MANIFEST = {"key": "roblox", "type": "game", "geo": None, "version": "1", "enabled_env": None}
    game_key = "roblox"
    display_name = "Roblox"
    supported_currencies = ["units"]

    def __init__(self, config_path="configs/games/roblox.yaml"):
        with open(config_path, encoding="utf-8") as f:
            self.config = yaml.safe_load(f)
        prize_path = self.config.get("prize_catalog_path", "configs/games/roblox.prizes.yaml")
        with open(prize_path, encoding="utf-8") as f:
            self.prizes = yaml.safe_load(f) or []

    def prize_catalog(self):
        return [
            PrizeSpec(p["prize_id"], p["name"], p["nominal_units"], p.get("region"))
            for p in self.prizes
        ]

    def quote_prize(self, prize_id, amount_units):
        for p in self.prizes:
            if p["prize_id"] == prize_id:
                return PrizeQuote(prize_id, p["nominal_units"], p.get("region"))
        raise ValueError("unknown prize")  # noqa: B904

    def deliver(self, user_ref, prize_quote, idempotency_key):
        channel = registry.get("prize", "giftcard_pool")
        if channel is None:
            raise RuntimeError("giftcard_pool not registered")  # noqa: B904
        return channel.deliver(prize_quote, user_ref)

    def poll_delivery(self, delivery_id):
        channel = registry.get("prize", "giftcard_pool")
        if channel is None:
            raise RuntimeError("giftcard_pool not registered")  # noqa: B904
        return channel.verify_delivery(delivery_id)

    def validate_account(self, user_ref):
        # region consistency check placeholder logic
        return AccountValidation(valid=True, region="US")


def register(reg):
    reg.register(RobloxAdapter())
