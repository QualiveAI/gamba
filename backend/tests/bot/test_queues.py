import json

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api.bot_webhooks import telegram_webhook
from app.bot.inbox import save_update
from app.bot.outbox import enqueue
from app.bot.security import BotSecurityError, decrypt_secret
from app.bot.users import apply_start_attribution, ensure_telegram_user
from app.config import settings
from app.db import get_conn


@pytest.mark.asyncio
async def test_inbox_deduplicates_and_encrypts_before_ack(main_registry):
    update = {"update_id": 20001, "message": {"text": "sensitive-synthetic-message"}}
    async with get_conn() as conn, conn.transaction():
        first, inserted = await save_update(conn, bot=main_registry, update=update)
        second, inserted_again = await save_update(conn, bot=main_registry, update=update)
        assert first == second and inserted and not inserted_again
    async with get_conn() as conn:
        row = await (
            await conn.execute(
                "SELECT payload_encrypted, status FROM bot_inbox WHERE id = %s", (first,)
            )
        ).fetchone()
    assert "sensitive-synthetic-message" not in row["payload_encrypted"]
    assert json.loads(decrypt_secret(row["payload_encrypted"])) == update
    assert row["status"] == "pending"


@pytest.mark.asyncio
async def test_invalid_header_does_not_read_payload(main_registry):
    was_read = False

    async def receive():
        nonlocal was_read
        was_read = True
        raise AssertionError("Неавторизованное тело не должно читаться")

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [
                (b"x-telegram-bot-api-secret-token", b"wrong"),
                (b"content-length", b"999999999"),
            ],
        },
        receive,
    )
    with pytest.raises(HTTPException) as rejected:
        await telegram_webhook(main_registry["bot_id"], request)
    assert rejected.value.status_code == 403 and was_read is False


@pytest.mark.asyncio
async def test_webhook_acks_only_durable_insert_and_accepts_duplicate(main_registry):
    raw = json.dumps({"update_id": 20002, "message": {"text": "/menu"}}).encode()

    def request():
        async def receive():
            return {"type": "http.request", "body": raw, "more_body": False}

        return Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/",
                "headers": [
                    (b"x-telegram-bot-api-secret-token", settings.telegram_webhook_secret.encode()),
                ],
            },
            receive,
        )

    assert await telegram_webhook(main_registry["bot_id"], request()) == {"ok": True}
    assert await telegram_webhook(main_registry["bot_id"], request()) == {"ok": True}
    async with get_conn() as conn:
        count = await (
            await conn.execute(
                "SELECT count(*) AS n FROM bot_inbox WHERE bot_id=%s AND update_id=20002",
                (main_registry["bot_id"],),
            )
        ).fetchone()
    assert count["n"] == 1


@pytest.mark.asyncio
async def test_outbox_reuses_dedupe_and_never_commits_caller_transaction(main_registry):
    async with get_conn() as conn, conn.transaction():
        user = await ensure_telegram_user(conn, telegram_id=830000001)
    payload = {"coins": 100, "rail": "stars", "intent_id": "synthetic-order-1"}
    async with get_conn() as conn, conn.transaction():
        first = await enqueue(
            conn,
            kind="deposit_confirmed",
            user_id=user["id"],
            payload=payload,
            dedupe_key="synthetic-deposit-dedupe-1",
        )
        second = await enqueue(
            conn,
            kind="deposit_confirmed",
            user_id=user["id"],
            payload=payload,
            dedupe_key="synthetic-deposit-dedupe-1",
        )
        assert first == second
        async with get_conn() as other:
            invisible = await (
                await other.execute("SELECT id FROM bot_outbox WHERE id = %s", (first,))
            ).fetchone()
        assert invisible is None
        with pytest.raises(BotSecurityError):
            await enqueue(
                conn,
                kind="deposit_confirmed",
                user_id=user["id"],
                payload=dict(payload, coins=999),
                dedupe_key="synthetic-deposit-dedupe-1",
            )
    async with get_conn() as conn:
        count = await (
            await conn.execute(
                "SELECT count(*) AS n FROM bot_outbox WHERE dedupe_key=%s",
                ("synthetic-deposit-dedupe-1",),
            )
        ).fetchone()
    assert count["n"] == 1


@pytest.mark.asyncio
async def test_welcome_referral_fk_and_first_touch_idempotent(main_registry):
    async with get_conn() as conn, conn.transaction():
        referrer = await ensure_telegram_user(conn, telegram_id=830000101, username="referrer")
        user = await ensure_telegram_user(conn, telegram_id=830000102, username="new_user")
        await ensure_telegram_user(conn, telegram_id=830000102, username="new_user_again")
        for _ in range(2):
            await apply_start_attribution(
                conn,
                user=user,
                source_bot_id=main_registry["bot_id"],
                payload=f"ref_{referrer['id']}",
            )
        await apply_start_attribution(
            conn, user=user, source_bot_id=main_registry["bot_id"], payload="lp_telegram"
        )
        await apply_start_attribution(
            conn, user=user, source_bot_id=main_registry["bot_id"], payload="lp_social"
        )
        await apply_start_attribution(
            conn, user=user, source_bot_id=main_registry["bot_id"], payload="lp_untrusted"
        )
        bonus = await (
            await conn.execute(
                "SELECT count(*) AS n FROM ledger_entries "
                "WHERE user_id=%s AND reason='welcome_freebet'",
                (user["id"],),
            )
        ).fetchone()
        referral = await (
            await conn.execute("SELECT * FROM referrals WHERE referee_id=%s", (user["id"],))
        ).fetchone()
        touch = await (
            await conn.execute(
                "SELECT campaign FROM bot_user_attribution WHERE user_id=%s", (user["id"],)
            )
        ).fetchone()
    assert bonus["n"] == 1
    assert referral["referrer_id"] == referrer["id"] and referral["referee_id"] == user["id"]
    assert touch["campaign"] == "telegram"


@pytest.mark.asyncio
async def test_outbox_rejects_plaintext_code_and_guest(main_registry):
    async with get_conn() as conn, conn.transaction():
        guest = await (
            await conn.execute(
                "INSERT INTO users (is_guest,username) VALUES (TRUE,'synthetic_guest') RETURNING id"
            )
        ).fetchone()
        with pytest.raises(BotSecurityError):
            await enqueue(
                conn,
                kind="giftcard_delivery",
                user_id=guest["id"],
                payload={"redemption_id": 12, "code": "SYNTHETIC-CODE"},
                dedupe_key="secret-test",
            )
        with pytest.raises(BotSecurityError):
            await enqueue(
                conn,
                kind="giftcard_delivery",
                user_id=guest["id"],
                payload={"redemption_id": 12},
                dedupe_key="guest-test",
            )
