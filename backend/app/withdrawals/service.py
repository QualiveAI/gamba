"""Атомарный обмен монет на один заранее загруженный код.

Ledger не меняется глобально. Все записи одного обмена находятся внутри conn.transaction().
Старые withdrawals не содержат однозначного SKU mapping и доступны только для просмотра.
"""

from app.giftcards import service as giftcard_service
from app.giftcards.security import (
    GiftCardError,
    authenticated_user,
    enabled_mode,
    positive_integer,
    request_key,
)
from core.engine.ledger.ledger import post_entry


async def redeem(conn, user: dict, *, sku_id: int, idempotency_key: str) -> dict:
    user_id, telegram_id, scope, bot_id = authenticated_user(user)
    positive_integer(sku_id)
    idempotency_key = request_key(idempotency_key)
    async with conn.transaction():
        # Порядок блокировок единый: user -> order -> inventory. Повторы одного user сериализуются.
        owner = await (
            await conn.execute(
                "SELECT id, telegram_id, is_guest, balance_units "
                "FROM users WHERE id = %s FOR UPDATE",
                (user_id,),
            )
        ).fetchone()
        if (
            owner is None
            or owner["is_guest"]
            or owner["telegram_id"] != telegram_id
            or owner["telegram_id"] <= 0
        ):
            raise GiftCardError("telegram_required", 403)
        previous = await (
            await conn.execute(
                "SELECT id, sku_id FROM giftcard_redemptions "
                "WHERE user_id = %s AND idempotency_key = %s",
                (user_id, idempotency_key),
            )
        ).fetchone()
        if previous is not None:
            if int(previous["sku_id"]) != sku_id:
                raise GiftCardError("idempotency_conflict", 409)
            return await giftcard_service.get_redemption(
                conn, redemption_id=int(previous["id"]), user_id=user_id
            )
        mode = enabled_mode()
        sku = await (
            await conn.execute(
                "SELECT id, operator_sku, brand, region, card_currency, face_value_minor, "
                "coin_cost, sandbox, active FROM giftcard_skus WHERE id = %s FOR SHARE",
                (sku_id,),
            )
        ).fetchone()
        if sku is None or not sku["active"] or sku["sandbox"] != (mode == "sandbox"):
            raise GiftCardError("sku_unavailable", 409)
        inventory_id = await giftcard_service.reserve(conn, sku_id=sku_id)
        if int(owner["balance_units"]) < int(sku["coin_cost"]):
            raise GiftCardError("insufficient_balance", 409)
        order = await (
            await conn.execute(
                "INSERT INTO giftcard_redemptions "
                "(user_id, telegram_id, sku_id, inventory_id, idempotency_key, operator_sku, "
                "brand, region, card_currency, face_value_minor, coin_cost, "
                "sandbox, auth_scope, bot_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (
                    user_id,
                    telegram_id,
                    sku_id,
                    inventory_id,
                    idempotency_key,
                    sku["operator_sku"],
                    sku["brand"],
                    sku["region"],
                    sku["card_currency"],
                    sku["face_value_minor"],
                    sku["coin_cost"],
                    sku["sandbox"],
                    scope,
                    bot_id,
                ),
            )
        ).fetchone()
        redemption_id = int(order["id"])
        await conn.execute(
            "UPDATE giftcard_inventory SET status = 'assigned', assigned_redemption_id = %s, "
            "assigned_at = now() WHERE id = %s AND status = 'available'",
            (redemption_id, inventory_id),
        )
        try:
            await post_entry(
                conn,
                user_id,
                "units",
                -int(sku["coin_cost"]),
                "giftcard_redemption",
                f"giftcard:{redemption_id}:debit",
            )
        except (ValueError, RuntimeError):
            raise GiftCardError("ledger_error", 409) from None
        from app.bot.outbox import enqueue

        await enqueue(
            conn,
            kind="giftcard_delivery",
            user_id=user_id,
            payload={"redemption_id": redemption_id},
            dedupe_key=f"giftcard:{redemption_id}:delivery",
            bot_id=bot_id,
        )
        return await giftcard_service.get_redemption(
            conn, redemption_id=redemption_id, user_id=user_id
        )


async def reject_redemption(conn, *, redemption_id: int, reason: str = "operator_rejected") -> dict:
    """Возврат один раз и только до первого committed prepare_delivery."""
    positive_integer(redemption_id)
    if reason not in ("operator_rejected", "requested_by_owner", "risk_review"):
        raise GiftCardError("invalid_request")
    blocked = False
    async with conn.transaction():
        owner = await (
            await conn.execute(
                "SELECT user_id FROM giftcard_redemptions WHERE id = %s", (redemption_id,)
            )
        ).fetchone()
        if owner is None:
            raise GiftCardError("not_found", 404)
        user_id = int(owner["user_id"])
        await conn.execute("SELECT id FROM users WHERE id = %s FOR UPDATE", (user_id,))
        row = await (
            await conn.execute(
                "SELECT r.*, i.status AS inventory_status, i.assigned_redemption_id "
                "FROM giftcard_redemptions r JOIN giftcard_inventory i ON i.id = r.inventory_id "
                "WHERE r.id = %s FOR UPDATE OF r, i",
                (redemption_id,),
            )
        ).fetchone()
        if row["status"] == "rejected":
            return {"id": redemption_id, "status": "rejected", "refunded": True}
        if row["status"] != "pending" or row["delivery_started_at"] is not None:
            if row["status"] == "delivering":
                await conn.execute(
                    "UPDATE giftcard_redemptions SET status = 'manual_review', updated_at = now() "
                    "WHERE id = %s",
                    (redemption_id,),
                )
            blocked = True
        elif (
            row["inventory_status"] != "assigned"
            or row["assigned_redemption_id"] != redemption_id
            or row["refunded_at"] is not None
        ):
            await conn.execute(
                "UPDATE giftcard_redemptions SET status = 'manual_review', updated_at = now() "
                "WHERE id = %s",
                (redemption_id,),
            )
            blocked = True
        else:
            try:
                await post_entry(
                    conn,
                    user_id,
                    "units",
                    int(row["coin_cost"]),
                    "giftcard_redemption_refund",
                    f"giftcard:{redemption_id}:refund",
                )
            except (ValueError, RuntimeError):
                raise GiftCardError("ledger_error", 409) from None
            await conn.execute(
                "UPDATE giftcard_redemptions SET status = 'rejected', refunded_at = now(), "
                "rejection_reason = %s, updated_at = now() WHERE id = %s",
                (reason, redemption_id),
            )
            await conn.execute(
                "UPDATE giftcard_inventory SET status = 'available', "
                "assigned_redemption_id = NULL, "
                "assigned_at = NULL WHERE id = %s AND assigned_redemption_id = %s",
                (row["inventory_id"], redemption_id),
            )
    if blocked:
        raise GiftCardError("manual_review_required", 409)
    # В очереди может остаться событие; prepare_delivery(rejected) всегда возвращает None.
    return {"id": redemption_id, "status": "rejected", "refunded": True}


async def admin_redemptions(conn, *, status: str | None = None) -> list[dict]:
    allowed = {"pending", "delivering", "issued", "rejected", "manual_review"}
    if status is not None and status not in allowed:
        raise GiftCardError("invalid_request")
    query = (
        "SELECT id, user_id, sku_id, operator_sku, brand, region, card_currency, "
        "face_value_minor, coin_cost, sandbox, status, created_at, updated_at, "
        "delivery_started_at, delivered_at, refunded_at, rejection_reason "
        "FROM giftcard_redemptions"
    )
    parameters = ()
    if status is not None:
        query += " WHERE status = %s"
        parameters = (status,)
    rows = await (await conn.execute(query + " ORDER BY id DESC LIMIT 200", parameters)).fetchall()
    return [dict(row) for row in rows]


async def request(conn, user, amount=None, region=None, *, sku_id=None, idempotency_key=None):
    """Совместимое имя; старый amount/region не является SKU mapping."""
    if amount is not None or region is not None or sku_id is None or idempotency_key is None:
        raise GiftCardError("legacy_read_only", 409)
    return await redeem(conn, user, sku_id=sku_id, idempotency_key=idempotency_key)


async def approve(conn, withdrawal_id):
    raise GiftCardError("legacy_read_only", 409)


async def reject(conn, withdrawal_id, reason):
    raise GiftCardError("legacy_read_only", 409)


async def unfreeze(conn, withdrawal_id):
    raise GiftCardError("legacy_read_only", 409)


async def finalize(conn, withdrawal_id):
    """Ни внешнего supplier check, ни скрытой комиссии, ни выдачи ambiguous legacy-кода."""
    row = await (
        await conn.execute("SELECT id FROM withdrawals WHERE id = %s", (withdrawal_id,))
    ).fetchone()
    if row is None:
        raise GiftCardError("not_found", 404)
    return {"status": "manual_review", "legacy": True, "read_only": True}
