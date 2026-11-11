"""Только тестовые карты/ключи; интеграционные тесты требуют изолированной TEST_DATABASE_URL."""

import asyncio
import base64
import secrets
import uuid
from types import SimpleNamespace

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI

from app.api import admin_withdrawals as admin_api
from app.api import giftcards as cards_api
from app.api import withdrawals as withdrawals_api
from app.api.deps import get_current_user
from app.bot import outbox
from app.db import get_conn
from app.giftcards import security
from app.giftcards import service as cards
from app.giftcards.security import GiftCardError
from app.withdrawals import service as redemptions
from core.engine.ledger.ledger import post_entry


@pytest.fixture(autouse=True)
def sandbox_settings(monkeypatch):
    monkeypatch.setattr(
        security,
        "settings",
        SimpleNamespace(
            giftcard_redemption_enabled=True,
            giftcard_mode="sandbox",
            giftcard_fernet_key=Fernet.generate_key().decode("ascii"),
            giftcard_fingerprint_key=base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(
                "ascii"
            ),
        ),
    )


def unique_number():
    return 10_000_000_000 + uuid.uuid4().int % 1_000_000_000_000


def sample_code():
    return "TEST-ONLY-" + uuid.uuid4().hex.upper()


async def new_user(*, coins=1_000, freebets=0, guest=False):
    async with get_conn() as conn, conn.transaction():
        row = await (
            await conn.execute(
                "INSERT INTO users (telegram_id, region, is_guest) VALUES (%s, 'BR', %s) "
                "RETURNING id, telegram_id, is_guest",
                (None if guest else unique_number(), guest),
            )
        ).fetchone()
        user = {**dict(row), "auth_scope": "guest" if guest else "primary", "auth_bot_id": None}
        if coins:
            await post_entry(conn, user["id"], "units", coins, "test_giftcard_funding")
        if freebets:
            await post_entry(conn, user["id"], "freebets", freebets, "test_giftcard_freebets")
    return user


async def new_sku(user, *, coin_cost=137, face_value_minor=731, sandbox=True):
    async with get_conn() as conn:
        sku = await cards.create_sku(
            conn,
            operator_sku="TEST-ONLY-" + uuid.uuid4().hex,
            brand="Roblox",
            region="BR",
            card_currency="BRL",
            face_value_minor=face_value_minor,
            coin_cost=coin_cost,
            sandbox=sandbox,
            created_by=user["id"],
        )
        await cards.set_sku_active(conn, sku_id=sku["id"], active=True)
    return sku


async def import_codes(user, sku, codes, *, batch=None):
    async with get_conn() as conn:
        return await cards.import_csv(
            conn,
            ("code\n" + "\n".join(codes) + "\n").encode("ascii"),
            sku_id=sku["id"],
            supplier_name="TEST-ONLY-SUPPLIER-NOT-LICENSED",
            batch_reference=batch or "TEST-ONLY-" + uuid.uuid4().hex,
            provenance_reference="TEST-ONLY-FIXTURE-NOT-A-PURCHASE",
            distribution_agreement_reference=None,
            imported_by=user["id"],
        )


async def redeem(user, sku, key=None):
    async with get_conn() as conn:
        return await redemptions.redeem(
            conn, user, sku_id=sku["id"], idempotency_key=key or uuid.uuid4().hex
        )


async def balance(user_id):
    async with get_conn() as conn:
        return await (
            await conn.execute(
                "SELECT balance_units, balance_freebets FROM users WHERE id = %s", (user_id,)
            )
        ).fetchone()


async def prepare(user, order):
    async with get_conn() as conn, conn.transaction():
        return await cards.prepare_delivery(conn, redemption_id=order["id"], user_id=user["id"])


async def owned_bot(user, *, kind="managed", chat=True):
    bot_id = unique_number()
    async with get_conn() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO bot_registry (bot_id, kind, owner_telegram_id, owner_user_id, "
            "token_encrypted, webhook_secret_encrypted, webhook_secret_hash, status) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, 'active')",
            (
                bot_id,
                kind,
                user["telegram_id"] if kind == "managed" else None,
                user["id"] if kind == "managed" else None,
                "TEST-ONLY-OPAQUE-CREDENTIAL",
                "TEST-ONLY-OPAQUE-WEBHOOK",
                "TEST-ONLY-HASH",
            ),
        )
        if chat:
            await conn.execute(
                "INSERT INTO bot_private_chats (bot_id, user_id, chat_id, credential_version) "
                "VALUES (%s, %s, %s, 1)",
                (bot_id, user["id"], user["telegram_id"]),
            )
    return bot_id


async def record(user, order, bot_id, message_id=123):
    async with get_conn() as conn, conn.transaction():
        return await cards.record_delivery(
            conn,
            redemption_id=order["id"],
            user_id=user["id"],
            telegram_message_id=message_id,
            bot_id=bot_id,
        )


async def test_last_code_concurrent_exchange_has_one_debit_and_one_outbox():
    users = await asyncio.gather(new_user(), new_user())
    sku = await new_sku(users[0])
    await import_codes(users[0], sku, [sample_code()])
    results = await asyncio.gather(*(redeem(user, sku) for user in users), return_exceptions=True)
    winners = [result for result in results if isinstance(result, dict)]
    failures = [result for result in results if isinstance(result, GiftCardError)]
    assert len(winners) == len(failures) == 1
    assert failures[0].code == "no_inventory"
    balances = await asyncio.gather(*(balance(user["id"]) for user in users))
    assert sum(row["balance_units"] for row in balances) == 2_000 - sku["coin_cost"]
    async with get_conn() as conn:
        rows = await (
            await conn.execute(
                "SELECT payload FROM bot_outbox WHERE kind = 'giftcard_delivery' "
                "AND user_id = ANY(%s)",
                ([user["id"] for user in users],),
            )
        ).fetchall()
    assert [row["payload"] for row in rows] == [{"redemption_id": winners[0]["id"]}]


async def test_locked_last_code_is_skipped_without_waiting_or_debit():
    user = await new_user()
    sku = await new_sku(user)
    await import_codes(user, sku, [sample_code()])
    async with get_conn() as locking_conn, locking_conn.transaction():
        await locking_conn.execute(
            "SELECT id FROM giftcard_inventory WHERE sku_id = %s FOR UPDATE", (sku["id"],)
        )
        with pytest.raises(GiftCardError) as error:
            await asyncio.wait_for(redeem(user, sku), timeout=2)
    assert error.value.code == "no_inventory"
    assert (await balance(user["id"]))["balance_units"] == 1_000


async def test_same_request_retries_debit_once_and_payload_conflict():
    user = await new_user()
    sku = await new_sku(user)
    another_sku = await new_sku(user)
    await import_codes(user, sku, [sample_code(), sample_code()])
    first, second = await asyncio.gather(
        redeem(user, sku, "retry-key"), redeem(user, sku, "retry-key")
    )
    assert first["id"] == second["id"]
    assert (await balance(user["id"]))["balance_units"] == 1_000 - sku["coin_cost"]
    with pytest.raises(GiftCardError) as error:
        await redeem(user, another_sku, "retry-key")
    assert error.value.code == "idempotency_conflict"
    security.settings.giftcard_redemption_enabled = False
    assert (await redeem(user, sku, "retry-key"))["id"] == first["id"]


async def test_idempotency_key_is_scoped_to_owner():
    first, second = await asyncio.gather(new_user(), new_user())
    sku = await new_sku(first)
    await import_codes(first, sku, [sample_code(), sample_code()])
    orders = await asyncio.gather(redeem(first, sku, "same-key"), redeem(second, sku, "same-key"))
    assert orders[0]["id"] != orders[1]["id"]


async def test_no_inventory_never_debits():
    user = await new_user()
    sku = await new_sku(user)
    with pytest.raises(GiftCardError) as error:
        await redeem(user, sku)
    assert error.value.code == "no_inventory"
    assert (await balance(user["id"]))["balance_units"] == 1_000


async def test_only_freebets_cannot_buy_a_card():
    user = await new_user(coins=0, freebets=1_000)
    sku = await new_sku(user)
    await import_codes(user, sku, [sample_code()])
    with pytest.raises(GiftCardError) as error:
        await redeem(user, sku)
    assert error.value.code == "insufficient_balance"
    assert await balance(user["id"]) == {"balance_units": 0, "balance_freebets": 1_000}
    async with get_conn() as conn:
        state = await (
            await conn.execute(
                "SELECT status FROM giftcard_inventory WHERE sku_id = %s", (sku["id"],)
            )
        ).fetchone()
    assert state["status"] == "available"


async def test_outbox_failure_rolls_back_order_assignment_and_debit(monkeypatch):
    user = await new_user()
    sku = await new_sku(user)
    await import_codes(user, sku, [sample_code()])

    async def unavailable_outbox(*args, **kwargs):
        raise RuntimeError("TEST-ONLY-OUTBOX-FAILURE")

    monkeypatch.setattr(outbox, "enqueue", unavailable_outbox)
    with pytest.raises(RuntimeError, match="TEST-ONLY-OUTBOX-FAILURE"):
        await redeem(user, sku)
    assert (await balance(user["id"]))["balance_units"] == 1_000
    async with get_conn() as conn:
        inventory = await (
            await conn.execute(
                "SELECT status, assigned_redemption_id FROM giftcard_inventory WHERE sku_id = %s",
                (sku["id"],),
            )
        ).fetchone()
        count = await (
            await conn.execute(
                "SELECT COUNT(*) AS c FROM giftcard_redemptions WHERE user_id = %s", (user["id"],)
            )
        ).fetchone()
    assert inventory == {"status": "available", "assigned_redemption_id": None}
    assert count["c"] == 0


async def test_import_encrypts_at_rest_and_duplicate_is_atomic():
    user = await new_user()
    sku = await new_sku(user)
    code = sample_code()
    imported = await import_codes(user, sku, [code])
    assert imported["imported"] == 1
    async with get_conn() as conn:
        row = await (
            await conn.execute("SELECT * FROM giftcard_inventory WHERE sku_id = %s", (sku["id"],))
        ).fetchone()
    assert code not in str(dict(row))
    assert "code" not in row
    assert (
        security.vault().decrypt(row["code_ciphertext"], row["code_fingerprint"], sandbox=True)
        == code
    )
    with pytest.raises(GiftCardError) as error:
        await import_codes(user, sku, [sample_code(), code.lower()])
    assert error.value.code == "duplicate_code"
    assert code not in str(error.value)
    async with get_conn() as conn:
        rows = await (
            await conn.execute("SELECT id FROM giftcard_inventory WHERE sku_id = %s", (sku["id"],))
        ).fetchall()
        batches = await (
            await conn.execute("SELECT id FROM giftcard_batches WHERE sku_id = %s", (sku["id"],))
        ).fetchall()
    assert len(rows) == len(batches) == 1


async def test_duplicate_inside_csv_and_parallel_import_are_rejected_atomically():
    user = await new_user()
    sku = await new_sku(user)
    code = sample_code()
    with pytest.raises(GiftCardError) as error:
        await import_codes(user, sku, [code, code.lower()])
    assert error.value.code == "duplicate_code"
    results = await asyncio.gather(
        import_codes(user, sku, [code]), import_codes(user, sku, [code]), return_exceptions=True
    )
    assert len([result for result in results if isinstance(result, dict)]) == 1
    assert [result.code for result in results if isinstance(result, GiftCardError)] == [
        "duplicate_code"
    ]


async def test_ambiguous_send_retries_the_same_code_and_expiry_does_not_release():
    user = await new_user()
    sku = await new_sku(user, coin_cost=137, face_value_minor=731)
    code = sample_code()
    await import_codes(user, sku, [code])
    order = await redeem(user, sku)
    first = await prepare(user, order)
    # Telegram timeout имитируется отсутствием receipt после committed prepare.
    async with get_conn() as conn:
        await conn.execute(
            "UPDATE giftcard_inventory SET assigned_at = now() - interval '30 days' WHERE sku_id = %s",
            (sku["id"],),
        )
        assert await cards.release_expired(conn) == 0
    second = await prepare(user, order)
    assert first["code"] == second["code"] == code
    assert first["face_value_minor"] == 731
    assert first["coin_cost"] == 137
    assert code not in repr(first)
    assert (await balance(user["id"]))["balance_units"] == 863
    with pytest.raises(GiftCardError) as error:
        await redeem(await new_user(), sku)
    assert error.value.code == "no_inventory"


async def test_reject_before_delivery_refunds_once_and_old_outbox_is_inert():
    user = await new_user()
    sku = await new_sku(user)
    await import_codes(user, sku, [sample_code()])
    order = await redeem(user, sku)
    for _ in range(2):
        async with get_conn() as conn:
            result = await redemptions.reject_redemption(conn, redemption_id=order["id"])
        assert result["status"] == "rejected"
    assert (await balance(user["id"]))["balance_units"] == 1_000
    assert await prepare(user, order) is None
    new_order = await redeem(user, sku)
    assert new_order["id"] != order["id"]
    assert await prepare(user, order) is None
    async with get_conn() as conn:
        refunds = await (
            await conn.execute(
                "SELECT currency, delta FROM ledger_entries WHERE user_id = %s "
                "AND reason = 'giftcard_redemption_refund'",
                (user["id"],),
            )
        ).fetchall()
    assert refunds == [{"currency": "units", "delta": sku["coin_cost"]}]


async def test_reject_after_ambiguous_send_never_refunds_or_recycles():
    user = await new_user()
    sku = await new_sku(user)
    await import_codes(user, sku, [sample_code()])
    order = await redeem(user, sku)
    await prepare(user, order)
    async with get_conn() as conn:
        with pytest.raises(GiftCardError) as error:
            await redemptions.reject_redemption(conn, redemption_id=order["id"])
    assert error.value.code == "manual_review_required"
    assert (await balance(user["id"]))["balance_units"] == 1_000 - sku["coin_cost"]
    async with get_conn() as conn:
        state = await cards.get_redemption(conn, redemption_id=order["id"], user_id=user["id"])
        inventory = await (
            await conn.execute(
                "SELECT status FROM giftcard_inventory WHERE sku_id = %s", (sku["id"],)
            )
        ).fetchone()
    assert state["status"] == "manual_review"
    assert inventory["status"] == "assigned"


async def test_delivery_receipt_is_idempotent_and_card_retrieval_requires_owner():
    user = await new_user()
    other = await new_user()
    sku = await new_sku(user)
    code = sample_code()
    await import_codes(user, sku, [code])
    order = await redeem(user, sku)
    bot_id = await owned_bot(user)
    async with get_conn() as conn, conn.transaction():
        pending = await cards.get_my_card(conn, redemption_id=order["id"], user_id=user["id"])
        assert pending["status"] == "pending" and "code" not in pending
    await prepare(user, order)
    await record(user, order, bot_id, message_id=123)
    await record(user, order, bot_id, message_id=124)
    assert await prepare(user, order) is None
    async with get_conn() as conn:
        async with conn.transaction():
            own = await cards.get_my_card(conn, redemption_id=order["id"], user_id=user["id"])
            assert own["code"] == code
        with pytest.raises(GiftCardError) as error:
            async with conn.transaction():
                await cards.get_my_card(conn, redemption_id=order["id"], user_id=other["id"])
        assert error.value.code == "not_found"
        status = await cards.get_redemption(conn, redemption_id=order["id"], user_id=user["id"])
        listed = await cards.list_owned_cards(conn, user_id=user["id"])
        admins = await redemptions.admin_redemptions(conn)
        receipt = await (
            await conn.execute(
                "SELECT telegram_message_id, delivered_bot_id FROM giftcard_redemptions WHERE id = %s",
                (order["id"],),
            )
        ).fetchone()
    assert receipt == {"telegram_message_id": 123, "delivered_bot_id": bot_id}
    assert code not in str((status, listed, admins))
    async with get_conn() as conn:
        with pytest.raises(GiftCardError) as error:
            await redemptions.reject_redemption(conn, redemption_id=order["id"])
    assert error.value.code == "manual_review_required"
    assert (await balance(user["id"]))["balance_units"] == 1_000 - sku["coin_cost"]


async def test_delivery_record_rejects_foreign_or_stale_bot_chat():
    user, other = await asyncio.gather(new_user(), new_user())
    sku = await new_sku(user)
    await import_codes(user, sku, [sample_code()])
    order = await redeem(user, sku)
    await prepare(user, order)
    foreign_bot = await owned_bot(other)
    with pytest.raises(GiftCardError) as error:
        await record(user, order, foreign_bot)
    assert error.value.code == "owner_mismatch"
    own_bot = await owned_bot(user)
    async with get_conn() as conn:
        await conn.execute(
            "UPDATE bot_registry SET credential_version = 2 WHERE bot_id = %s", (own_bot,)
        )
    with pytest.raises(GiftCardError) as error:
        await record(user, order, own_bot)
    assert error.value.code == "owner_mismatch"


async def test_managed_origin_can_record_verified_primary_fallback(monkeypatch):
    from app.bot import pool

    user = await new_user()
    managed_id = await owned_bot(user)
    user.update(
        auth_scope="managed", auth_bot_id=managed_id, auth_owner_telegram_id=user["telegram_id"]
    )
    sku = await new_sku(user)
    await import_codes(user, sku, [sample_code()])
    order = await redeem(user, sku)
    # Проверка actual primary здесь изолируется от настроек реального бота.
    async with get_conn() as conn:
        existing = await (
            await conn.execute("SELECT bot_id FROM bot_registry WHERE kind = 'main'")
        ).fetchone()
    if existing:
        main_id = existing["bot_id"]
        async with get_conn() as conn:
            await conn.execute(
                "INSERT INTO bot_private_chats (bot_id, user_id, chat_id, credential_version) "
                "SELECT bot_id, %s, %s, credential_version FROM bot_registry WHERE bot_id = %s",
                (user["id"], user["telegram_id"], main_id),
            )
    else:
        main_id = await owned_bot(user, kind="main")
    monkeypatch.setattr(
        pool, "trusted_main", lambda bot: bot["kind"] == "main" and bot["bot_id"] == main_id
    )
    await prepare(user, order)
    await record(user, order, main_id)
    async with get_conn() as conn:
        row = await (
            await conn.execute(
                "SELECT bot_id, delivered_bot_id FROM giftcard_redemptions WHERE id = %s",
                (order["id"],),
            )
        ).fetchone()
    assert row == {"bot_id": managed_id, "delivered_bot_id": main_id}


async def test_disabled_guest_and_sandbox_live_mismatch_fail_before_debit():
    user = await new_user()
    sku = await new_sku(user)
    await import_codes(user, sku, [sample_code()])
    security.settings.giftcard_redemption_enabled = False
    async with get_conn() as conn:
        assert await cards.catalog(conn) == {"enabled": False, "mode": "disabled", "items": []}
    with pytest.raises(GiftCardError) as error:
        await redeem(user, sku)
    assert error.value.code == "disabled"
    security.settings.giftcard_redemption_enabled = True
    guest = await new_user(guest=True)
    with pytest.raises(GiftCardError) as error:
        await redeem(guest, sku)
    assert error.value.code == "telegram_required"
    security.settings.giftcard_mode = "live"
    with pytest.raises(GiftCardError) as error:
        await redeem(user, sku)
    assert error.value.code == "sku_unavailable"
    assert (await balance(user["id"]))["balance_units"] == 1_000


def test_csv_limits_marker_and_keyed_deduplication():
    code = sample_code()
    code_vault = security.vault()
    assert code_vault.fingerprint(code) == code_vault.fingerprint(code.replace("-", ""))
    with pytest.raises(GiftCardError) as error:
        cards._parse_codes(
            b"code\n" + b"X" * security.MAX_IMPORT_BYTES, sandbox=True, code_vault=code_vault
        )
    assert error.value.code == "import_too_large"
    with pytest.raises(GiftCardError):
        cards._parse_codes(b"code\nNOT-A-REAL-CARD\n", sandbox=True, code_vault=code_vault)
    with pytest.raises(GiftCardError):
        cards._parse_codes(("code\n" + code).encode(), sandbox=False, code_vault=code_vault)
    with pytest.raises(GiftCardError):
        cards._parse_codes(
            b"code,unexpected\nTEST-ONLY-ABC,extra\n", sandbox=True, code_vault=code_vault
        )
    security.settings.giftcard_fingerprint_key = security.settings.giftcard_fernet_key
    with pytest.raises(GiftCardError) as error:
        security.vault()
    assert error.value.code == "storage_not_configured"


@pytest.mark.parametrize("bad_value", [True, 1.5, "137", 0, -1])
async def test_coin_cost_requires_an_explicit_positive_integer(bad_value):
    user = await new_user()
    with pytest.raises(GiftCardError):
        await new_sku(user, coin_cost=bad_value)


async def test_delivery_primitives_require_transaction():
    user = await new_user()
    async with get_conn() as conn:
        with pytest.raises(GiftCardError) as error:
            await cards.prepare_delivery(conn, redemption_id=1, user_id=user["id"])
    assert error.value.code == "transaction_required"


async def test_catalog_has_explicit_face_value_and_disabled_sku_is_hidden():
    user = await new_user()
    sku = await new_sku(user, face_value_minor=731, coin_cost=137)
    await import_codes(user, sku, [sample_code()])
    async with get_conn() as conn:
        catalog = await cards.catalog(conn)
        item = next(item for item in catalog["items"] if item["id"] == sku["id"])
        assert (
            item["card_currency"] == "BRL" and item["brand"] == "Roblox" and item["region"] == "BR"
        )
        assert item["face_value_minor"] == 731 and item["coin_cost"] == 137
        assert item["available"] and item["available_count"] == 1 and item["sandbox"]
        await cards.set_sku_active(conn, sku_id=sku["id"], active=False)
        assert not any(item["id"] == sku["id"] for item in (await cards.catalog(conn))["items"])


async def test_live_import_requires_distribution_provenance_before_any_insert():
    user = await new_user()
    sku = await new_sku(user, sandbox=False)
    with pytest.raises(GiftCardError) as error:
        await import_codes(user, sku, [sample_code()])
    assert error.value.code == "provenance_required"


async def test_foreign_owner_cannot_prepare_and_persisted_guest_cannot_redeem():
    user, other = await asyncio.gather(new_user(), new_user())
    sku = await new_sku(user)
    await import_codes(user, sku, [sample_code(), sample_code()])
    order = await redeem(user, sku)
    with pytest.raises(GiftCardError) as error:
        await prepare(other, order)
    assert error.value.code == "not_found"
    async with get_conn() as conn:
        await conn.execute("UPDATE users SET is_guest = TRUE WHERE id = %s", (user["id"],))
    with pytest.raises(GiftCardError) as error:
        await redeem(user, sku)
    assert error.value.code == "telegram_required"


async def test_http_status_admin_and_validation_never_expose_code():
    user, other = await asyncio.gather(new_user(), new_user())
    sku = await new_sku(user)
    code = sample_code()
    await import_codes(user, sku, [code])
    app = FastAPI()
    app.include_router(cards_api.router)
    app.include_router(withdrawals_api.router)
    app.include_router(admin_api.router)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[cards_api.giftcard_admin] = lambda: user
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/redemptions", json={"sku_id": sku["id"], "idempotency_key": "http-request"}
        )
        assert response.status_code == 200
        order = response.json()
        for path in (f"/redemptions/{order['id']}", "/redemptions", "/admin/redemptions"):
            result = await client.get(path)
            assert result.status_code == 200 and code not in result.text
            assert "code_ciphertext" not in result.text and "code_fingerprint" not in result.text
        for payload in (
            {"sku_id": sku["id"], "idempotency_key": "extra", "code": code},
            {"sku_id": True, "idempotency_key": "bool"},
            {"sku_id": 1.5, "idempotency_key": "fraction"},
            {"sku_id": sku["id"], "idempotency_key": "qty", "quantity": 2},
        ):
            rejected = await client.post("/redemptions", json=payload)
            assert rejected.status_code == 422 and code not in rejected.text
        legacy = await client.post("/withdrawals", json={"amount": 1_000, "region": "BR"})
        assert legacy.status_code == 422
        app.dependency_overrides[get_current_user] = lambda: other
        forbidden = await client.get(f"/redemptions/{order['id']}")
        assert forbidden.status_code == 404 and code not in forbidden.text
        cancelled = await client.post(
            f"/admin/redemptions/{order['id']}/reject", json={"reason": "operator_rejected"}
        )
        assert cancelled.status_code == 200 and code not in cancelled.text


async def test_http_import_duplicate_is_sanitized_and_atomic():
    user = await new_user()
    sku = await new_sku(user)
    code = sample_code()
    app = FastAPI()
    app.include_router(cards_api.router)
    app.dependency_overrides[cards_api.giftcard_admin] = lambda: user
    parameters = {
        "sku_id": sku["id"],
        "supplier_name": "TEST-ONLY-NOT-A-SUPPLIER",
        "batch_reference": uuid.uuid4().hex,
        "provenance_reference": "TEST-ONLY-NO-PURCHASE",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/admin/giftcards/import",
            params=parameters,
            content=f"code\n{code}\n{code}\n".encode(),
            headers={"Content-Type": "text/csv"},
        )
        assert response.status_code == 409
        assert code not in response.text
        assert response.json()["detail"]["code"] == "duplicate_code"
        response = await client.post(
            "/admin/giftcards/import",
            params=parameters,
            content=b"ignored",
            headers={"Content-Type": "text/csv", "Content-Length": "1048577"},
        )
        assert response.status_code == 413
    async with get_conn() as conn:
        rows = await (
            await conn.execute("SELECT id FROM giftcard_inventory WHERE sku_id = %s", (sku["id"],))
        ).fetchall()
    assert rows == []
