import asyncio

import pytest
from unittest.mock import AsyncMock, patch

from core.engine.rtp.engine import RtpDecision
from plugins.games.crash.plugin import CrashAdapter


@pytest.mark.asyncio
async def test_empirical_matches_decision():
    decision = RtpDecision(0.80, ["f_chase"], "ok", False)
    adapter = CrashAdapter()
    user = {"id": 1, "is_admin": False}
    with patch("plugins.games.crash.plugin.effective_rtp", new=AsyncMock(return_value=decision)):
        sessions = [await adapter.open_session(user, 100, {}) for _ in range(2000)]
    assert all(s["rtp_effective"] == 0.80 for s in sessions)
    assert all(s["config_version_id"] is not None for s in sessions)
    assert all(s["modifiers_applied"] == ["f_chase"] for s in sessions)


@pytest.mark.asyncio
async def test_admin_override():
    decision = RtpDecision(1.0, ["f_admin"], "admin", True)
    adapter = CrashAdapter()
    user = {"id": 1, "is_admin": True}
    with patch("plugins.games.crash.plugin.effective_rtp", new=AsyncMock(return_value=decision)):
        sessions = [await adapter.open_session(user, 100, {}) for _ in range(100)]
    assert all(s["admin_override"] is True for s in sessions)


@pytest.mark.asyncio
async def test_override_ignored_for_non_admin():
    decision = RtpDecision(0.80, ["f_chase"], "ok", True)
    adapter = CrashAdapter()
    user = {"id": 1, "is_admin": False}
    with patch("plugins.games.crash.plugin.effective_rtp", new=AsyncMock(return_value=decision)):
        sessions = [await adapter.open_session(user, 100, {}) for _ in range(1000)]
    assert all(s["admin_override"] is False for s in sessions)
    assert all(s["rtp_effective"] == 0.80 for s in sessions)

