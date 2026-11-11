import asyncio
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest

from app.bot.client import TelegramAPIError, TelegramClient, retry_delay
from app.bot.dispatcher import dispatch_update
from app.bot.notifications import deliver_notification
from app.config import settings


@pytest.mark.asyncio
async def test_ambiguous_delivery_retries_same_code_outside_transaction(monkeypatch):
    from app.bot import notifications

    state = {"connections": 0, "transactions": 0, "prepares": 0, "records": 0, "sends": []}
    card = {
        "redemption_id": 41,
        "user_id": 7,
        "telegram_id": 900001,
        "bot_id": None,
        "code": "SYNTHETIC-NO-VALUE-CODE",
        "brand": "Roblox",
        "region": "BR",
        "sandbox": True,
    }
    user = {"id": 7, "telegram_id": 900001, "is_guest": False}
    bot = {"bot_id": 900002, "kind": "main", "chat_id": 900001, "credential_version": 1}

    @asynccontextmanager
    async def transaction():
        state["transactions"] += 1
        try:
            yield
        finally:
            state["transactions"] -= 1

    @asynccontextmanager
    async def get_conn():
        state["connections"] += 1
        try:
            yield SimpleNamespace(transaction=transaction)
        finally:
            state["connections"] -= 1

    async def resolve(_conn, *, job):
        return user, bot

    async def prepare(_conn, *, redemption_id, user_id):
        assert state["transactions"] == 1
        assert (redemption_id, user_id) == (41, 7)
        state["prepares"] += 1
        return card.copy()

    async def record(_conn, *, redemption_id, user_id, telegram_message_id, bot_id):
        assert state["transactions"] == 1
        assert (redemption_id, user_id, telegram_message_id, bot_id) == (41, 7, 56, 900002)
        state["records"] += 1

    async def send(_client, *, user_id, bot, message, protected):
        assert state["connections"] == state["transactions"] == 0
        assert user_id == 7 and protected is True
        state["sends"].append(message["text"])
        if len(state["sends"]) == 1:
            raise TelegramAPIError("transport_error", retryable=True)
        return 56

    monkeypatch.setattr(notifications, "get_conn", get_conn)
    monkeypatch.setattr(notifications, "resolve_destination", resolve)
    monkeypatch.setattr(
        notifications,
        "optional_service",
        lambda *_args: SimpleNamespace(prepare_delivery=prepare, record_delivery=record),
    )
    monkeypatch.setattr(notifications, "_send", send)
    job = {
        "id": 50,
        "kind": "giftcard_delivery",
        "user_id": 7,
        "bot_id": None,
        "payload": {"redemption_id": 41},
    }
    with pytest.raises(TelegramAPIError):
        await deliver_notification(object(), job=job)
    assert state["records"] == 0
    assert await deliver_notification(object(), job=job) == (56, 900002)
    assert state["prepares"] == 2 and state["records"] == 1
    assert state["sends"][0] == state["sends"][1]
    assert "SYNTHETIC-NO-VALUE-CODE" in state["sends"][1]


@pytest.mark.asyncio
async def test_429_classification_and_exception_do_not_reveal_token():
    token = "910001:synthetic_token_not_for_telegram"
    requests = []

    def reply(request):
        requests.append(request)
        return httpx.Response(
            429, json={"ok": False, "error_code": 429, "parameters": {"retry_after": 123}}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as session:
        client = TelegramClient(session=session)
        with pytest.raises(TelegramAPIError) as rejected:
            await client.call(token, "getMe")
        assert rejected.value.code == "rate_limited" and rejected.value.retry_after == 123
        assert rejected.value.retryable
        assert token not in str(rejected.value) and "https://" not in str(rejected.value)
        assert retry_delay(3, rejected.value.retry_after) == 123
        assert len(requests) == 1
        assert requests[0].method == "POST"


@pytest.mark.asyncio
async def test_malformed_429_body_still_retries():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(429, text="rate limit"))
    ) as session:
        client = TelegramClient(session=session)
        with pytest.raises(TelegramAPIError) as rejected:
            await client.call("910002:synthetic_token", "getMe")
    assert rejected.value.code == "rate_limited" and rejected.value.retryable


@pytest.mark.asyncio
async def test_managed_merchant_payload_never_reaches_stars(monkeypatch):
    from app.bot import dispatcher

    def no_service(*_args):
        raise AssertionError("Managed merchant event не должен вызывать payment service")

    monkeypatch.setattr(dispatcher, "optional_service", no_service)
    bot = {
        "bot_id": 1,
        "kind": "managed",
        "status": "active",
        "owner_telegram_id": 2,
        "owner_user_id": 3,
        "token_encrypted": "encrypted",
    }
    await dispatch_update(
        object(),
        bot=bot,
        update={
            "update_id": 1,
            "message": {
                "from": {"id": 2, "is_bot": False},
                "chat": {"type": "private", "id": 2},
                "successful_payment": {},
            },
        },
    )
    await dispatch_update(
        object(), bot=bot, update={"update_id": 2, "pre_checkout_query": {"from": {"id": 2}}}
    )


@pytest.mark.asyncio
async def test_disabled_worker_does_not_create_client(monkeypatch):
    from app.bot import worker

    monkeypatch.setattr(settings, "bot_mode", "disabled")

    def forbidden():
        raise AssertionError("Disabled worker не должен создавать сетевой клиент")

    monkeypatch.setattr(worker, "TelegramClient", forbidden)
    await worker.run_worker()


@pytest.mark.asyncio
async def test_configure_bot_preserves_user_selected_name(monkeypatch):
    from app.bot.setup import configure_bot

    monkeypatch.setattr(settings, "webapp_url", "https://app.example.test/app/")
    calls = []

    class Client:
        async def call(self, token, method, **params):
            calls.append((method, params))
            return True

    await configure_bot(
        Client(), bot={"bot_id": 42, "kind": "managed"}, token="synthetic", webhook=False
    )
    assert not any(method == "setMyName" for method, _params in calls)
    menu = next(params for method, params in calls if method == "setChatMenuButton")
    assert "auth_bot_id=42" in menu["menu_button"]["web_app"]["url"]
    assert all(
        method
        in {"setMyCommands", "setMyDescription", "setMyShortDescription", "setChatMenuButton"}
        for method, _params in calls
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("event_kind", ["successful_payment", "pre_checkout_query"])
async def test_main_payment_and_worker_share_intent_first_lock_order(
    main_registry, monkeypatch, event_kind
):
    from app.bot.inbox import save_update
    from app.db import get_conn
    from app.payments import stars
    from core.contracts.payment import VerifiedPayment
    from core.payments.events import process_event, record_verified_event
    from core.payments.intents import create_intent, get_intent
    from core.payments.quotes import create_quote

    monkeypatch.setattr(settings, "payments_mode", "live")
    monkeypatch.setattr(settings, "stars_enabled", True)
    monkeypatch.setattr(
        stars, "_transport", SimpleNamespace(merchant_bot_id=main_registry["bot_id"])
    )
    # Ни invoice transport, ни Telegram send не нужны: работаем с уже проверенным evidence.
    telegram_id = 8_900_000_000 + uuid.uuid4().int % 1_000_000_000
    async with get_conn() as conn, conn.transaction():
        saved_flags = await (
            await conn.execute(
                "SELECT key, value FROM system_config WHERE key = ANY(%s)",
                (["deposits_enabled", "payments_stars_enabled"],),
            )
        ).fetchall()
        saved_flags = {row["key"]: row["value"] for row in saved_flags}
        for key in ("deposits_enabled", "payments_stars_enabled"):
            await conn.execute(
                "INSERT INTO system_config (key, value) VALUES (%s, '{\"value\":true}') "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                (key,),
            )
        row = await (
            await conn.execute(
                "INSERT INTO users (telegram_id, username) "
                "VALUES (%s, 'before_payment') RETURNING id",
                (telegram_id,),
            )
        ).fetchone()
        user = {
            "id": row["id"],
            "telegram_id": telegram_id,
            "is_guest": False,
            "auth_scope": "primary",
            "auth_bot_id": main_registry["bot_id"],
        }
        quote = await create_quote(conn, user=user, coins=100, method="stars")
        intent = await create_intent(
            conn=conn, user=user, quote_id=quote.id, idempotency_key=uuid.uuid4().hex
        )
        charge_id = "synthetic-charge-" + uuid.uuid4().hex
        evidence = VerifiedPayment(
            reference=intent.id,
            rail="stars",
            mode="live",
            provider_event_id=charge_id,
            status="succeeded",
            amount_atomic=intent.provider_amount_atomic,
            currency="XTR",
            source="telegram_main",
            charge_id=charge_id,
            user_id=user["id"],
            merchant_bot_id=main_registry["bot_id"],
        )
        event_id = await record_verified_event(conn, evidence)
        payment = {
            "invoice_payload": f"deposit:{intent.id}",
            "currency": "XTR",
            "total_amount": intent.provider_amount_atomic,
        }
        sender = {"id": telegram_id, "is_bot": False, "username": "not_a_profile_update"}
        update = {"update_id": 3_000_000_000 + uuid.uuid4().int % 1_000_000_000}
        if event_kind == "successful_payment":
            update["message"] = {
                "from": sender,
                "chat": {"id": telegram_id, "type": "private"},
                "successful_payment": dict(payment, telegram_payment_charge_id=charge_id),
            }
        else:
            update["pre_checkout_query"] = dict(
                payment, id="synthetic-checkout", **{"from": sender}
            )
        await save_update(conn, bot=main_registry, update=update)

    reached_intent = asyncio.Event()
    calls = []
    actual_get_intent = stars.get_intent

    async def observed_get_intent(intent_id, *, conn=None, lock=False):
        if intent_id == intent.id and lock:
            reached_intent.set()
        return await actual_get_intent(intent_id, conn=conn, lock=lock)

    class Client:
        async def call(self, token, method, **params):
            assert method == "answerPreCheckoutQuery"
            calls.append(params)
            return True

    monkeypatch.setattr(stars, "get_intent", observed_get_intent)
    task = None
    try:
        async with get_conn() as worker_conn, worker_conn.transaction():
            # Worker уже держит intent, но ещё не users. Handler обязан ждать только intent,
            # не мешая worker завершить intent -> event -> users без deadlock/lock timeout.
            await get_intent(intent.id, conn=worker_conn, lock=True)
            await worker_conn.execute("SET LOCAL lock_timeout = '1s'")
            task = asyncio.create_task(dispatch_update(Client(), bot=main_registry, update=update))
            await asyncio.wait_for(reached_intent.wait(), timeout=5)
            result = await process_event(worker_conn, event_id)
            assert result.status == "processed" and result.credited
        await asyncio.wait_for(task, timeout=5)
        async with get_conn() as conn:
            owner = await (
                await conn.execute(
                    "SELECT username, balance_units FROM users WHERE id=%s", (user["id"],)
                )
            ).fetchone()
            ledger = await (
                await conn.execute(
                    "SELECT currency, delta, reason FROM ledger_entries WHERE user_id=%s",
                    (user["id"],),
                )
            ).fetchall()
            notifications = await (
                await conn.execute("SELECT kind FROM bot_outbox WHERE user_id=%s", (user["id"],))
            ).fetchall()
            chat = await (
                await conn.execute(
                    "SELECT chat_id FROM bot_private_chats WHERE user_id=%s AND bot_id=%s",
                    (user["id"], main_registry["bot_id"]),
                )
            ).fetchone()
        assert owner["username"] == "before_payment" and owner["balance_units"] == 100
        assert len(ledger) == 1 and ledger[0]["reason"] == "deposit_units"
        assert [item["kind"] for item in notifications] == ["deposit_confirmed"]
        if event_kind == "successful_payment":
            assert chat["chat_id"] == telegram_id and not calls
        else:
            assert chat is None and len(calls) == 1 and calls[0]["ok"] is False
    finally:
        if task is not None:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        from psycopg.types.json import Jsonb

        async with get_conn() as conn, conn.transaction():
            for key in ("deposits_enabled", "payments_stars_enabled"):
                await conn.execute(
                    "UPDATE system_config SET value=%s WHERE key=%s",
                    (Jsonb(saved_flags.get(key, {"value": False})), key),
                )


@pytest.mark.asyncio
@pytest.mark.parametrize("owner_exists", [True, False])
async def test_unconfirmed_payment_has_no_user_or_chat_side_effects(
    main_registry, monkeypatch, owner_exists
):
    from app.bot import dispatcher
    from app.bot.dispatcher import SettlementDeferred
    from app.bot.security import BotSecurityError
    from app.db import get_conn

    telegram_id = 10_900_000_000 + uuid.uuid4().int % 1_000_000_000
    if owner_exists:
        async with get_conn() as conn, conn.transaction():
            await conn.execute(
                "INSERT INTO users (telegram_id, username) VALUES (%s, 'unchanged_owner')",
                (telegram_id,),
            )
    attempts = []

    async def rejected_settlement(conn, bot, user, payment):
        attempts.append(user["id"])
        return False

    monkeypatch.setattr(dispatcher, "_successful_payment", rejected_settlement)
    expected = SettlementDeferred if owner_exists else BotSecurityError
    with pytest.raises(expected):
        await dispatch_update(
            object(),
            bot=main_registry,
            update={
                "update_id": 4_000_000_000 + uuid.uuid4().int % 1_000_000_000,
                "message": {
                    "from": {"id": telegram_id, "is_bot": False, "username": "must_not_replace"},
                    "chat": {"id": telegram_id, "type": "private"},
                    "successful_payment": {},
                },
            },
        )
    async with get_conn() as conn:
        user = await (
            await conn.execute(
                "SELECT id, username, balance_units FROM users WHERE telegram_id=%s", (telegram_id,)
            )
        ).fetchone()
        assert bool(user) is owner_exists
        assert len(attempts) == int(owner_exists)
        if user:
            assert user["username"] == "unchanged_owner" and user["balance_units"] == 0
            for table in ("ledger_entries", "bot_private_chats", "bot_outbox"):
                row = await (
                    await conn.execute(
                        f"SELECT count(*) AS n FROM {table} WHERE user_id=%s", (user["id"],)
                    )
                ).fetchone()
                assert row["n"] == 0
