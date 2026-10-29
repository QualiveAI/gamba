import os

import yaml

from app.economy.rng import ProvablyFairRNG
from core.contracts.game import (
    AccountValidation,
    DeliveryResult,
    DeliveryStatus,
    PrizeQuote,
    PrizeSpec,
)
from core.engine.rtp.behavior import session_context
from core.engine.rtp.engine import effective_rtp


class CasesAdapter:
    MANIFEST = {"key": "cases", "type": "game", "geo": None, "version": "1", "enabled_env": None}
    game_key = "cases"
    display_name = "Cases"
    supported_currencies = ["units"]
    allowed_modifiers = ["f_win", "f_bet", "f_chase", "f_admin"]

    def __init__(self, config_path="configs/games/cases.yaml"):
        self.config_path = config_path
        with open(config_path, encoding="utf-8") as f:
            self.config = yaml.safe_load(f) or {}
        prize_path = self.config.get("prize_catalog_path", "configs/games/cases.prizes.yaml")
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

    async def open_session(self, user, bet_units, config, conn):
        # scale weights to match RTP
        rtp = await effective_rtp(0.90, "cases", user, await session_context(conn, user["id"]))
        # simple: use original weights
        total_w = sum(p.get("weight", 1) for p in self.prizes)
        # pick prize
        server_seed = os.urandom(16).hex()
        client_seed = str(user.get("id"))
        nonce = 1
        rng = ProvablyFairRNG(server_seed, client_seed, nonce)
        roll = rng.roll()
        # weighted pick
        target = roll * total_w
        acc = 0.0
        chosen = self.prizes[-1]
        for p in self.prizes:
            acc += p.get("weight", 1)
            if target <= acc:
                chosen = p
                break
        return {
            "session_id": "case_session",
            "server_seed_hash": ProvablyFairRNG.server_seed_hash(server_seed),
            "client_seed": client_seed,
            "nonce": nonce,
            "roll": roll,
            "prize": chosen,
            "rtp": rtp.rtp_effective,
            "server_seed": server_seed,
        }

    def resolve(self, session, action):
        if action != "open":
            raise ValueError("invalid action")  # noqa: B904
        return session

    def close_session(self, session):
        return session

    def deliver(self, user_ref, prize_quote, idempotency_key):
        return DeliveryResult(f"del_{idempotency_key}", "delivered")

    def poll_delivery(self, delivery_id):
        return DeliveryStatus(delivery_id, "delivered")

    def validate_account(self, user_ref):
        return AccountValidation(True)


def register(reg):
    reg.register(CasesAdapter())
