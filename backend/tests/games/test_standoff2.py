import math
import pytest
from unittest.mock import MagicMock, patch

from plugins.games.standoff2.adapter import Standoff2Adapter


def test_gold_price_ceil():
    adapter = Standoff2Adapter()
    session1 = {"units": 800, "bet_units": 800, "skin_name": "AK Skin"}
    result1 = adapter.close_session(session1)
    assert result1["gold"] == 1000
    assert result1["gold"] != 999

    session2 = {"units": 801, "bet_units": 801, "skin_name": "AK Skin"}
    result2 = adapter.close_session(session2)
    assert result2["gold"] == 1002
    assert result2["gold"] != 1001

    # negative
    with pytest.raises(ValueError):
        adapter.close_session({"units": 0, "bet_units": 0, "skin_name": "AK Skin"})


def test_no_direct_supplier_call():
    from unittest.mock import MagicMock
    adapter = Standoff2Adapter()
    mock_supplier = MagicMock()
    # Simulate that a supplier exists but is never invoked
    s = {"units": 800, "bet_units": 800, "skin_name": "AK Skin"}
    result = adapter.close_session(s)
    # supplier should never be called
    assert mock_supplier.call_count == 0
    assert mock_supplier.called is False
    assert result["delivery_channel"] == "market_listing"


def test_produces_moderator_buy_task():
    adapter = Standoff2Adapter()
    session = {"units": 800, "bet_units": 800, "skin_name": "AK Skin"}
    result = adapter.close_session(session)
    assert result["task"] == "moderator_buy"
    assert "skin_name" in result
    assert "gold" in result
    assert result["skin_name"] is not None


def test_allowed_modifiers_present():
    adapter = Standoff2Adapter()
    assert "f_chase" in adapter.allowed_modifiers
    assert "f_chase" != "f_win"