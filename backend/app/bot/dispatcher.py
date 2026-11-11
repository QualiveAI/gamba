"""Raw Update dispatcher с явными границами primary/managed, без aiogram imports."""

import importlib
import re

from app.bot.inbox import event_allowed
from app.bot.outbox import enqueue
from app.bot.pool import (
    activate_managed,
    confirm_private_chat,
    create_intent,
    get_bot,
    observe_managed_update,
    revoke_managed,
    stage_managed_credentials,
    trusted_main,
)
from app.bot.security import BotSecurityError, positive_id
from app.bot.setup import configure_bot
from app.bot.users import apply_start_attribution, ensure_telegram_user
from app.config import settings
from app.db import get_conn


class FeatureUnavailable(RuntimeError):
    pass


class SettlementDeferred(RuntimeError):
    pass


def optional_service(module: str, *names: str):
    try:
        service = importlib.import_module(module)
    except ImportError:
        raise FeatureUnavailable("feature_disabled") from None
    if not all(callable(getattr(service, name, None)) for name in names):
        raise FeatureUnavailable("feature_disabled")
    return service


async def _process_manager(client, source: dict, update: dict):
    # observe сначала commit: при сбое getManagedBotToken старые сессии уже отозваны.
    async with get_conn() as conn, conn.transaction():
        observed = await observe_managed_update(conn, source=source, update=update)
    if not observed or observed["status"] == "active":
        return
    if not getattr(settings, "managed_bots_enabled", False) or not observed["pending_intent_id"]:
        return
    if getattr(settings, "bot_mode", "disabled") != "webhook":
        return
    token = await client.call(settings.bot_token, "getManagedBotToken", user_id=observed["bot_id"])
    if not isinstance(token, str):
        raise BotSecurityError("managed_token_response_invalid")
    me = await client.call(token, "getMe")
    async with get_conn() as conn, conn.transaction():
        staged = await stage_managed_credentials(conn, observed=observed, token=token, me=me)
    await client.call(
        settings.bot_token,
        "setManagedBotAccessSettings",
        user_id=staged["bot_id"],
        is_access_restricted=True,
        added_user_ids=[],
    )
    await configure_bot(client, bot=staged, token=token, webhook=True)
    async with get_conn() as conn, conn.transaction():
        await activate_managed(conn, staged)
        await enqueue(
            conn,
            kind="bot_message",
            user_id=staged["owner_user_id"],
            bot_id=source["bot_id"],
            payload={
                "template": "managed_ready",
                "credential_version": source["credential_version"],
            },
            dedupe_key=f"managed_ready:{staged['bot_id']}:{staged['credential_version']}",
        )


async def _payment_user(conn, telegram_id: int):
    # Invoice уже связан с существующим пользователем. Не берём users row lock
    # до payment service: единый порядок settlement — intent -> event -> users.
    user = await (
        await conn.execute(
            "SELECT id, telegram_id, is_guest FROM users "
            "WHERE telegram_id = %s AND is_guest = FALSE",
            (telegram_id,),
        )
    ).fetchone()
    if not user:
        raise BotSecurityError("payment_owner_unknown")
    return dict(user)


async def _precheckout(client, bot: dict, query: dict):
    if not trusted_main(bot) or not isinstance(query, dict):
        return
    sender = query.get("from")
    if not isinstance(sender, dict) or not positive_id(sender.get("id")) or sender.get("is_bot"):
        return
    query_id = query.get("id")
    if not isinstance(query_id, str) or not 1 <= len(query_id) <= 200:
        return
    okay = False
    try:
        service = optional_service("app.payments.stars", "validate_stars_precheckout")
        async with get_conn() as conn, conn.transaction():
            user = await _payment_user(conn, sender["id"])
            okay = (
                await service.validate_stars_precheckout(
                    conn,
                    user_id=user["id"],
                    invoice_payload=query.get("invoice_payload"),
                    currency=query.get("currency"),
                    total_amount=query.get("total_amount"),
                )
                is True
            )
    except Exception:
        # Покупку отклоняем fail-closed, не переносим ошибки с payload/PII в Bot API.
        okay = False
    params = {"pre_checkout_query_id": query_id, "ok": okay}
    if not okay:
        params["error_message"] = (
            "Pagamento indisponível. Tente novamente no bot principal ou use /paysupport."
        )
    await client.call(settings.bot_token, "answerPreCheckoutQuery", **params)


async def _successful_payment(conn, bot: dict, user: dict, payment: dict):
    if not trusted_main(bot) or not isinstance(payment, dict):
        raise BotSecurityError("merchant_source_required")
    service = optional_service("app.payments.stars", "settle_stars_payment")
    result = await service.settle_stars_payment(
        conn,
        user_id=user["id"],
        invoice_payload=payment.get("invoice_payload"),
        currency=payment.get("currency"),
        total_amount=payment.get("total_amount"),
        charge_id=payment.get("telegram_payment_charge_id"),
    )
    return getattr(result, "status", None) in {"processed", "duplicate"}


async def dispatch_update(client, *, bot: dict, update: dict):
    if not event_allowed(bot, update):
        return
    if "managed_bot" in update:
        await _process_manager(client, bot, update)
        return
    if "pre_checkout_query" in update:
        await _precheckout(client, bot, update["pre_checkout_query"])
        return
    message = update.get("message")
    if not isinstance(message, dict):
        return
    sender, chat = message.get("from"), message.get("chat")
    if (
        not isinstance(sender, dict)
        or not isinstance(chat, dict)
        or not positive_id(sender.get("id"))
        or sender.get("is_bot") is not False
        or chat.get("type") != "private"
        or chat.get("id") != sender["id"]
        or message.get("sender_chat")
    ):
        return
    text = message.get("text", "")
    text = text if isinstance(text, str) else ""
    match = re.fullmatch(r"/([a-z]+)(?:@([A-Za-z0-9_]+))?(?:\s+([^\n]{1,128}))?\s*", text.strip())
    if "successful_payment" in message:
        async with get_conn() as conn, conn.transaction():
            current = await get_bot(conn, bot["bot_id"], lock=True)
            if (
                not current
                or current["credential_version"] != bot["credential_version"]
                or not trusted_main(current)
            ):
                raise BotSecurityError("merchant_source_required")
            user = await _payment_user(conn, sender["id"])
            settled = await _successful_payment(conn, current, user, message["successful_payment"])
            if settled:
                # Private-chat FK также может блокировать users, поэтому только после intent.
                await confirm_private_chat(conn, bot=current, user=user, chat_id=chat["id"])
        # Сохраняем диагностический payment event, но не маркируем Telegram inbox done.
        if not settled:
            raise SettlementDeferred("stars_settlement_pending")
        return
    async with get_conn() as conn, conn.transaction():
        current = await get_bot(conn, bot["bot_id"], lock=True)
        if (
            not current
            or current["credential_version"] != bot["credential_version"]
            or not event_allowed(current, update)
        ):
            return
        if current["kind"] == "main":
            user = await ensure_telegram_user(
                conn, telegram_id=sender["id"], username=sender.get("username", "")
            )
        else:
            user = await (
                await conn.execute(
                    "SELECT * FROM users WHERE id = %s AND telegram_id = %s AND is_guest = FALSE",
                    (current["owner_user_id"], sender["id"]),
                )
            ).fetchone()
            if not user:
                raise BotSecurityError("managed_owner_unbound")
            user = dict(user)
        await confirm_private_chat(conn, bot=current, user=user, chat_id=chat["id"])
        # Gifts/Stars вне конкретного успешного main merchant payload не дают баланса.
        if not match:
            return
        command, target, arg = match.groups()
        if target and target.lower() != current["username"].lower():
            return
        arg = (arg or "").strip()
        template = (
            command
            if command
            in {"start", "menu", "balance", "withdraw", "support", "paysupport", "mycards"}
            else "menu"
        )
        if command == "start" and current["kind"] == "main":
            await apply_start_attribution(
                conn, user=user, source_bot_id=current["bot_id"], payload=arg
            )
            if arg == "managed":
                template = "managed"
        if command in {"mybot", "createbot", "reconnectbot", "revokebot"}:
            template = "managed"
            if command != "mybot" and current["kind"] == "main":
                if not getattr(settings, "managed_bots_enabled", False) or (
                    command != "revokebot"
                    and getattr(settings, "bot_mode", "disabled") != "webhook"
                ):
                    template = "disabled"
                elif command == "createbot":
                    await create_intent(conn, user=user)
                    template = "managed_opt_in"
                elif command in {"reconnectbot", "revokebot"} and re.fullmatch(
                    r"[1-9][0-9]{0,18}", arg
                ):
                    personal_id = int(arg)
                    if not positive_id(personal_id):
                        raise BotSecurityError("managed_bot_id_invalid")
                    if command == "reconnectbot":
                        await create_intent(conn, user=user, bot_id=personal_id)
                        template = "managed_opt_in"
                    else:
                        await revoke_managed(
                            conn, bot_id=personal_id, owner_telegram_id=sender["id"]
                        )
                        template = "managed_revoke"
        payload = {"template": template, "credential_version": current["credential_version"]}
        if command == "mycards" and re.fullmatch(r"[1-9][0-9]{0,18}", arg):
            redemption_id = int(arg)
            if positive_id(redemption_id):
                payload["redemption_id"] = redemption_id
        await enqueue(
            conn,
            kind="bot_message",
            user_id=user["id"],
            bot_id=current["bot_id"],
            payload=payload,
            dedupe_key=f"command:{current['bot_id']}:{update['update_id']}",
        )
