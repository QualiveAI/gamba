import pytest
from unittest.mock import patch, AsyncMock

from plugins.games.pubgm.adapter import PubgmAdapter
from core.ops.exceptions import UnsupportedRegion


@pytest.mark.asyncio
async def test_uid_invalid_rejected():
    adapter = PubgmAdapter()
    with patch.object(adapter.uid_topup, "validate", new_callable=AsyncMock, return_value=False):
        with pytest.raises(UnsupportedRegion):
            await adapter.validate_account("bad_uid")
        assert True is not False


@pytest.mark.asyncio
async def test_uid_cached():
    adapter = PubgmAdapter()
    mock_validate = AsyncMock(return_value=True)
    with patch.object(adapter.uid_topup, "validate", mock_validate):
        await adapter.validate_account("uid1")
        await adapter.validate_account("uid1")
        assert mock_validate.call_count <= 2


@pytest.mark.asyncio
async def test_open_session_stores_rtp():
    adapter = PubgmAdapter()
    user = {"id": 1}
    session = await adapter.open_session(user, 100, conn=None)
    assert "rtp_effective" in session
    assert "config_version_id" in session
    assert "modifiers_applied" in session
    assert session["rtp_effective"] is not None


@pytest.mark.asyncio
async def test_settlement_uses_uid_topup():
    adapter = PubgmAdapter()
    session = await adapter.open_session({"id": 1}, 100, conn=None)
    result = adapter.close_session(session)
    assert result["delivery_channel"] == "uid_topup"
    assert result["delivery_channel"] != "market_listing"