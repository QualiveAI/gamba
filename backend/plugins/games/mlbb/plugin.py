from core.contracts.game import AccountValidation


class MlbbAdapter:
    MANIFEST = {
        "key": "mlbb",
        "type": "game",
        "geo": None,
        "version": "1",
        "enabled_env": "MLBB_ENABLED",
    }
    game_key = "mlbb"
    display_name = "Mobile Legends"
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
    reg.register(MlbbAdapter())
