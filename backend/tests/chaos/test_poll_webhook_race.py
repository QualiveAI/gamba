import asyncio
import uuid

import pytest

from app.db import get_conn
from core.payments.events import ingest, process_event


@pytest.mark.asyncio
async def test_concurrent_unverified_events_do_not_credit():
    key = uuid.uuid4().hex
    first, second = await asyncio.gather(
        ingest("paygate", key, {"status": "succeeded"}, mode="sandbox"),
        ingest("paygate", key, {"status": "succeeded"}, mode="sandbox"),
    )
    assert first == second
    async with get_conn() as conn:
        result = await process_event(conn, first)
        assert result.status == "rejected_unverified" and not result.credited
        row = await (
            await conn.execute(
                "SELECT count(*) AS n FROM payment_events WHERE provider_event_id=%s",
                (key,),
            )
        ).fetchone()
        assert row["n"] == 1
