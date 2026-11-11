import pytest

from app.db import get_conn
from core.payments.events import ingest, process_event


@pytest.mark.asyncio
async def test_webhook_before_intent_stays_untrusted():
    # Старый regression принимал произвольный callback и позже превращал его в
    # деньги через link_intent. Новый контракт никогда не повышает так доверие.
    event_id = await ingest("paygate", "early-untrusted", {"status": "succeeded"})
    async with get_conn() as conn:
        result = await process_event(conn, event_id)
        assert result.status == "rejected_unverified" and not result.credited
        row = await (
            await conn.execute(
                "SELECT verification_state,outcome FROM payment_events WHERE id=%s",
                (event_id,),
            )
        ).fetchone()
        assert row["verification_state"] == "rejected"
