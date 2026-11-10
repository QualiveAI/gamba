import pytest

from app.api.auth import TelegramAuthRequest, auth_telegram
from app.db import get_conn


@pytest.mark.asyncio
async def test_guest_auth_local():
    """Пустой initData в dev-среде = гостевой вход (браузерные проверки)."""
    res = await auth_telegram(TelegramAuthRequest(init_data=""))
    assert res.get("access_token")
    async with get_conn() as conn:
        row = await (
            await conn.execute("SELECT id, username FROM users WHERE telegram_id = 900001")
        ).fetchone()
        assert row is not None
