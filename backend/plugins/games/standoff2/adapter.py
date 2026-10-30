import math

from core.contracts.game import (
    AccountValidation,
    DeliveryResult,
    DeliveryStatus,
    PrizeQuote,
    PrizeSpec,
)
from core.engine.rtp.behavior import session_context
from core.engine.rtp.engine import effective_rtp


class Standoff2Adapter:
    MANIFEST = {"key": "standoff2", "type": "game", "contract_version": 1, "enabled_env": None}
    game_key = "standoff2"
    display_name = "Standoff 2"
    supported_currencies = ["units"]
    allowed_modifiers = ["f_win", "f_bet", "f_chase"]

    def __init__(self, config_path="configs/games/standoff2.yaml"):
        self.config_path = config_path
        try:
            import yaml

            with open(config_path, encoding="utf-8") as f:
                self.config = yaml.safe_load(f) or {}
        except FileNotFoundError:
            self.config = {}

    def prize_catalog(self):
        return []

    def quote_prize(self, prize_id, amount_units):
        return None

    async def open_session(self, user, bet_units, config=None, conn=None, session_ctx=None):
        if config is None:
            config = self.config
        if session_ctx is None:
            if conn is not None:
                from core.engine.rtp.behavior import session_context as sc

                uid = user.get("id") if isinstance(user, dict) else getattr(user, "id", None)
                session_ctx = await sc(conn, uid)
            else:
                session_ctx = {}
        base_rtp = float(self.config.get("rtp_base", 0.90))
        decision = await effective_rtp(base_rtp, self.game_key, user, session_ctx)
        session = {
            "session_id": "standoff2_session",
            "game": "standoff2",
            "bet_units": bet_units,
            "units": bet_units,
            "skin_name": self.config.get("skin_name", "AK Skin"),
            "rtp_effective": decision.rtp_effective,
            "config_version_id": self.config.get("version", 1),
            "modifiers_applied": list(decision.modifiers_applied),
            "status": "active",
        }
        return session

    def resolve(self, session, action):
        return session

    def close_session(self, session):
        units = session.get("units", session.get("bet_units", 0))
        if units <= 0:
            raise ValueError("units must be > 0")
        gold = math.ceil(units / 0.8)
        return {
            "session_id": session.get("session_id"),
            "game": "standoff2",
            "delivery_channel": "market_listing",
            "task": "moderator_buy",
            "skin_name": session.get("skin_name", "AK Skin"),
            "gold": gold,
            "units": units,
        }

    def deliver(self, user_ref, prize_quote, idempotency_key):
        # No supplier call - only produces task
        return DeliveryResult(f"listing_{idempotency_key}", "listed")

    def poll_delivery(self, delivery_id):
        return DeliveryStatus(delivery_id, "listed")

    def validate_account(self, user_ref):
        return AccountValidation(valid=True, message="standoff uid accepted")


def register(reg):
    reg.register(Standoff2Adapter())