import pytest
from fastapi import HTTPException

from app.api.wallet import my_referrals
from app.config import settings
from app.db import get_conn


@pytest.mark.asyncio
async def test_unconfigured_referral_bot_returns_safe_unavailable(monkeypatch):
    monkeypatch.setattr(settings, "bot_username", "")
    async with get_conn() as conn:
        row = await (
            await conn.execute("INSERT INTO users(telegram_id) VALUES(880099923) RETURNING id")
        ).fetchone()
    with pytest.raises(HTTPException) as error:
        await my_referrals({"id": row["id"]})
    assert error.value.status_code == 503
    assert error.value.detail == "bot_not_configured"
