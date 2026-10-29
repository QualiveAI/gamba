import importlib.util
import os

from core.registry.registry import registry


def test_add_game():
    # create fake plugin folder
    base = os.path.join(os.getcwd(), "plugins", "games", "demo_game")
    os.makedirs(base, exist_ok=True)
    code = """
from core.contracts.game import GameAdapter, AccountValidation

class DemoGame:
    MANIFEST = {
            "key": "demo_game",
            "type": "game",
            "geo": None,
            "version": "1",
            "enabled_env": None,
        }  # noqa: E501
    game_key = "demo_game"
    display_name = "Demo Game"
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
    reg.register(DemoGame())
"""
    with open(os.path.join(base, "plugin.py"), "w", encoding="utf-8") as f:
        f.write(code)
    # load module
    spec = importlib.util.spec_from_file_location(
        "plugins.games.demo_game.plugin", os.path.join(base, "plugin.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.register(registry)
    assert registry.get("game", "demo_game") is not None
    # cleanup
    import shutil

    shutil.rmtree(base, ignore_errors=True)
