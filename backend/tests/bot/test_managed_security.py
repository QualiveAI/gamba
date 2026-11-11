import hashlib
import hmac
import json
import sys
import time
from urllib.parse import urlencode

import pytest
from fastapi import HTTPException

from app.api.auth import TelegramAuthRequest, auth_telegram
from app.api.deps import get_current_user, require_admin
from app.auth.jwt import issue_token, verify_claims
from app.bot.inbox import event_allowed, save_update
from app.bot.pool import (
    activate_managed,
    create_intent,
    get_bot,
    observe_managed_update,
    revoke_managed,
    stage_managed_credentials,
)
from app.bot.security import BotSecurityError
from app.bot.users import ensure_telegram_user
from app.config import settings
from app.db import get_conn

TOKEN = "800000201:synthetic_managed_token_not_for_telegram"
OWNER = 800000301
BOT_ID = 800000201


@pytest.fixture(autouse=True)
def unique_identity(request, monkeypatch):
    # Общая safe test DB очищается на session, поэтому каждому тесту отдельная bot identity.
    offset = (
        int.from_bytes(hashlib.sha256(request.node.name.encode()).digest()[:4], "big") % 1_000_000
    )
    module = sys.modules[__name__]
    monkeypatch.setattr(module, "BOT_ID", 810000000 + offset)
    monkeypatch.setattr(module, "OWNER", 820000000 + offset)
    monkeypatch.setattr(
        module, "TOKEN", f"{810000000 + offset}:synthetic_managed_token_not_for_telegram"
    )


def signed_init_data(user_id: int, token: str | None = None) -> str:
    token = token or TOKEN
    data = {
        "auth_date": str(int(time.time())),
        "query_id": "synthetic-query",
        "user": json.dumps({"id": user_id, "username": "synthetic_owner"}),
    }
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(
        secret, "\n".join(f"{k}={v}" for k, v in sorted(data.items())).encode(), hashlib.sha256
    ).hexdigest()
    return urlencode(data)


async def provision(main_registry, update_id: int):
    async with get_conn() as conn, conn.transaction():
        user = await ensure_telegram_user(conn, telegram_id=OWNER, username="synthetic_owner")
        await create_intent(conn, user=user)
        observed = await observe_managed_update(
            conn,
            source=main_registry,
            update={
                "update_id": update_id,
                "managed_bot": {
                    "user": {"id": OWNER, "is_bot": False},
                    "bot": {"id": BOT_ID, "is_bot": True, "username": "personal_test_bot"},
                },
            },
        )
        staged = await stage_managed_credentials(
            conn,
            observed=observed,
            token=TOKEN,
            me={"id": BOT_ID, "is_bot": True, "username": "personal_test_bot"},
        )
        await activate_managed(conn, staged)
        bot = await get_bot(conn, BOT_ID)
    return user, dict(bot)


@pytest.mark.asyncio
async def test_managed_signed_other_user_and_admin_rejected(main_registry, monkeypatch):
    user, bot = await provision(main_registry, 10001)
    monkeypatch.setattr(settings, "admin_telegram_ids", f"{OWNER},{OWNER + 999}")
    for malicious_id in (OWNER + 1, OWNER + 999):
        with pytest.raises(HTTPException) as rejected:
            await auth_telegram(
                TelegramAuthRequest(init_data=signed_init_data(malicious_id), auth_bot_id=BOT_ID)
            )
        assert rejected.value.status_code == 401
    login = await auth_telegram(
        TelegramAuthRequest(init_data=signed_init_data(OWNER), auth_bot_id=BOT_ID)
    )
    claims = verify_claims(login["access_token"])
    assert (claims.user_id, claims.scope, claims.auth_bot_id) == (user["id"], "managed", BOT_ID)
    assert claims.owner_telegram_id == OWNER
    assert claims.credential_version == bot["credential_version"]
    authenticated = await get_current_user("Bearer " + login["access_token"])
    assert authenticated["auth_owner_telegram_id"] == OWNER
    with pytest.raises(HTTPException) as rejected:
        await require_admin(authenticated)
    assert rejected.value.status_code == 403
    with pytest.raises(HTTPException):
        await auth_telegram(TelegramAuthRequest(init_data=signed_init_data(OWNER)))


@pytest.mark.asyncio
async def test_owner_change_revokes_before_worker_without_account_transfer(main_registry):
    user, bot = await provision(main_registry, 10002)
    session = issue_token(
        user["id"],
        scope="managed",
        auth_bot_id=BOT_ID,
        owner_telegram_id=OWNER,
        credential_version=bot["credential_version"],
    )
    new_owner = OWNER + 10
    async with get_conn() as conn, conn.transaction():
        await save_update(
            conn,
            bot=main_registry,
            update={
                "update_id": 10003,
                "managed_bot": {
                    "user": {"id": new_owner, "is_bot": False},
                    "bot": {"id": BOT_ID, "is_bot": True, "username": "personal_test_bot"},
                },
            },
        )
    async with get_conn() as conn:
        changed = await get_bot(conn, BOT_ID)
        old_user = await (
            await conn.execute("SELECT * FROM users WHERE id = %s", (user["id"],))
        ).fetchone()
        new_user = await (
            await conn.execute("SELECT id FROM users WHERE telegram_id = %s", (new_owner,))
        ).fetchone()
    assert changed["status"] == "revoked" and changed["token_encrypted"] is None
    assert changed["owner_telegram_id"] == new_owner and changed["owner_user_id"] is None
    assert changed["credential_version"] > bot["credential_version"]
    assert old_user["telegram_id"] == OWNER and old_user["balance_units"] == user["balance_units"]
    assert new_user is None
    with pytest.raises(HTTPException):
        await get_current_user("Bearer " + session)


@pytest.mark.asyncio
async def test_rotation_invalidates_session_and_requires_pending_intent(main_registry):
    # Новый explicit opt-in обязателен для повторного подключения отозванного бота.
    async with get_conn() as conn, conn.transaction():
        await observe_managed_update(
            conn,
            source=main_registry,
            update={
                "update_id": 10004,
                "managed_bot": {
                    "user": {"id": OWNER, "is_bot": False},
                    "bot": {"id": BOT_ID, "is_bot": True},
                },
            },
        )
    user, bot = await provision(main_registry, 10005)
    session = issue_token(
        user["id"],
        scope="managed",
        auth_bot_id=BOT_ID,
        owner_telegram_id=OWNER,
        credential_version=bot["credential_version"],
    )
    async with get_conn() as conn, conn.transaction():
        await revoke_managed(conn, bot_id=BOT_ID, owner_telegram_id=OWNER)
    with pytest.raises(HTTPException):
        await get_current_user("Bearer " + session)
    async with get_conn() as conn, conn.transaction():
        observed = await observe_managed_update(
            conn,
            source=main_registry,
            update={
                "update_id": 10006,
                "managed_bot": {
                    "user": {"id": OWNER, "is_bot": False},
                    "bot": {"id": BOT_ID, "is_bot": True},
                },
            },
        )
        assert observed["pending_intent_id"] is None
        with pytest.raises(BotSecurityError):
            await stage_managed_credentials(
                conn, observed=observed, token=TOKEN, me={"id": BOT_ID, "is_bot": True}
            )


@pytest.mark.asyncio
async def test_getme_identity_mismatch_and_untrusted_manager(main_registry):
    user, bot = await provision(main_registry, 10007)
    async with get_conn() as conn, conn.transaction():
        with pytest.raises(BotSecurityError):
            await observe_managed_update(conn, source=bot, update={"managed_bot": {}})
        await create_intent(conn, user=user, bot_id=BOT_ID)
        observed = await observe_managed_update(
            conn,
            source=main_registry,
            update={
                "update_id": 10008,
                "managed_bot": {
                    "user": {"id": OWNER, "is_bot": False},
                    "bot": {"id": BOT_ID, "is_bot": True},
                },
            },
        )
        with pytest.raises(BotSecurityError):
            await stage_managed_credentials(
                conn,
                observed=observed,
                token=TOKEN,
                me={"id": BOT_ID + 1, "is_bot": True},
            )


def test_managed_foreign_message_and_merchant_events_fail_closed():
    bot = {
        "bot_id": BOT_ID,
        "kind": "managed",
        "status": "active",
        "owner_telegram_id": OWNER,
        "owner_user_id": 10,
        "token_encrypted": "encrypted",
    }
    message = {
        "from": {"id": OWNER, "is_bot": False},
        "chat": {"type": "private", "id": OWNER},
        "text": "/menu",
    }
    assert event_allowed(bot, {"update_id": 1, "message": message})
    assert not event_allowed(
        bot,
        {"update_id": 2, "message": dict(message, **{"from": {"id": OWNER + 1, "is_bot": False}})},
    )
    assert not event_allowed(bot, {"update_id": 3, "message": dict(message, successful_payment={})})
    assert not event_allowed(bot, {"update_id": 4, "pre_checkout_query": {"from": {"id": OWNER}}})
    assert not event_allowed(bot, {"update_id": 5, "managed_bot": {"user": {"id": OWNER}}})
