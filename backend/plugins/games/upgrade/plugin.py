from core.contracts.game import AccountValidation, DeliveryResult, DeliveryStatus
from core.engine.rtp.engine import effective_rtp


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

    async def open_session(self, user, from_prize, to_prize, config=None, conn=None, session_ctx=None):
        if config is None:
            config = self.config
        if session_ctx is None:
            if conn is not None:
                from core.engine.rtp.behavior import session_context

                uid = user.get("id") if isinstance(user, dict) else getattr(user, "id", None)
                session_ctx = await session_context(conn, uid)
            else:
                session_ctx = {}
        from_val = from_prize.get("value", 1)
        to_val = to_prize.get("value", 2)
        base_rtp = float(self.config.get("rtp_base", 0.8))
        decision = await effective_rtp(base_rtp, self.game_key, user, session_ctx)
        house_edge = float(self.config.get("house_edge_factor", 0.8))
        chance = (from_val / to_val) * house_edge * decision.rtp_effective
        is_admin = user.get("is_admin") if isinstance(user, dict) else getattr(user, "is_admin", False)
        session = {
            "from": from_prize,
            "to": to_prize,
            "chance": chance,
            "status": "open",
            "rtp_effective": decision.rtp_effective,
            "config_version_id": self.config.get("version", 1),
            "modifiers_applied": list(decision.modifiers_applied),
            "admin_override": bool(decision.override and is_admin),
        }
        if session["admin_override"]:
            session["status"] = "won"
        return session

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
