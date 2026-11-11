"""Зашифрованный склад gift cards и выдача только через доверенный bot worker."""

import csv
import io
import re

from psycopg import errors

from app.giftcards.security import (
    MAX_IMPORT_BYTES,
    MAX_IMPORT_ROWS,
    GiftCardError,
    enabled_mode,
    normalized_code,
    positive_integer,
    reference,
    require_transaction,
    vault,
)

SKU_FIELDS = (
    "id, operator_sku, brand, region, card_currency, face_value_minor, coin_cost, sandbox, active"
)
PUBLIC_ORDER_FIELDS = (
    "id, sku_id, operator_sku, brand, region, card_currency, face_value_minor, "
    "coin_cost, sandbox, status, created_at, updated_at, delivered_at, refunded_at"
)


class DeliveryData(dict):
    """Не выводит код при случайном repr/str payload в журнале worker-а."""

    def __repr__(self):
        return f"DeliveryData(redemption_id={self.get('redemption_id')}, code=<скрыт>)"

    __str__ = __repr__


async def create_sku(
    conn,
    *,
    operator_sku: str,
    brand: str,
    region: str,
    card_currency: str,
    face_value_minor: int,
    coin_cost: int,
    sandbox: bool,
    created_by: int,
) -> dict:
    """Оператор задаёт номинал и цену явно; новые SKU всегда выключены."""
    if not isinstance(operator_sku, str) or not re.fullmatch(
        r"[A-Za-z0-9._:-]{1,80}", operator_sku
    ):
        raise GiftCardError("invalid_request")
    if (brand, region, card_currency) != ("Roblox", "BR", "BRL") or type(sandbox) is not bool:
        raise GiftCardError("invalid_request")
    positive_integer(face_value_minor)
    positive_integer(coin_cost)
    positive_integer(created_by)
    try:
        async with conn.transaction():
            row = await (
                await conn.execute(
                    "INSERT INTO giftcard_skus "
                    "(operator_sku, brand, region, card_currency, face_value_minor, "
                    "coin_cost, sandbox, created_by) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
                    f"RETURNING {SKU_FIELDS}",
                    (
                        operator_sku,
                        brand,
                        region,
                        card_currency,
                        face_value_minor,
                        coin_cost,
                        sandbox,
                        created_by,
                    ),
                )
            ).fetchone()
    except errors.UniqueViolation:
        raise GiftCardError("duplicate_sku", 409) from None
    return dict(row)


async def set_sku_active(conn, *, sku_id: int, active: bool) -> dict:
    positive_integer(sku_id)
    if type(active) is not bool:
        raise GiftCardError("invalid_request")
    async with conn.transaction():
        row = await (
            await conn.execute(
                f"UPDATE giftcard_skus SET active = %s WHERE id = %s RETURNING {SKU_FIELDS}",
                (active, sku_id),
            )
        ).fetchone()
        if row is None:
            raise GiftCardError("not_found", 404)
    return dict(row)


async def list_skus(conn) -> list[dict]:
    rows = await (
        await conn.execute(f"SELECT {SKU_FIELDS} FROM giftcard_skus ORDER BY id DESC LIMIT 500")
    ).fetchall()
    return [dict(row) for row in rows]


async def catalog(conn) -> dict:
    try:
        mode = enabled_mode()
    except GiftCardError:
        return {"enabled": False, "mode": "disabled", "items": []}
    rows = await (
        await conn.execute(
            "SELECT s.id, s.operator_sku, s.brand, s.region, s.card_currency, "
            "s.face_value_minor, s.coin_cost, s.sandbox, "
            "COUNT(i.id) FILTER (WHERE i.status = 'available' "
            "AND i.assigned_redemption_id IS NULL) AS available_count "
            "FROM giftcard_skus s LEFT JOIN giftcard_inventory i ON i.sku_id = s.id "
            "WHERE s.active AND s.sandbox = %s "
            "GROUP BY s.id ORDER BY s.coin_cost, s.id LIMIT 500",
            (mode == "sandbox",),
        )
    ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item["available_count"] = int(item["available_count"])
        item["available"] = item["available_count"] > 0
        items.append(item)
    return {"enabled": bool(items), "mode": mode, "items": items}


def _parse_codes(content: bytes, *, sandbox: bool, code_vault) -> list[tuple[str, str]]:
    if not isinstance(content, bytes):
        raise GiftCardError("invalid_csv")
    if len(content) > MAX_IMPORT_BYTES:
        raise GiftCardError("import_too_large", 413)
    try:
        reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig"), newline=""), strict=True)
        if reader.fieldnames != ["code"]:
            raise GiftCardError("invalid_csv")
        encrypted = []
        seen = set()
        for row in reader:
            if len(encrypted) >= MAX_IMPORT_ROWS:
                raise GiftCardError("import_too_large", 413)
            if set(row) != {"code"} or not row["code"]:
                raise GiftCardError("invalid_csv")
            code = normalized_code(row["code"], sandbox=sandbox)
            fingerprint = code_vault.fingerprint(code)
            if fingerprint in seen:
                raise GiftCardError("duplicate_code", 409)
            seen.add(fingerprint)
            encrypted.append((code_vault.encrypt(code), fingerprint))
    except (csv.Error, UnicodeError):
        raise GiftCardError("invalid_csv") from None
    if not encrypted:
        raise GiftCardError("invalid_csv")
    return encrypted


async def import_csv(
    conn,
    content: bytes,
    *,
    sku_id: int,
    supplier_name: str,
    batch_reference: str,
    provenance_reference: str,
    distribution_agreement_reference: str | None,
    imported_by: int,
) -> dict:
    """Весь CSV или ничего; файл не сохраняется на диск, коды в SQL уже зашифрованы."""
    positive_integer(sku_id)
    positive_integer(imported_by)
    supplier_name = reference(supplier_name, 120)
    batch_reference = reference(batch_reference, 160)
    provenance_reference = reference(provenance_reference, 240)
    if distribution_agreement_reference is not None:
        distribution_agreement_reference = reference(distribution_agreement_reference, 240)
    code_vault = vault()
    try:
        async with conn.transaction():
            sku = await (
                await conn.execute(
                    "SELECT id, sandbox FROM giftcard_skus WHERE id = %s FOR SHARE", (sku_id,)
                )
            ).fetchone()
            if sku is None:
                raise GiftCardError("not_found", 404)
            if not sku["sandbox"] and not distribution_agreement_reference:
                raise GiftCardError("provenance_required")
            encrypted = _parse_codes(content, sandbox=sku["sandbox"], code_vault=code_vault)
            existing = await (
                await conn.execute(
                    "SELECT 1 FROM giftcard_inventory WHERE code_fingerprint = ANY(%s) LIMIT 1",
                    ([fingerprint for _, fingerprint in encrypted],),
                )
            ).fetchone()
            if existing is not None:
                raise GiftCardError("duplicate_code", 409)
            batch = await (
                await conn.execute(
                    "INSERT INTO giftcard_batches "
                    "(sku_id, supplier_name, batch_reference, provenance_reference, "
                    "distribution_agreement_reference, imported_by, imported_count) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                    (
                        sku_id,
                        supplier_name,
                        batch_reference,
                        provenance_reference,
                        distribution_agreement_reference,
                        imported_by,
                        len(encrypted),
                    ),
                )
            ).fetchone()
            for ciphertext, fingerprint in encrypted:
                await conn.execute(
                    "INSERT INTO giftcard_inventory "
                    "(sku_id, batch_id, code_ciphertext, code_fingerprint) VALUES (%s, %s, %s, %s)",
                    (sku_id, batch["id"], ciphertext, fingerprint),
                )
    except errors.UniqueViolation as exc:
        error = (
            "duplicate_code"
            if exc.diag.constraint_name == "giftcard_inventory_code_fingerprint_key"
            else "duplicate_batch"
        )
        raise GiftCardError(error, 409) from None
    return {"batch_id": int(batch["id"]), "imported": len(encrypted)}


async def inventory_stats(conn) -> dict:
    rows = await (
        await conn.execute(
            "SELECT s.sandbox, i.status, COUNT(*) AS count "
            "FROM giftcard_inventory i JOIN giftcard_skus s ON s.id = i.sku_id "
            "GROUP BY s.sandbox, i.status ORDER BY s.sandbox, i.status"
        )
    ).fetchall()
    return {"inventory": [dict(row) for row in rows], "legacy_read_only": True}


async def reserve(conn, *, sku_id: int) -> int:
    """Только блокировка одного кода; вызывается внутри общей транзакции обмена."""
    require_transaction(conn)
    row = await (
        await conn.execute(
            "SELECT id FROM giftcard_inventory WHERE sku_id = %s AND status = 'available' "
            "AND assigned_redemption_id IS NULL ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED",
            (sku_id,),
        )
    ).fetchone()
    if row is None:
        raise GiftCardError("no_inventory", 409)
    return int(row["id"])


async def _owned_delivery(conn, *, redemption_id: int, user_id: int) -> dict:
    require_transaction(conn)
    positive_integer(redemption_id)
    positive_integer(user_id)
    user = await (
        await conn.execute(
            "SELECT id, telegram_id, is_guest FROM users WHERE id = %s FOR UPDATE", (user_id,)
        )
    ).fetchone()
    if not user or user["is_guest"] or not user["telegram_id"] or user["telegram_id"] <= 0:
        raise GiftCardError("owner_mismatch", 403)
    row = await (
        await conn.execute(
            "SELECT r.*, i.status AS inventory_status, i.assigned_redemption_id, "
            "i.code_ciphertext, i.code_fingerprint, i.sku_id AS inventory_sku_id "
            "FROM giftcard_redemptions r JOIN giftcard_inventory i ON i.id = r.inventory_id "
            "WHERE r.id = %s AND r.user_id = %s FOR UPDATE OF r, i",
            (redemption_id, user_id),
        )
    ).fetchone()
    if row is None:
        raise GiftCardError("not_found", 404)
    if row["telegram_id"] != user["telegram_id"]:
        raise GiftCardError("owner_mismatch", 403)
    return dict(row)


def _check_assignment(row: dict) -> None:
    if (
        row["assigned_redemption_id"] != row["id"]
        or row["inventory_sku_id"] != row["sku_id"]
        or row["inventory_status"] not in ("assigned", "issued")
        or row["refunded_at"] is not None
    ):
        raise GiftCardError("manual_review_required", 409)


def _delivery_data(row: dict) -> DeliveryData:
    code = vault().decrypt(row["code_ciphertext"], row["code_fingerprint"], sandbox=row["sandbox"])
    return DeliveryData(
        redemption_id=int(row["id"]),
        user_id=int(row["user_id"]),
        telegram_id=int(row["telegram_id"]),
        bot_id=row["bot_id"],
        origin_bot_id=row["bot_id"],
        code=code,
        brand=row["brand"],
        region=row["region"],
        card_currency=row["card_currency"],
        face_value_minor=int(row["face_value_minor"]),
        coin_cost=int(row["coin_cost"]),
        sandbox=row["sandbox"],
    )


async def prepare_delivery(conn, *, redemption_id: int, user_id: int) -> DeliveryData | None:
    """NO commit. Worker обязан commit marker, закрыть conn, затем отправить код.

    При неопределённом исходе Telegram повторяется этот же заказ, не подбор нового кода.
    """
    row = await _owned_delivery(conn, redemption_id=redemption_id, user_id=user_id)
    if row["status"] in ("issued", "rejected"):
        return None
    if row["status"] not in ("pending", "delivering"):
        raise GiftCardError("manual_review_required", 409)
    mode = enabled_mode()
    if row["sandbox"] != (mode == "sandbox"):
        raise GiftCardError("sku_unavailable", 409)
    _check_assignment(row)
    if row["inventory_status"] != "assigned":
        raise GiftCardError("manual_review_required", 409)
    await conn.execute(
        "UPDATE giftcard_redemptions SET status = 'delivering', "
        "delivery_started_at = COALESCE(delivery_started_at, now()), "
        "delivery_attempts = delivery_attempts + 1, updated_at = now() WHERE id = %s",
        (redemption_id,),
    )
    return _delivery_data(row)


async def _verified_delivery_bot(conn, row: dict, bot_id: int | None) -> dict:
    from app.bot.pool import managed_owner_matches, trusted_main

    selection = "b.bot_id = %s" if bot_id is not None else "b.kind = 'main'"
    parameters = (row["user_id"], row["telegram_id"])
    if bot_id is not None:
        parameters += (bot_id,)
    bot = await (
        await conn.execute(
            "SELECT b.* FROM bot_registry b JOIN bot_private_chats p ON p.bot_id = b.bot_id "
            "WHERE p.user_id = %s AND p.chat_id = %s "
            "AND p.credential_version = b.credential_version AND b.status = 'active' AND "
            + selection
            + " FOR SHARE OF b, p",
            parameters,
        )
    ).fetchone()
    if bot is None:
        raise GiftCardError("owner_mismatch", 403)
    valid = (
        trusted_main(bot)
        if bot["kind"] == "main"
        else (
            managed_owner_matches(bot, row["telegram_id"])
            and bot["owner_user_id"] == row["user_id"]
            and not bot["manager_owner_changed"]
        )
    )
    if not valid:
        raise GiftCardError("owner_mismatch", 403)
    return bot


async def record_delivery(
    conn,
    *,
    redemption_id: int,
    user_id: int,
    telegram_message_id: int,
    bot_id: int | None = None,
) -> dict:
    """NO commit. bot_id — фактический отправитель, не origin; None означает main.

    Для подтверждения нужен активный доверенный бот с подтверждённым private chat
    того же владельца и текущей версией credentials. Первый receipt не перезаписывается.
    """
    positive_integer(telegram_message_id)
    if bot_id is not None:
        positive_integer(bot_id)
    row = await _owned_delivery(conn, redemption_id=redemption_id, user_id=user_id)
    _check_assignment(row)
    if row["status"] == "issued":
        return {"redemption_id": redemption_id, "status": "issued"}
    if row["status"] not in ("delivering", "manual_review") or not row["delivery_started_at"]:
        raise GiftCardError("manual_review_required", 409)
    actual_bot = await _verified_delivery_bot(conn, row, bot_id)
    await conn.execute(
        "UPDATE giftcard_inventory SET status = 'issued', issued_at = COALESCE(issued_at, now()) "
        "WHERE id = %s AND assigned_redemption_id = %s",
        (row["inventory_id"], redemption_id),
    )
    await conn.execute(
        "UPDATE giftcard_redemptions SET status = 'issued', telegram_message_id = %s, "
        "delivered_bot_id = %s, delivered_credential_version = %s, "
        "delivered_at = now(), updated_at = now() WHERE id = %s",
        (
            telegram_message_id,
            actual_bot["bot_id"],
            actual_bot["credential_version"],
            redemption_id,
        ),
    )
    return {"redemption_id": redemption_id, "status": "issued"}


async def list_owned_cards(conn, *, user_id: int, limit: int = 100) -> list[dict]:
    """Метаданные без кода. user_id разрешается доверенным bot caller по Telegram identity."""
    positive_integer(user_id)
    if type(limit) is not int or not 1 <= limit <= 100:
        raise GiftCardError("invalid_request")
    rows = await (
        await conn.execute(
            f"SELECT {PUBLIC_ORDER_FIELDS} FROM giftcard_redemptions "
            "WHERE user_id = %s ORDER BY id DESC LIMIT %s",
            (user_id, limit),
        )
    ).fetchall()
    return [dict(row) for row in rows]


async def get_redemption(conn, *, redemption_id: int, user_id: int) -> dict:
    positive_integer(redemption_id)
    positive_integer(user_id)
    row = await (
        await conn.execute(
            f"SELECT {PUBLIC_ORDER_FIELDS} FROM giftcard_redemptions "
            "WHERE id = %s AND user_id = %s",
            (redemption_id, user_id),
        )
    ).fetchone()
    if row is None:
        raise GiftCardError("not_found", 404)
    return dict(row)


async def get_my_card(conn, *, redemption_id: int, user_id: int) -> dict:
    """Только доверенный /mycards worker и явная transaction; НЕ HTTP/admin API.

    Pending/ambiguous возвращают метаданные без кода. Issued возвращает тот же код владельцу.
    """
    row = await _owned_delivery(conn, redemption_id=redemption_id, user_id=user_id)
    if row["status"] != "issued":
        return {name.strip(): row[name.strip()] for name in PUBLIC_ORDER_FIELDS.split(",")}
    if row["sandbox"] != (enabled_mode() == "sandbox"):
        raise GiftCardError("sku_unavailable", 409)
    _check_assignment(row)
    result = _delivery_data(row)
    result["status"] = "issued"
    return result


async def release_expired(conn) -> int:
    """Реальные и неоднозначные назначения не имеют автоматического TTL возврата."""
    return 0


async def issue(conn, reservation_id: int) -> str:
    raise GiftCardError("legacy_read_only", 409)


async def mark_activated(conn, code: str) -> None:
    raise GiftCardError("legacy_read_only", 409)


async def schedule_verify(conn, code_id: int) -> None:
    """Legacy verifier больше не получает код и не возвращает его в склад."""
    return None
