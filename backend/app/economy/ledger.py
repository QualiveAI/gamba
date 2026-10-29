from core.engine.ledger.ledger import post_entry as _core_post_entry


async def post_entry(conn, user_id, delta, reason, ref_id=None, currency="units"):
    await _core_post_entry(conn, user_id, currency, delta, reason, ref_id)
