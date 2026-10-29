import random

from core.contracts.game import (
    AccountValidation,
    DeliveryResult,
    DeliveryStatus,
)
from core.engine.rtp.engine import effective_rtp


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

    async def open_session(self, user, bet_units, config=None, conn=None, session_ctx=None):
        if config is None:
            config = self.config
        if session_ctx is None:
            if conn is not None:
                from core.engine.rtp.behavior import session_context

                uid = user.get("id") if isinstance(user, dict) else getattr(user, "id", None)
                session_ctx = await session_context(conn, uid)
            else:
                session_ctx = {}
        base_rtp = float(self.config.get("rtp_base", 0.9))
        decision = await effective_rtp(base_rtp, self.game_key, user, session_ctx)
        mine_count = 3
        grid_size = 25
        mines = random.sample(range(grid_size), mine_count)
        is_admin = user.get("is_admin") if isinstance(user, dict) else getattr(user, "is_admin", False)
        session = {
            "mines": mines,
            "revealed": [],
            "multiplier": decision.rtp_effective,
            "status": "active",
            "grid_size": grid_size,
            "mine_count": mine_count,
            "bet": bet_units,
            "rtp_effective": decision.rtp_effective,
            "config_version_id": self.config.get("version", 1),
            "modifiers_applied": list(decision.modifiers_applied),
            "admin_override": bool(decision.override and is_admin),
        }
        if session["admin_override"]:
            session["status"] = "won"
        return session

    def resolve(self, session, action, cell=None):
        if action == "reveal":
            if session["status"] not in ("active", "won"):
                raise ValueError("not active")  # noqa: B904
            if cell in session["mines"]:
                session["status"] = "lost"
                return {"hit_mine": True}
            session["revealed"].append(cell)
            session["multiplier"] = session["rtp_effective"]
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
