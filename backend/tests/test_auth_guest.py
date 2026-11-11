import pytest
from fastapi import HTTPException

from app.api.auth import TelegramAuthRequest, auth_telegram
from app.api.deps import get_current_user, require_admin
from app.auth.jwt import verify_claims
from app.config import settings
from app.db import get_conn


@pytest.mark.asyncio
async def test_guest_auth_requires_explicit_dev_opt_in(monkeypatch):
    monkeypatch.setattr(settings, "env", "dev")
    monkeypatch.setattr(settings, "allow_guest_auth", False)
    with pytest.raises(HTTPException) as rejected:
        await auth_telegram(TelegramAuthRequest(init_data=""))
    assert rejected.value.status_code == 401
    monkeypatch.setattr(settings, "allow_guest_auth", True)
    result = await auth_telegram(TelegramAuthRequest(init_data=""))
    claims = verify_claims(result["access_token"])
    assert claims.scope == "guest"
    async with get_conn() as conn:
        row = await (
            await conn.execute(
                "SELECT is_guest, telegram_id FROM users WHERE id = %s", (claims.user_id,)
            )
        ).fetchone()
    assert row["is_guest"] is True and row["telegram_id"] is None
    user = await get_current_user("Bearer " + result["access_token"])
    with pytest.raises(HTTPException) as rejected:
        await require_admin(user)
    assert rejected.value.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("environment", ["prod", "production", "staging", "preview", "DEV"])
async def test_guest_prod_and_unknown_environment_fail_closed(monkeypatch, environment):
    monkeypatch.setattr(settings, "allow_guest_auth", True)
    monkeypatch.setattr(settings, "env", environment)
    with pytest.raises(HTTPException) as rejected:
        await auth_telegram(TelegramAuthRequest(init_data=""))
    assert rejected.value.status_code == 401


@pytest.mark.asyncio
async def test_guest_token_revoked_after_environment_switch(monkeypatch):
    monkeypatch.setattr(settings, "env", "test")
    monkeypatch.setattr(settings, "allow_guest_auth", True)
    login = await auth_telegram(TelegramAuthRequest(init_data=""))
    monkeypatch.setattr(settings, "env", "prod")
    with pytest.raises(HTTPException) as rejected:
        await get_current_user("Bearer " + login["access_token"])
    assert rejected.value.status_code == 401


@pytest.mark.asyncio
async def test_empty_managed_login_never_falls_back_to_guest(monkeypatch):
    monkeypatch.setattr(settings, "env", "test")
    monkeypatch.setattr(settings, "allow_guest_auth", True)
    with pytest.raises(HTTPException):
        await auth_telegram(TelegramAuthRequest(init_data="", auth_bot_id=12345))
