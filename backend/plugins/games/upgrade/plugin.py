from core.contracts.game import AccountValidation, DeliveryResult, DeliveryStatus


class UpgradeAdapter:
    MANIFEST = {"key": "upgrade", "type": "game", "geo": None, "version": "1", "enabled_env": None}
    game_key = "upgrade"
    display_name = "Upgrade"
    supported_currencies = ["units"]
    allowed_modifiers = ["f_win", "f_bet", "f_chase"]

    def __init__(self, config_path="configs/games/upgrade.yaml"):
        import yaml

        with open(config_path, encoding="utf-8") as f:
            self.config = yaml.safe_load(f) or {}

    def prize_catalog(self):
        return []

    def quote_prize(self, prize_id, amount_units):
        return None

    def open_session(self, user, from_prize, to_prize):
        from_val = from_prize.get("value", 1)
        to_val = to_prize.get("value", 2)
        house_edge = self.config.get("house_edge_factor", 0.8)
        chance = (from_val / to_val) * house_edge
        return {"from": from_prize, "to": to_prize, "chance": chance, "status": "open"}

    def resolve(self, session, action):
        if action != "spin":
            raise ValueError("invalid action")  # noqa: B904
        import random

        roll = random.random()
        win = roll < session["chance"]
        if win:
            session["status"] = "won"
        else:
            session["status"] = "lost"
        return {"win": win, "roll": roll}

    def close_session(self, session):
        return session

    def deliver(self, user_ref, prize_quote, idempotency_key):
        return DeliveryResult(f"del_{idempotency_key}", "delivered")

    def poll_delivery(self, delivery_id):
        return DeliveryStatus(delivery_id, "delivered")

    def validate_account(self, user_ref):
        return AccountValidation(True)


def register(reg):
    reg.register(UpgradeAdapter())
