"""Транзакционный outbox: только ссылки на заказы, никакого plaintext кода или token."""

import json
import re

from psycopg.types.json import Jsonb

from app.bot.security import BotSecurityError, positive_id

_FORBIDDEN_KEYS = frozenset(
    {
        "token",
        "bot_token",
        "code",
        "gift_code",
        "gift_codes",
        "password",
        "secret",
        "init_data",
    }
)


def _safe_tree(value):
    if isinstance(value, dict):
        if any(str(key).lower() in _FORBIDDEN_KEYS for key in value):
            raise BotSecurityError("outbox_secret_forbidden")
        for item in value.values():
            _safe_tree(item)
    elif isinstance(value, list):
        for item in value:
            _safe_tree(item)
    elif isinstance(value, str) and re.search(r"\b[1-9][0-9]{4,}:[A-Za-z0-9_-]{15,}\b", value):
        raise BotSecurityError("outbox_secret_forbidden")


def validate_payload(kind: str, payload: dict):
    if not isinstance(payload, dict):
        raise BotSecurityError("outbox_payload_invalid")
    _safe_tree(payload)
    if kind == "deposit_confirmed":
        if set(payload) != {"coins", "rail", "intent_id"}:
            raise BotSecurityError("outbox_payload_invalid")
        if not positive_id(payload["coins"]) or not isinstance(payload["rail"], str):
            raise BotSecurityError("outbox_payload_invalid")
        if not re.fullmatch(r"[a-z0-9_-]{1,40}", payload["rail"]):
            raise BotSecurityError("outbox_payload_invalid")
        if not isinstance(payload["intent_id"], (str, int)) or isinstance(
            payload["intent_id"], bool
        ):
            raise BotSecurityError("outbox_payload_invalid")
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", str(payload["intent_id"])):
            raise BotSecurityError("outbox_payload_invalid")
    elif kind == "giftcard_delivery":
        if set(payload) != {"redemption_id"} or not positive_id(payload["redemption_id"]):
            raise BotSecurityError("outbox_payload_invalid")
    elif kind == "bot_message":
        # Этот внутренний kind принимает только заранее выбранный шаблон, не произвольный text.
        templates = {
            "start",
            "menu",
            "balance",
            "withdraw",
            "support",
            "paysupport",
            "mycards",
            "managed",
            "managed_opt_in",
            "managed_revoke",
            "disabled",
            "managed_ready",
        }
        base_keys = {"template", "credential_version"}
        allowed_keys = (
            base_keys | {"redemption_id"} if payload.get("template") == "mycards" else base_keys
        )
        if not base_keys <= set(payload) <= allowed_keys or payload["template"] not in templates:
            raise BotSecurityError("outbox_payload_invalid")
        if "redemption_id" in payload and not positive_id(payload["redemption_id"]):
            raise BotSecurityError("outbox_payload_invalid")
        if not positive_id(payload["credential_version"]):
            raise BotSecurityError("outbox_payload_invalid")
    else:
        raise BotSecurityError("outbox_kind_invalid")
    if len(json.dumps(payload)) > 4096:
        raise BotSecurityError("outbox_payload_invalid")


async def enqueue(
    conn, *, kind: str, user_id: int, payload: dict, dedupe_key: str, bot_id: int | None = None
) -> int:
    """NO commit: caller атомарно фиксирует доменную операцию вместе с уведомлением."""
    if not positive_id(user_id) or (bot_id is not None and not positive_id(bot_id)):
        raise BotSecurityError("outbox_recipient_invalid")
    if not isinstance(dedupe_key, str) or not 1 <= len(dedupe_key) <= 200:
        raise BotSecurityError("outbox_dedupe_invalid")
    if kind == "deposit_confirmed":
        # Deposit всегда primary merchant: caller bot_id не меняет получателя/доверие.
        bot_id = None
    validate_payload(kind, payload)
    user = await (
        await conn.execute("SELECT telegram_id, is_guest FROM users WHERE id = %s", (user_id,))
    ).fetchone()
    if not user or user["is_guest"] or not positive_id(user["telegram_id"]):
        raise BotSecurityError("outbox_telegram_user_required")
    row = await (
        await conn.execute(
            "INSERT INTO bot_outbox (kind, user_id, bot_id, payload, dedupe_key) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (dedupe_key) DO NOTHING RETURNING id",
            (kind, user_id, bot_id, Jsonb(payload), dedupe_key),
        )
    ).fetchone()
    if row:
        return int(row["id"])
    row = await (
        await conn.execute(
            "SELECT id, kind, user_id, bot_id, payload FROM bot_outbox WHERE dedupe_key = %s",
            (dedupe_key,),
        )
    ).fetchone()
    if (
        row["kind"] != kind
        or row["user_id"] != user_id
        or row["bot_id"] != bot_id
        or row["payload"] != payload
    ):
        raise BotSecurityError("outbox_dedupe_conflict")
    return int(row["id"])
