from core.contracts.game import AccountValidation


class PubgmAdapter:
    MANIFEST = {
        "key": "pubgm",
        "type": "game",
        "geo": None,
        "version": "1",
        "enabled_env": "PUBGM_ENABLED",
    }
    game_key = "pubgm"
    display_name = "PUBG Mobile"
    supported_currencies = ["units"]

    def prize_catalog(self):
        return []

    def quote_prize(self, prize_id, amount_units):
        return None

    def deliver(self, user_ref, prize_quote, idempotency_key):
        return None

    def poll_delivery(self, delivery_id):
        return None

    def validate_account(self, user_ref):
        return AccountValidation(True)


def register(reg):
    reg.register(PubgmAdapter())
