import random

from core.contracts.game import (
    AccountValidation,
    DeliveryResult,
    DeliveryStatus,
)


class MinesAdapter:
    MANIFEST = {"key": "mines", "type": "game", "geo": None, "version": "1", "enabled_env": None}
    game_key = "mines"
    display_name = "Mines"
    supported_currencies = ["units"]
    allowed_modifiers = ["f_win", "f_bet"]

    def __init__(self, config_path="configs/games/mines.yaml"):
        import yaml

        with open(config_path, encoding="utf-8") as f:
            self.config = yaml.safe_load(f) or {}

    def prize_catalog(self):
        return []

    def quote_prize(self, prize_id, amount_units):
        return None

    def open_session(self, user, bet_units, config):
        mine_count = 3
        grid_size = 25
        mines = random.sample(range(grid_size), mine_count)
        return {
            "mines": mines,
            "revealed": [],
            "multiplier": 1.0,
            "status": "active",
            "grid_size": grid_size,
            "mine_count": mine_count,
            "bet": bet_units,
        }

    def resolve(self, session, action, cell=None):
        if action == "reveal":
            if session["status"] != "active":
                raise ValueError("not active")  # noqa: B904
            if cell in session["mines"]:
                session["status"] = "lost"
                return {"hit_mine": True}
            session["revealed"].append(cell)
            # next-move bias
            bet = session["bet"]
            threshold = 100
            if bet > threshold:
                # re-place mines among unrevealed cells
                available = [c for c in range(session["grid_size"]) if c not in session["revealed"]]
                if len(available) >= session["mine_count"]:
                    session["mines"] = random.sample(available, session["mine_count"])
            session["multiplier"] = 1.0 + 0.2 * len(session["revealed"])
            return {"hit_mine": False, "multiplier": session["multiplier"]}
        if action == "cashout":
            session["status"] = "cashed_out"
            return {"payout_multiplier": session["multiplier"]}
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
    reg.register(MinesAdapter())
