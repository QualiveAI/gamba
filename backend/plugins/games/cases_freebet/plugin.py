import random

from core.contracts.game import (
    AccountValidation,
    DeliveryResult,
    DeliveryStatus,
    PrizeQuote,
    PrizeSpec,
)
from core.engine.freebets.config import load_freebet_catalog


class CasesFreebetAdapter:
    MANIFEST = {
        "key": "cases_freebet",
        "type": "game",
        "geo": None,
        "version": "1",
        "enabled_env": None,
    }
    game_key = "cases_freebet"
    display_name = "Freebet Cases"
    supported_currencies = ["freebets"]
    currency = "freebets"
    allowed_modifiers = []

    def __init__(self, config_path="configs/games/cases.freebet.yaml"):
        self.config_path = config_path
        self.catalog = load_freebet_catalog()

    def prize_catalog(self):
        return [PrizeSpec(p.prize_id, p.name, p.nominal_units) for p in self.catalog.prizes]

    def quote_prize(self, prize_id, amount_units):
        for p in self.catalog.prizes:
            if p.prize_id == prize_id:
                return PrizeQuote(prize_id, p.nominal_units)
        raise ValueError("unknown prize")  # noqa: B904

    def open_session(self, user, bet_freebets, config):
        if bet_freebets > user.get("balance_freebets", 0):
            raise ValueError("insufficient freebets")  # noqa: B904
        prizes = self.catalog.prizes
        total_w = sum(p.weight for p in prizes)
        # pick
        r = random.random() * total_w
        acc = 0.0
        chosen = prizes[-1]
        for p in prizes:
            acc += p.weight
            if r <= acc:
                chosen = p
                break
        return {"prize": chosen, "bet": bet_freebets, "currency": "freebets"}

    def resolve(self, session, action):
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
    reg.register(CasesFreebetAdapter())
