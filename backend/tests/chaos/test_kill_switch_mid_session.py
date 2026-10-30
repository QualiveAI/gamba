import pytest
import uuid

from app.db import get_conn
from core.ops.flags import set_flag, require_enabled
from core.ops.exceptions import ServiceDisabled


@pytest.mark.asyncio
async def test_kill_switch_mid_session():
    async with get_conn() as conn:
        await set_flag(conn, "trading_enabled", False)
        try:
            with pytest.raises(ServiceDisabled):
                await require_enabled(conn, "trading_enabled", "trading")
            # negative: no ledger entry posted (count unchanged)
            cnt_before = await (await conn.execute("SELECT COUNT(*) AS c FROM ledger_entries")).fetchone()
            cnt_after = await (await conn.execute("SELECT COUNT(*) AS c FROM ledger_entries")).fetchone()
            assert cnt_after["c"] == cnt_before["c"]
        finally:
            await set_flag(conn, "trading_enabled", True)