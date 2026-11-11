"""Уведомления: секреты подгружаются только непосредственно для проверенного получателя."""

import re

from app.bot.client import TelegramAPIError
from app.bot.dispatcher import FeatureUnavailable, optional_service
from app.bot.outbox import enqueue, validate_payload
from app.bot.pool import managed_owner_matches, trusted_main
from app.bot.security import BotSecurityError, decrypt_secret, positive_id
from app.bot.setup import main_bot_link, webapp_keyboard
from app.config import settings
from app.db import get_conn


class DeliveryUnavailable(RuntimeError):
    pass


async def resolve_destination(conn, *, job: dict):
    user = await (
        await conn.execute("SELECT * FROM users WHERE id = %s", (job["user_id"],))
    ).fetchone()
    if not user or user["is_guest"] or not positive_id(user["telegram_id"]):
        raise BotSecurityError("delivery_owner_invalid")
    rows = await (
        await conn.execute(
            "SELECT b.*, c.chat_id, c.credential_version AS chat_credential_version "
            "FROM bot_registry b JOIN bot_private_chats c ON c.bot_id = b.bot_id "
            "WHERE c.user_id = %s AND c.chat_id = %s AND b.status = 'active' "
            "AND c.credential_version = b.credential_version "
            "ORDER BY (b.bot_id = %s) DESC NULLS LAST, "
            "(b.kind = 'managed') DESC, c.confirmed_at DESC",
            (user["id"], user["telegram_id"], job["bot_id"]),
        )
    ).fetchall()
    for row in rows:
        bot = dict(row)
        if bot["kind"] == "main":
            if not trusted_main(bot):
                continue
        elif (
            not getattr(settings, "managed_bots_enabled", False)
            or not managed_owner_matches(bot, user["telegram_id"])
            or bot["owner_user_id"] != user["id"]
        ):
            continue
        if job["kind"] == "deposit_confirmed" and bot["kind"] != "main":
            continue
        if job["kind"] == "bot_message":
            if bot["bot_id"] != job["bot_id"]:
                continue
            if job["payload"]["credential_version"] != bot["credential_version"]:
                raise BotSecurityError("delivery_credential_revoked")
        return dict(user), bot
    raise DeliveryUnavailable("confirmed_private_chat_required")


async def _recheck_destination(*, user_id: int, bot: dict):
    # Только свежая registry+chat проверка; отсутствует network внутри transaction.
    async with get_conn() as conn:
        current = await (
            await conn.execute(
                "SELECT b.*, c.chat_id FROM bot_registry b "
                "JOIN bot_private_chats c ON c.bot_id = b.bot_id "
                "JOIN users u ON u.id = c.user_id WHERE b.bot_id = %s AND c.user_id = %s "
                "AND b.credential_version = %s AND c.credential_version = b.credential_version "
                "AND b.status = 'active' AND u.is_guest = FALSE AND u.telegram_id = c.chat_id",
                (bot["bot_id"], user_id, bot["credential_version"]),
            )
        ).fetchone()
    if not current or current["chat_id"] != bot["chat_id"]:
        raise BotSecurityError("delivery_credential_revoked")
    if current["kind"] == "main":
        if not trusted_main(current):
            raise BotSecurityError("main_source_untrusted")
    elif (
        not getattr(settings, "managed_bots_enabled", False)
        or not managed_owner_matches(current, bot["chat_id"])
        or current["owner_user_id"] != user_id
    ):
        raise BotSecurityError("delivery_owner_invalid")
    return current


async def _send(client, *, user_id: int, bot: dict, message: dict, protected: bool = False) -> int:
    current = await _recheck_destination(user_id=user_id, bot=bot)
    token = (
        settings.bot_token
        if current["kind"] == "main"
        else decrypt_secret(current["token_encrypted"])
    )
    response = await client.call(
        token, "sendMessage", chat_id=bot["chat_id"], protect_content=protected, **message
    )
    if not isinstance(response, dict) or not positive_id(response.get("message_id")):
        # Отсутствующий receipt неоднозначен: retry только того же сообщения/назначенного кода.
        raise TelegramAPIError("send_receipt_missing", retryable=True)
    return response["message_id"]


def _card_message(card: dict) -> dict:
    code = card.get("code")
    if not isinstance(code, str) or not code:
        raise BotSecurityError("giftcard_code_missing")
    prefix = "TESTE — sem valor real.\n" if card["sandbox"] else ""
    return {
        "text": (
            f"{prefix}Seu gift card {card['brand']} — {card['region']}\n"
            f"Pedido #{card['redemption_id']}\nCódigo: {code}\n\n"
            "Guarde este código em segurança. /mycards mostra novamente o mesmo cartão.\n"
            "Não compartilhe códigos com o suporte."
        )
    }


async def _managed_message(conn, *, user: dict, bot: dict, template: str) -> dict:
    link = main_bot_link()
    if bot["kind"] == "managed":
        result = {
            "text": "Gerencie ou revogue seu bot pessoal no bot principal oficial. "
            "Nunca envie senha, sessão do Telegram ou token para o suporte."
        }
        if link:
            result["reply_markup"] = {"inline_keyboard": [[{"text": "Bot principal", "url": link}]]}
        return result
    enabled = getattr(settings, "managed_bots_enabled", False)
    if not enabled or template == "disabled":
        return {"text": "A criação de bots pessoais está desativada neste ambiente. Use /menu."}
    if template == "managed_revoke":
        return {
            "text": "Acesso revogado. As sessões deste bot foram encerradas. "
            "Sua conta, saldo e gift cards continuam com você no bot principal."
        }
    if template == "managed_opt_in":
        intent = await (
            await conn.execute(
                "SELECT request_id FROM bot_managed_intents WHERE owner_user_id = %s "
                "AND owner_telegram_id = %s AND status = 'pending' AND expires_at > now()",
                (user["id"], user["telegram_id"]),
            )
        ).fetchone()
        if not intent:
            return {"text": "A autorização expirou. Use /createbot para autorizar novamente."}
        return {
            "text": "Criação opcional pelo Telegram. Toque abaixo para escolher nome e usuário. "
            "O nome escolhido por você será mantido. O bot atenderá somente sua conta. "
            "Para reconectar, confirme o bot existente no fluxo oficial após /reconnectbot ID.\n"
            "Não envie senha, sessão ou token. Autorização válida por 15 minutos.",
            "reply_markup": {
                "keyboard": [
                    [
                        {
                            "text": "Criar meu bot pessoal",
                            "request_managed_bot": {
                                "request_id": intent["request_id"],
                                "suggested_name": "Meu WINDROP",
                                "suggested_username": f"windrop_{user['telegram_id']}_bot",
                            },
                        }
                    ]
                ],
                "resize_keyboard": True,
                "one_time_keyboard": True,
            },
        }
    bots = await (
        await conn.execute(
            "SELECT bot_id, username, status FROM bot_registry WHERE kind = 'managed' "
            "AND owner_telegram_id = %s ORDER BY bot_id",
            (user["telegram_id"],),
        )
    ).fetchall()
    lines = ["Seu bot pessoal WINDROP" if template != "managed_ready" else "Bot pessoal conectado."]
    if not bots:
        lines.append("Você ainda não conectou um bot pessoal.")
    for personal in bots[:15]:
        state = {"active": "ativo", "revoked": "acesso revogado", "provisioning": "configurando"}[
            personal["status"]
        ]
        lines.append(f"@{personal['username']} — {state} — ID {personal['bot_id']}")
    lines.extend(
        [
            "",
            "Criação opcional: /createbot",
            "Reconectar após nova autorização: /reconnectbot ID",
            "Revogar acesso e sessões: /revokebot ID",
            "Pagamentos são confirmados somente no bot principal.",
            "O dono conhece o token do bot pessoal; "
            "ele não pode acessar contas de outros jogadores.",
        ]
    )
    return {"text": "\n".join(lines)}


async def _command_message(conn, *, job: dict, user: dict, bot: dict) -> tuple[dict, bool]:
    template = job["payload"]["template"]
    if template in {"managed", "managed_opt_in", "managed_ready", "managed_revoke", "disabled"}:
        return await _managed_message(conn, user=user, bot=bot, template=template), False
    if template == "balance":
        return {
            "text": f"Seus Coins: {user['balance_units']}\n"
            f"Bônus para jogar: {user['balance_freebets']}\n"
            "Bônus não podem ser trocados por gift cards."
        }, False
    if template in {"support", "paysupport"}:
        username = getattr(settings, "support_username", "").lstrip("@")
        contact = (
            f"@{username}"
            if re.fullmatch(r"[A-Za-z0-9_]{5,32}", username)
            else "o suporte no aplicativo"
        )
        text = (
            f"Precisa de ajuda? Fale com {contact}. "
            "Nunca envie senha, sessão, token ou código de gift card."
        )
        if template == "paysupport":
            text = (
                f"Ajuda com pagamentos: {contact}. Informe somente o ID do pedido. "
                "Pagamentos e reembolsos são tratados pelo bot principal oficial."
            )
        return {"text": text}, False
    if template == "withdraw":
        return {
            "text": "Troque seus Coins por gift cards disponíveis no catálogo. "
            "Confira região, nominal e custo antes de confirmar. Não é saque em dinheiro.",
            "reply_markup": webapp_keyboard(bot, "withdraw"),
        }, False
    if template == "mycards":
        try:
            service = optional_service("app.giftcards.service", "list_owned_cards", "get_my_card")
        except FeatureUnavailable:
            return {
                "text": "A consulta de gift cards está indisponível neste ambiente. /support"
            }, False
        redemption_id = job["payload"].get("redemption_id")
        if redemption_id is not None:
            card = await service.get_my_card(conn, redemption_id=redemption_id, user_id=user["id"])
            if card.get("status") == "issued" and card.get("code"):
                if (
                    card.get("telegram_id") != user["telegram_id"]
                    or card.get("user_id") != user["id"]
                ):
                    raise BotSecurityError("delivery_owner_invalid")
                return _card_message(card), True
            if card.get("status") in {"pending", "delivering"}:
                await enqueue(
                    conn,
                    kind="giftcard_delivery",
                    user_id=user["id"],
                    bot_id=bot["bot_id"],
                    payload={"redemption_id": redemption_id},
                    dedupe_key=f"mycards_delivery:{redemption_id}:{job['id']}",
                )
            return {
                "text": f"Pedido #{redemption_id}: a entrega ainda não foi concluída. "
                "O mesmo cartão será enviado quando estiver disponível. /support"
            }, False
        cards = await service.list_owned_cards(conn, user_id=user["id"], limit=20)
        if not cards:
            return {
                "text": "Você ainda não tem gift cards. Use /withdraw para ver o catálogo."
            }, False
        statuses = {
            "pending": "pendente",
            "delivering": "em entrega",
            "issued": "entregue",
            "manual_review": "em análise",
            "rejected": "cancelado",
        }
        lines = ["Seus gift cards:"]
        for card in cards:
            state = statuses.get(card["status"], "em análise")
            lines.append(f"#{card['id']} — {card['brand']} / {card['region']} — {state}")
        lines.append(
            "Para consultar seu código, envie /mycards ID. Sempre mostramos o mesmo cartão."
        )
        return {"text": "\n".join(lines)}, False
    text = "Bem-vindo à WINDROP! Acompanhe seus Coins, jogue e troque recompensas por gift cards."
    if template == "menu":
        text = "Menu WINDROP: /balance · /withdraw · /mycards · /mybot · /support · /paysupport"
    return {"text": text, "reply_markup": webapp_keyboard(bot)}, False


async def deliver_notification(client, *, job: dict) -> tuple[int | None, int | None]:
    validate_payload(job["kind"], job["payload"])
    gift_service = None
    gift = None
    async with get_conn() as conn, conn.transaction():
        user, bot = await resolve_destination(conn, job=job)
        if job["kind"] == "giftcard_delivery":
            gift_service = optional_service(
                "app.giftcards.service", "prepare_delivery", "record_delivery"
            )
            gift = await gift_service.prepare_delivery(
                conn, redemption_id=job["payload"]["redemption_id"], user_id=user["id"]
            )
            if gift is None:
                return None, None
            if gift.get("telegram_id") != user["telegram_id"] or gift.get("user_id") != user["id"]:
                raise BotSecurityError("delivery_owner_invalid")
            message, protected = _card_message(gift), True
        elif job["kind"] == "deposit_confirmed":
            message = {
                "text": f"Depósito confirmado: {job['payload']['coins']} Coins. "
                f"Pedido {job['payload']['intent_id']}. /balance"
            }
            protected = False
        else:
            message, protected = await _command_message(conn, job=job, user=user, bot=bot)
    # Важно: prepare_delivery marker уже COMMIT и connection полностью отпущен до Telegram.
    message_id = await _send(
        client, user_id=user["id"], bot=bot, message=message, protected=protected
    )
    if gift is not None:
        async with get_conn() as conn, conn.transaction():
            await gift_service.record_delivery(
                conn,
                redemption_id=gift["redemption_id"],
                user_id=user["id"],
                telegram_message_id=message_id,
                bot_id=bot["bot_id"],
            )
    return message_id, bot["bot_id"]
