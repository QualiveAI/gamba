import pytest

from app.db import get_conn
from core.ops.exceptions import ServiceDisabled
from core.ops.flags import set_flag, require_enabled


@pytest.mark.asyncio
async def test_service_disabled_raised():
    async with get_conn() as conn:
        await set_flag(conn, "trading_enabled", False)
        with pytest.raises(ServiceDisabled):
            await require_enabled(conn, "trading_enabled", "trading")
        await set_flag(conn, "trading_enabled", True)
        # negative: enabled does not raise
        await require_enabled(conn, "trading_enabled", "trading")
        assert True