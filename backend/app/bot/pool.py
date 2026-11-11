"""Реестр официальных Managed Bots. Импорт plaintext CSV намеренно удалён."""

import secrets

from app.bot.security import (
    BotSecurityError,
    encrypt_secret,
    fingerprint,
    main_bot_id,
    positive_id,
    token_bot_id,
    valid_webhook_secret,
)
from app.config import settings


async def get_bot(conn, bot_id: int, *, lock: bool = False):
    suffix = " FOR UPDATE" if lock else ""
    return await (
        await conn.execute("SELECT * FROM bot_registry WHERE bot_id = %s" + suffix, (bot_id,))
    ).fetchone()


def trusted_main(bot) -> bool:
    try:
        configured_id = main_bot_id()
    except BotSecurityError:
        return False
    return bool(
        bot
        and bot["kind"] == "main"
        and bot["status"] == "active"
        and bot["bot_id"] == configured_id
        and bot["token_fingerprint"] == fingerprint(settings.bot_token)
    )


def managed_owner_matches(bot, telegram_id: int) -> bool:
    return bool(
        bot
        and bot["kind"] == "managed"
        and bot["status"] == "active"
        and positive_id(telegram_id)
        and telegram_id == bot["owner_telegram_id"]
        and bot["owner_user_id"] is not None
        and bot["token_encrypted"]
    )


async def register_main(conn, me: dict):
    bot_id = main_bot_id()
    if not isinstance(me, dict) or me.get("id") != bot_id or me.get("is_bot") is not True:
        raise BotSecurityError("main_identity_mismatch")
    secret = getattr(settings, "telegram_webhook_secret", "")
    if not valid_webhook_secret(secret):
        raise BotSecurityError("webhook_secret_not_configured")
    token_hash = fingerprint(settings.bot_token)
    secret_hash = fingerprint(secret)
    row = await get_bot(conn, bot_id, lock=True)
    if row is not None and row["kind"] != "main":
        raise BotSecurityError("main_registry_conflict")
    return await (
        await conn.execute(
            "INSERT INTO bot_registry (bot_id, kind, username, token_fingerprint, "
            "webhook_secret_encrypted, webhook_secret_hash, status) "
            "VALUES (%s, 'main', %s, %s, %s, %s, 'active') "
            "ON CONFLICT (bot_id) DO UPDATE SET username = EXCLUDED.username, "
            "credential_version = bot_registry.credential_version + CASE WHEN "
            "bot_registry.token_fingerprint IS DISTINCT FROM EXCLUDED.token_fingerprint "
            "OR bot_registry.webhook_secret_hash <> EXCLUDED.webhook_secret_hash "
            "OR bot_registry.status <> 'active' THEN 1 ELSE 0 END, "
            "token_fingerprint = EXCLUDED.token_fingerprint, "
            "webhook_secret_encrypted = EXCLUDED.webhook_secret_encrypted, "
            "webhook_secret_hash = EXCLUDED.webhook_secret_hash, status = 'active', "
            "updated_at = now() RETURNING *",
            (bot_id, me.get("username", ""), token_hash, encrypt_secret(secret), secret_hash),
        )
    ).fetchone()


async def create_intent(conn, *, user: dict, bot_id: int | None = None):
    if user.get("is_guest") or not positive_id(user.get("telegram_id")):
        raise BotSecurityError("primary_telegram_required")
    if not getattr(settings, "managed_bots_enabled", False):
        raise BotSecurityError("managed_bots_disabled")
    if bot_id is not None:
        owned = await get_bot(conn, bot_id, lock=True)
        if (
            not owned
            or owned["kind"] != "managed"
            or owned["owner_telegram_id"] != user["telegram_id"]
        ):
            raise BotSecurityError("managed_owner_mismatch")
    # Блокировка пользователя сериализует два одновременных opt-in.
    await conn.execute("SELECT id FROM users WHERE id = %s FOR UPDATE", (user["id"],))
    await conn.execute(
        "UPDATE bot_managed_intents SET status = 'expired' "
        "WHERE owner_telegram_id = %s AND status = 'pending' AND expires_at <= now()",
        (user["telegram_id"],),
    )
    pending = await (
        await conn.execute(
            "SELECT * FROM bot_managed_intents WHERE owner_telegram_id = %s "
            "AND status = 'pending' FOR UPDATE",
            (user["telegram_id"],),
        )
    ).fetchone()
    if pending and pending["bot_id"] == bot_id:
        return pending
    if pending:
        await conn.execute(
            "UPDATE bot_managed_intents SET status = 'expired' WHERE id = %s", (pending["id"],)
        )
    return await (
        await conn.execute(
            "INSERT INTO bot_managed_intents "
            "(request_id, owner_user_id, owner_telegram_id, bot_id) "
            "VALUES (%s, %s, %s, %s) RETURNING *",
            (secrets.randbelow(2**31 - 1) + 1, user["id"], user["telegram_id"], bot_id),
        )
    ).fetchone()


async def observe_managed_update(conn, *, source: dict, update: dict):
    """Сначала отозвать доверие и commit у вызывающего, затем получать новый token."""
    if not trusted_main(source):
        raise BotSecurityError("manager_source_untrusted")
    event = update.get("managed_bot")
    if not isinstance(event, dict):
        raise BotSecurityError("manager_event_invalid")
    owner, bot = event.get("user"), event.get("bot")
    update_id = update.get("update_id")
    if (
        not isinstance(owner, dict)
        or not isinstance(bot, dict)
        or not positive_id(owner.get("id"))
        or owner.get("is_bot") is not False
        or not positive_id(bot.get("id"))
        or bot.get("is_bot") is not True
        or type(update_id) is not int
        or update_id < 0
        or bot["id"] == source["bot_id"]
    ):
        raise BotSecurityError("manager_event_invalid")
    bot_id, owner_id = bot["id"], owner["id"]
    # Блокировка также защищает INSERT ещё неизвестного бота.
    await conn.execute("SELECT pg_advisory_xact_lock(%s)", (bot_id,))
    existing = await get_bot(conn, bot_id, lock=True)
    if existing and existing["kind"] != "managed":
        raise BotSecurityError("manager_registry_conflict")
    if existing and existing["last_manager_update_id"] is not None:
        if update_id < existing["last_manager_update_id"]:
            return None
        if update_id == existing["last_manager_update_id"]:
            return existing
    changed_owner = existing is not None and existing["owner_telegram_id"] != owner_id
    intent = None
    if changed_owner:
        # Старые разрешения не переносятся новому владельцу: он должен снова opt-in в main.
        await conn.execute(
            "UPDATE bot_managed_intents SET status = 'expired' WHERE status = 'pending' "
            "AND owner_telegram_id IN (%s, %s)",
            (existing["owner_telegram_id"], owner_id),
        )
    else:
        intent = await (
            await conn.execute(
                "SELECT i.* FROM bot_managed_intents i JOIN users u ON u.id = i.owner_user_id "
                "WHERE i.owner_telegram_id = %s AND i.status = 'pending' AND i.expires_at > now() "
                "AND (i.bot_id IS NULL OR i.bot_id = %s) AND u.telegram_id = i.owner_telegram_id "
                "AND u.is_guest = FALSE FOR UPDATE OF i",
                (owner_id, bot_id),
            )
        ).fetchone()
    secret = secrets.token_urlsafe(32)
    return await (
        await conn.execute(
            "INSERT INTO bot_registry (bot_id, kind, username, owner_telegram_id, "
            "webhook_secret_encrypted, webhook_secret_hash, status, last_manager_update_id, "
            "pending_intent_id, manager_owner_changed) "
            "VALUES (%s, 'managed', %s, %s, %s, %s, 'revoked', %s, %s, %s) "
            "ON CONFLICT (bot_id) DO UPDATE SET username = EXCLUDED.username, "
            "owner_telegram_id = EXCLUDED.owner_telegram_id, owner_user_id = NULL, "
            "token_encrypted = NULL, token_fingerprint = NULL, "
            "credential_version = bot_registry.credential_version + 1, "
            "webhook_secret_encrypted = EXCLUDED.webhook_secret_encrypted, "
            "webhook_secret_hash = EXCLUDED.webhook_secret_hash, status = 'revoked', "
            "health_status = 'revoked', last_manager_update_id = EXCLUDED.last_manager_update_id, "
            "pending_intent_id = EXCLUDED.pending_intent_id, "
            "manager_owner_changed = EXCLUDED.manager_owner_changed, updated_at = now() "
            "RETURNING *",
            (
                bot_id,
                bot.get("username", ""),
                owner_id,
                encrypt_secret(secret),
                fingerprint(secret),
                update_id,
                intent["id"] if intent else None,
                changed_owner,
            ),
        )
    ).fetchone()


async def stage_managed_credentials(conn, *, observed: dict, token: str, me: dict):
    bot_id = observed["bot_id"]
    if (
        token_bot_id(token) != bot_id
        or not isinstance(me, dict)
        or me.get("id") != bot_id
        or me.get("is_bot") is not True
    ):
        raise BotSecurityError("managed_identity_mismatch")
    row = await get_bot(conn, bot_id, lock=True)
    if (
        not row
        or row["credential_version"] != observed["credential_version"]
        or row["last_manager_update_id"] != observed["last_manager_update_id"]
        or row["status"] not in {"revoked", "provisioning"}
        or not row["pending_intent_id"]
    ):
        raise BotSecurityError("managed_trust_changed")
    intent = await (
        await conn.execute(
            "SELECT i.* FROM bot_managed_intents i JOIN users u ON u.id = i.owner_user_id "
            "WHERE i.id = %s AND i.status = 'pending' AND i.expires_at > now() "
            "AND i.owner_telegram_id = %s AND u.telegram_id = i.owner_telegram_id "
            "AND u.is_guest = FALSE AND (i.bot_id IS NULL OR i.bot_id = %s) FOR UPDATE OF i",
            (row["pending_intent_id"], row["owner_telegram_id"], bot_id),
        )
    ).fetchone()
    if not intent:
        raise BotSecurityError("managed_intent_missing")
    await conn.execute(
        "UPDATE bot_managed_intents SET bot_id = %s WHERE id = %s", (bot_id, intent["id"])
    )
    return await (
        await conn.execute(
            "UPDATE bot_registry SET token_encrypted = %s, token_fingerprint = %s, "
            "owner_user_id = %s, status = 'provisioning', username = %s, updated_at = now() "
            "WHERE bot_id = %s RETURNING *",
            (
                encrypt_secret(token),
                fingerprint(token),
                intent["owner_user_id"],
                me.get("username", ""),
                bot_id,
            ),
        )
    ).fetchone()


async def activate_managed(conn, staged: dict):
    row = await get_bot(conn, staged["bot_id"], lock=True)
    if (
        not row
        or row["status"] != "provisioning"
        or row["credential_version"] != staged["credential_version"]
    ):
        raise BotSecurityError("managed_trust_changed")
    intent = await (
        await conn.execute(
            "UPDATE bot_managed_intents SET status = 'consumed', bot_id = %s "
            "WHERE id = %s AND owner_telegram_id = %s AND owner_user_id = %s "
            "AND status = 'pending' AND expires_at > now() RETURNING id",
            (
                row["bot_id"],
                row["pending_intent_id"],
                row["owner_telegram_id"],
                row["owner_user_id"],
            ),
        )
    ).fetchone()
    if not intent:
        raise BotSecurityError("managed_intent_missing")
    await conn.execute(
        "UPDATE bot_registry SET status = 'active', manager_owner_changed = FALSE, "
        "health_status = 'ok', last_error_code = NULL, updated_at = now() WHERE bot_id = %s",
        (row["bot_id"],),
    )


async def revoke_managed(conn, *, bot_id: int, owner_telegram_id: int):
    row = await get_bot(conn, bot_id, lock=True)
    if not row or row["kind"] != "managed" or row["owner_telegram_id"] != owner_telegram_id:
        raise BotSecurityError("managed_owner_mismatch")
    secret = secrets.token_urlsafe(32)
    await conn.execute(
        "UPDATE bot_registry SET status = 'revoked', token_encrypted = NULL, "
        "token_fingerprint = NULL, credential_version = credential_version + 1, "
        "webhook_secret_encrypted = %s, webhook_secret_hash = %s, pending_intent_id = NULL, "
        "health_status = 'revoked', updated_at = now() WHERE bot_id = %s",
        (encrypt_secret(secret), fingerprint(secret), bot_id),
    )
    await conn.execute(
        "UPDATE bot_managed_intents SET status = 'expired' "
        "WHERE owner_telegram_id = %s AND status = 'pending'",
        (owner_telegram_id,),
    )


async def confirm_private_chat(conn, *, bot: dict, user: dict, chat_id: int):
    if user.get("is_guest") or not positive_id(chat_id) or chat_id != user["telegram_id"]:
        raise BotSecurityError("private_chat_required")
    if bot["kind"] == "managed" and (
        not managed_owner_matches(bot, user["telegram_id"]) or bot["owner_user_id"] != user["id"]
    ):
        raise BotSecurityError("managed_owner_mismatch")
    if bot["kind"] == "main" and not trusted_main(bot):
        raise BotSecurityError("main_source_untrusted")
    await conn.execute(
        "INSERT INTO bot_private_chats (bot_id, user_id, chat_id, credential_version) "
        "VALUES (%s, %s, %s, %s) ON CONFLICT (bot_id, user_id) DO UPDATE "
        "SET chat_id = EXCLUDED.chat_id, credential_version = EXCLUDED.credential_version, "
        "confirmed_at = now()",
        (bot["bot_id"], user["id"], chat_id, bot["credential_version"]),
    )
