import os

import yaml

from core.contracts.game import (
    AccountValidation,
    DeliveryResult,
    DeliveryStatus,
    PrizeQuote,
    PrizeSpec,
)
from core.engine.rtp.behavior import session_context
from core.engine.rtp.engine import effective_rtp
from plugins.prizes.uid_topup.adapter import UidTopupChannel


class PubgmAdapter:
    MANIFEST = {"key": "pubgm", "type": "game", "contract_version": 1, "enabled_env": "PUBGM_ENABLED"}
    game_key = "pubgm"
    display_name = "PUBG Mobile"
    supported_currencies = ["units"]
    allowed_modifiers = ["f_win", "f_bet"]

    def __init__(self, config_path="configs/games/pubgm.yaml"):
        self.config_path = config_path
        try:
            with open(config_path, encoding="utf-8") as f:
                self.config = yaml.safe_load(f) or {}
        except FileNotFoundError:
            self.config = {}
        self.uid_topup = UidTopupChannel()

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
            "session_id": "pubgm_session",
            "game": "pubgm",
            "bet_units": bet_units,
            "rtp_effective": decision.rtp_effective,
            "config_version_id": self.config.get("version", 1),
            "modifiers_applied": list(decision.modifiers_applied),
            "status": "active",
        }
        return session

    def resolve(self, session, action):
        return session

    def close_session(self, session):
        return {
            "session_id": session.get("session_id"),
            "game": "pubgm",
            "delivery_channel": "uid_topup",
            "status": "closed",
        }

    def deliver(self, user_ref, prize_quote, idempotency_key):
        return DeliveryResult(f"del_{idempotency_key}", "delivered")

    def poll_delivery(self, delivery_id):
        return DeliveryStatus(delivery_id, "delivered")

    async def validate_account(self, user_ref):
        uid = user_ref if isinstance(user_ref, str) else str(user_ref)
        valid = await self.uid_topup.validate(uid, "pubgm")
        if not valid:
            from core.ops.exceptions import UnsupportedRegion

            raise UnsupportedRegion("unknown uid")
        return AccountValidation(valid=True)


def register(reg):
    reg.register(PubgmAdapter())