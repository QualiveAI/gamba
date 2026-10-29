from core.contracts.prize import DeliveryResult, VerificationResult


class GiftcardPoolChannel:
    MANIFEST = {
        "key": "giftcard_pool",
        "type": "prize",
        "geo": None,
        "version": "1",
        "enabled_env": None,
    }
    channel_key = "giftcard_pool"

    def __init__(self, conn_provider=None):
        self.conn_provider = conn_provider

    def deliver(self, prize_quote, user_ref):
        # requires DB; in tests inject conn. For plugin, use sync? We'll implement async via separate?  # noqa: E501
        # Spec protocol methods may be sync. But existing code async. We'll keep sync stub using global pool.  # noqa: E501
        import asyncio

        from app.db import get_conn

        async def _run():
            async with get_conn() as conn:
                row = await (
                    await conn.execute(
                        "SELECT id, code FROM gift_codes WHERE status = 'available' AND region = %s AND nominal_units = %s ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1",  # noqa: E501
                        (
                            getattr(prize_quote, "region", None),
                            prize_quote.amount_units
                            if hasattr(prize_quote, "amount_units")
                            else prize_quote.nominal_units,
                        ),
                    )
                ).fetchone()
                if row is None:
                    from core.contracts.errors import InsufficientInventory

                    raise InsufficientInventory("empty pool")  # noqa: B904
                await conn.execute(
                    "UPDATE gift_codes SET status = 'reserved', reserved_by = NULL, reserved_at = now() WHERE id = %s",  # noqa: E501
                    (row["id"],),
                )
                await conn.commit()
                return DeliveryResult(str(row["id"]), "reserved")

        # run sync
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_run())
        finally:
            loop.close()

    def verify_delivery(self, delivery_id):
        # 24h double-check: if not activated, return to pool (handled by background)
        return VerificationResult(delivery_id, True, "ok")


def register(reg):
    reg.register(GiftcardPoolChannel())
