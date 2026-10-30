import asyncio

from core.contracts.game import (
    AccountValidation,
    PrizeQuote,
    PrizeSpec,
)
from core.registry.registry import registry
from core.prizes.giftcard_pool import GiftcardPoolChannel


class RobloxAdapter:
    MANIFEST = {"key": "roblox", "type": "game", "geo": None, "version": "1", "enabled_env": None}
    game_key = "roblox"
    display_name = "Roblox"
    supported_currencies = ["units"]

    def __init__(self, conn=None):
        self.conn = conn
        self.prizes = None
        # lazy load from DB
        if conn is not None:
            self._load_prizes_from_db(conn)

    def _load_prizes_from_db(self, conn):
        import json

        async def _run():
            async with conn.cursor() as cur:
                await cur.execute("SELECT id, code, nominal_units, region FROM gift_codes WHERE status = 'available'")
                rows = await cur.fetchall()
            return [{"id": r[0], "code": r[1], "nominal_units": r[2], "region": r[3]} for r in rows]

        loop = asyncio.new_event_loop()
        try:
            self.prizes = loop.run_until_complete(_run())
        finally:
            loop.close()

    def prize_catalog(self):
        if self.prizes is None:
            return []
        return [
            PrizeSpec(p["code"], p["name"] if hasattr(p, "get") else p.get("code", "unknown"), p["nominal_units"], p.get("region"))
            for p in self.prizes
        ]

    def quote_prize(self, prize_id, amount_units):
        if self.prizes is None:
            raise ValueError("prizes not loaded")  # noqa: B904
        for p in self.prizes:
            if p["code"] == prize_id or p["id"] == prize_id:
                return PrizeQuote(prize_id, p["nominal_units"], p.get("region"))
        raise ValueError("unknown prize")  # noqa: B904

    def deliver(self, user_ref, prize_quote, idempotency_key):
        channel = registry.get("prize", "giftcard_pool")
        if channel is None:
            raise RuntimeError("giftcard_pool not registered")  # noqa: B904
        return channel.deliver(prize_quote, user_ref)

    def poll_delivery(self, delivery_id):
        channel = registry.get("prize", "giftcard_pool")
        if channel is None:
            raise RuntimeError("giftcard_pool not registered")  # noqa: B904
        return channel.verify_delivery(delivery_id)

    def validate_account(self, user_ref):
        # region consistency check placeholder logic
        return AccountValidation(valid=True, region="US")


def register(reg):
    reg.register(RobloxAdapter())