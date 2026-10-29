import random

from core.contracts.game import (
    AccountValidation,
    DeliveryResult,
    DeliveryStatus,
)


class ShellAdapter:
    MANIFEST = {"key": "shell", "type": "game", "geo": None, "version": "1", "enabled_env": None}
    game_key = "shell"
    display_name = "Shell"
    supported_currencies = ["units"]
    allowed_modifiers = ["f_win", "f_bet"]

    def __init__(self, config_path="configs/games/shell.yaml"):
        import yaml

        with open(config_path, encoding="utf-8") as f:
            self.config = yaml.safe_load(f) or {}

    def prize_catalog(self):
        return []

    def quote_prize(self, prize_id, amount_units):
        return None

    def open_session(self, user, bet_units, config):
        ball = random.randrange(3)
        return {"ball": ball, "status": "open", "bet": bet_units}

    def resolve(self, session, action, cup_index=None):
        if action != "pick":
            raise ValueError("invalid action")  # noqa: B904
        win = cup_index == session["ball"]
        payout = session["bet"] * 2.7 if win else 0
        session["status"] = "resolved"
        return {"win": win, "ball": session["ball"], "payout": payout}

    def close_session(self, session):
        return session

    def deliver(self, user_ref, prize_quote, idempotency_key):
        return DeliveryResult(f"del_{idempotency_key}", "delivered")

    def poll_delivery(self, delivery_id):
        return DeliveryStatus(delivery_id, "delivered")

    def validate_account(self, user_ref):
        return AccountValidation(True)


def register(reg):
    reg.register(ShellAdapter())
