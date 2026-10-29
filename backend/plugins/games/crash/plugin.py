import random

from core.contracts.game import (
    AccountValidation,
    DeliveryResult,
    DeliveryStatus,
)


class CrashAdapter:
    MANIFEST = {"key": "crash", "type": "game", "geo": None, "version": "1", "enabled_env": None}
    game_key = "crash"
    display_name = "Crash"
    supported_currencies = ["units"]
    allowed_modifiers = ["f_win", "f_bet"]

    def __init__(self, config_path="configs/games/crash.yaml"):
        import yaml

        with open(config_path, encoding="utf-8") as f:
            self.config = yaml.safe_load(f) or {}

    def prize_catalog(self):
        return []

    def quote_prize(self, prize_id, amount_units):
        return None

    def open_session(self, user, bet_units, config):
        roll = random.random()
        crash_point = max(1.0, (1.0 / (1.0 - roll)) * 0.95)
        return {"crash_point": crash_point, "status": "active", "bet": bet_units}

    def resolve(self, session, action, at_multiplier=None):
        if action == "cashout":
            if at_multiplier >= session["crash_point"]:
                raise ValueError("cashout above crash point")  # noqa: B904
            return {"win": True, "multiplier": at_multiplier}
        if action == "wait":
            return {"multiplier": session["crash_point"]}
        raise ValueError("invalid action")  # noqa: B904

    def close_session(self, session):
        return session

    def deliver(self, user_ref, prize_quote, idempotency_key):
        return DeliveryResult(f"del_{idempotency_key}", "delivered")

    def poll_delivery(self, delivery_id):
        return DeliveryStatus(delivery_id, "delivered")

    def validate_account(self, user_ref):
        return AccountValidation(True)


def register(reg):
    reg.register(CrashAdapter())
