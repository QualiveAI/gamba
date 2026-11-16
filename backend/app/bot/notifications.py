"""Уведомления: секреты подгружаются только непосредственно для проверенного получателя."""

import re

from app.bot.client import TelegramAPIError
from app.bot.dispatcher import FeatureUnavailable, optional_service
from app.bot.outbox import enqueue, validate_payload
from app.bot.pool import create_intent, managed_owner_matches, trusted_main
from app.bot.security import BotSecurityError, decrypt_secret, positive_id
from app.bot.setup import main_bot_link, webapp_keyboard
from app.config import settings
from app.db import get_conn
from app.payments.stars import create_invoice_for_intent
from core.contracts.payment import PaymentError
from core.payments.intents import create_intent as create_payment_intent
from core.payments.quotes import create_quote


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


async def _pending_intent(conn, *, user: dict):
    return await (
        await conn.execute(
            "SELECT request_id FROM bot_managed_intents WHERE owner_user_id = %s "
            "AND owner_telegram_id = %s AND status = 'pending' AND expires_at > now()",
            (user["id"], user["telegram_id"]),
        )
    ).fetchone()


async def _active_personal_bot(conn, *, user: dict):
    return await (
        await conn.execute(
            "SELECT bot_id, username FROM bot_registry WHERE kind = 'managed' "
            "AND owner_telegram_id = %s AND status = 'active' ORDER BY bot_id LIMIT 1",
            (user["telegram_id"],),
        )
    ).fetchone()


def _request_bot_keyboard(intent, user: dict, *, label: str, suggested_name: str = "Meu WINDROP"):
    # Имя и username подставляем сами: игрок только подтверждает, а не выбирает.
    return {
        "keyboard": [
            [
                {
                    "text": label,
                    "request_managed_bot": {
                        "request_id": intent["request_id"],
                        "suggested_name": suggested_name,
                        "suggested_username": f"windrop_{user['telegram_id']}_bot",
                    },
                }
            ]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": True,
    }


async def _managed_message(conn, *, user: dict, bot: dict, template: str) -> dict:
    link = main_bot_link()
    if bot["kind"] == "managed":
        # Это личный бот игрока: здесь и открывается Mini App.
        if template == "managed_ready":
            return {
                "text": (
                    "Seu bot pessoal WINDROP está pronto! 🎉\n\n"
                    "Toque em «Abrir WINDROP» para abrir caixas, jogar os mini-jogos e trocar "
                    "seus Coins por gift cards. Avisos e códigos de gift card chegam aqui, "
                    "neste bot.\n\n"
                    "Suporte: /support"
                ),
                "reply_markup": webapp_keyboard(bot),
            }
        result = {
            "text": "Bem-vindo à WINDROP!\n\n"
            "Toque em «Abrir WINDROP» para abrir caixas, jogar e trocar Coins por gift cards. "
            "Códigos de gift card chegam neste bot.\n\n"
            "Suporte: /support · Pagamentos: /paysupport (somente no bot principal).",
            "reply_markup": webapp_keyboard(bot),
        }
        if link:
            result["reply_markup"]["inline_keyboard"].append(
                [{"text": "Bot principal", "url": link}]
            )
        return result
    enabled = getattr(settings, "managed_bots_enabled", False)
    if not enabled or template == "disabled":
        if template in {"start", "menu"}:
            # dev/test: личных ботов нет, поэтому показываем Mini App главного бота.
            return {
                "text": "Bem-vindo à WINDROP! Seus Coins, caixas, mini-jogos e gift cards.",
                "reply_markup": webapp_keyboard(bot),
            }
        return {"text": "A criação de bots pessoais está desativada neste ambiente. Use /menu."}
    if template == "managed_revoke":
        return {
            "text": "Acesso revogado. As sessões deste bot foram encerradas. "
            "Sua conta, saldo e gift cards continuam com você no bot principal."
        }
    if template == "managed_opt_in":
        intent = await _pending_intent(conn, user=user)
        if not intent:
            return {"text": "A autorização expirou. Use /createbot para autorizar novamente."}
        return {
            "text": "Criação opcional pelo Telegram. Toque abaixo para escolher nome e usuário. "
            "O nome escolhido por você será mantido. O bot atenderá somente sua conta. "
            "Para reconectar, confirme o bot existente no fluxo oficial após /reconnectbot ID.\n"
            "Não envie senha, sessão ou token. Autorização válida por 15 minutos.",
            "reply_markup": _request_bot_keyboard(intent, user, label="Criar meu bot pessoal"),
        }
    if template == "managed_ready":
        # Бот создан: в главном чате остаётся только ссылка на личного бота — играть
        # нужно там, потому что initData подписывает именно он.
        personal = await _active_personal_bot(conn, user=user)
        if personal:
            return {
                "text": f"Seu bot pessoal está pronto: @{personal['username']}\n"
                "Abra-o e toque em «Abrir WINDROP» para jogar.",
                "reply_markup": {
                    "inline_keyboard": [
                        [{"text": "Abrir meu bot", "url": f"https://t.me/{personal['username']}"}]
                    ]
                },
            }
        return {"text": "Seu bot pessoal foi criado. Use /mybot para ver o usuário dele."}
    if template in {"start", "menu"}:
        # Главный бот — вход и оплата: сначала личный бот, потом игра.
        personal = await _active_personal_bot(conn, user=user)
        if personal:
            return {
                "text": (
                    f"Bem-vindo de volta à WINDROP!\n\nSeu bot pessoal: @{personal['username']}\n"
                    "Abra-o e toque em «Abrir WINDROP» para jogar. Gift cards chegam lá."
                ),
                "reply_markup": {
                    "inline_keyboard": [
                        [{"text": "Abrir meu bot", "url": f"https://t.me/{personal['username']}"}]
                    ]
                },
            }
        intent = await _pending_intent(conn, user=user) or await create_intent(conn, user=user)
        return {
            "text": (
                "Bem-vindo à WINDROP! 🎉\n\n"
                "Aqui você acompanha seus Coins, abre caixas, joga mini-jogos e troca as "
                "recompensas por gift cards.\n\n"
                "Como começar:\n"
                "1. Toque em «Jogar» — o Telegram cria seu bot pessoal com o seu nome em "
                "segundos, você só confirma.\n"
                "2. Abra o seu bot e toque em «Abrir WINDROP».\n"
                "3. Gift cards e avisos chegam no seu bot pessoal.\n\n"
                "Suporte: /support · Pagamentos: /paysupport"
            ),
            "reply_markup": _request_bot_keyboard(intent, user, label="Jogar"),
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


def _deposit_deep_link() -> str | None:
    username = getattr(settings, "bot_username", "").lstrip("@")
    if not re.fullmatch(r"[A-Za-z0-9_]{5,32}", username):
        return None
    return f"https://t.me/{username}?start=deposit"


def _coins_label(coins: int) -> str:
    return f"{coins:,}".replace(",", ".")


async def _deposit_intent(conn, *, user: dict, coins: int):
    """Живой intent на эту сумму переиспользуем: /deposit не плодит счета."""
    row = await (
        await conn.execute(
            "SELECT id FROM payment_intents WHERE user_id = %s AND method = 'stars' "
            "AND status = 'pending' AND coins = %s AND expires_at > now() "
            "ORDER BY created_at DESC LIMIT 1",
            (user["id"], coins),
        )
    ).fetchone()
    if row:
        return row["id"]
    quote = await create_quote(conn, user=user, coins=coins, method="stars")
    intent = await create_payment_intent(
        conn=conn,
        user=user,
        tenant="default",
        quote_id=quote.id,
        idempotency_key=f"bot-deposit-{quote.id}",
    )
    return intent.id


async def _deposit_message(conn, *, user: dict, bot: dict) -> dict:
    """Пополнение прямо в чате: Mini App для этого не нужен."""
    if bot["kind"] != "main":
        link = main_bot_link()
        result = {
            "text": "Adicionar Coins é feito no bot principal oficial, por Telegram Stars. "
            "Os Coins caem na mesma conta."
        }
        if link:
            result["reply_markup"] = {"inline_keyboard": [[{"text": "Bot principal", "url": link}]]}
        return result
    rows = []
    for coins in getattr(settings, "deposit_presets_list", []):
        try:
            intent_id = await _deposit_intent(conn, user=user, coins=coins)
            invoice = await create_invoice_for_intent(conn, user=user, intent_id=intent_id)
        except PaymentError:
            continue
        link = invoice.get("invoice_link")
        if not link:
            continue
        stars = invoice.get("stars_amount") or invoice.get("provider_amount_atomic")
        label = f"{_coins_label(coins)} Coins" + (f" — {stars} ⭐" if stars else "")
        rows.append([{"text": label, "url": link}])
    if not rows:
        return {
            "text": "Pagamentos estão desativados no momento. Tente mais tarde ou use /support."
        }
    return {
        "text": (
            "Adicionar Coins com Telegram Stars.\n"
            "O Telegram confirma o pagamento, e os Coins caem na conta na hora.\n"
            "Escolha o pacote:"
        ),
        "reply_markup": {"inline_keyboard": rows},
    }


async def _command_message(conn, *, job: dict, user: dict, bot: dict) -> tuple[dict, bool]:
    template = job["payload"]["template"]
    if template in {
        "start",
        "menu",
        "managed",
        "managed_opt_in",
        "managed_ready",
        "managed_revoke",
        "disabled",
    }:
        return await _managed_message(conn, user=user, bot=bot, template=template), False
    if template == "deposit":
        return await _deposit_message(conn, user=user, bot=bot), False
    if template == "balance":
        result = {
            "text": f"Seus Coins: {user['balance_units']}\n"
            f"Bônus para jogar: {user['balance_freebets']}\n"
            "Bônus não podem ser trocados por gift cards."
        }
        if bot["kind"] == "main":
            # Пополнение живёт в главном боте, поэтому кнопка ведёт на /deposit.
            deep = _deposit_deep_link()
            if deep:
                result["reply_markup"] = {
                    "inline_keyboard": [[{"text": "Adicionar Coins", "url": deep}]]
                }
        return result, False
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
        if bot["kind"] == "main":
            # Mini App живёт только в личном боте: здесь только дорога туда.
            personal = await _active_personal_bot(conn, user=user)
            if personal:
                return {
                    "text": "A troca de Coins por gift cards acontece no seu bot pessoal.",
                    "reply_markup": {
                        "inline_keyboard": [
                            [
                                {
                                    "text": "Abrir meu bot",
                                    "url": f"https://t.me/{personal['username']}",
                                }
                            ]
                        ]
                    },
                }, False
            return {
                "text": "Crie seu bot pessoal com /start e troque Coins por gift cards lá."
            }, False
        return {
            "text": "Troque seus Coins por gift cards disponíveis no catálogo. "
            "Confira região, nominal e custo antes de confirmar. Não é saque em dinheiro.",
            "reply_markup": webapp_keyboard(bot, "withdraw"),
        }, False
    if template == "mycards":
        if bot["kind"] == "main":
            personal = await _active_personal_bot(conn, user=user)
            if personal:
                return {
                    "text": "Seus gift cards e os códigos ficam no seu bot pessoal.",
                    "reply_markup": {
                        "inline_keyboard": [
                            [
                                {
                                    "text": "Abrir meu bot",
                                    "url": f"https://t.me/{personal['username']}",
                                }
                            ]
                        ]
                    },
                }, False
            return {"text": "Crie seu bot pessoal com /start para receber gift cards."}, False
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
        text = "Menu WINDROP: /deposit · /balance · /mybot · /support · /paysupport"
    if bot["kind"] == "main":
        # Mini App в главном боте не показываем вовсе — только в личном.
        return {"text": text}, False
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
