import random

from core.contracts.game import (
    AccountValidation,
    DeliveryResult,
    DeliveryStatus,
)
from core.engine.rtp.engine import effective_rtp


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
        roll = random.random()
        house_edge = float(self.config.get("house_edge_factor", 0.95))
        crash_point = max(1.0, (1.0 / (1.0 - roll)) * decision.rtp_effective)
        is_admin = user.get("is_admin") if isinstance(user, dict) else getattr(user, "is_admin", False)
        session = {
            "crash_point": crash_point,
            "status": "active",
            "bet": bet_units,
            "rtp_effective": decision.rtp_effective,
            "config_version_id": self.config.get("version", 1),
            "modifiers_applied": list(decision.modifiers_applied),
            "admin_override": bool(decision.override and is_admin),
        }
        if session["admin_override"]:
            session["status"] = "won"
        return session

    def resolve(self, session, action, at_multiplier=None):
        if action == "cashout":
            if at_multiplier is not None and at_multiplier >= session["crash_point"]:
                raise ValueError("cashout above crash point")  # noqa: B904
            multiplier = at_multiplier if at_multiplier is not None else session["rtp_effective"]
            return {"win": True, "multiplier": multiplier}
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
