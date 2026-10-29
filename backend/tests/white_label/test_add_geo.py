import importlib.util
import os

import yaml

from core.registry.registry import registry


def test_add_geo():
    # fake rail plugin
    base = os.path.join(os.getcwd(), "plugins", "payments", "ng_fake")
    os.makedirs(base, exist_ok=True)
    code = """
from core.contracts.payment import PaymentRailAdapter, PaymentIntent, PaymentStatus, WebhookOutcome

class NgFakeRail:
    MANIFEST = {
            "key": "ng_fake",
            "type": "payment",
            "geo": "NG",
            "version": "1",
            "enabled_env": None,
        }  # noqa: E501
    rail_key = "ng_fake"
    geo = "NG"
    methods = []
    refund_supported = False

    def create_payment(self, user_id, amount_minor, currency, idempotency_key):
        return PaymentIntent(idempotency_key, "ng_fake", amount_minor, currency, {"qr": "NG"})

    def poll_payment(self, intent_id):
        return PaymentStatus(intent_id, "pending", 0)

    def handle_webhook(self, headers, body):
        return WebhookOutcome(None, "e1", "succeeded", True)

def register(reg):
    reg.register(NgFakeRail())
"""
    with open(os.path.join(base, "plugin.py"), "w", encoding="utf-8") as f:
        f.write(code)
    spec = importlib.util.spec_from_file_location(
        "plugins.payments.ng_fake.plugin", os.path.join(base, "plugin.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.register(registry)

    # geo config
    os.makedirs("configs/geos", exist_ok=True)
    with open("configs/geos/NG.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(
            {"geo": "NG", "rails": ["ng_fake"], "min_deposit_minor": 1, "max_deposit_minor": 1000},
            f,
        )

    # tenant config add geo? We'll just check registry
    assert registry.get("payment", "ng_fake") is not None
    # cleanup
    import shutil

    shutil.rmtree(base, ignore_errors=True)
    os.remove("configs/geos/NG.yaml")
