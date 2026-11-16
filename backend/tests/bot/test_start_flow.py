"""Поток /start: главный бот ведёт к созданию личного бота, игра — уже в нём.

Игрок не выбирает Mini App в главном боте: главный бот предлагает кнопку «Jogar»,
Telegram создаёт личного бота с подставленным именем, а Mini App открывается из
личного бота (его токен подписывает initData).
"""

from app.bot.notifications import _command_message, _managed_message
from app.bot.pool import get_bot
from app.bot.security import encrypt_secret, fingerprint
from app.bot.users import ensure_telegram_user
from app.db import get_conn


async def _user(telegram_id: int):
    async with get_conn() as conn, conn.transaction():
        return dict(await ensure_telegram_user(conn, telegram_id=telegram_id, username="tester"))


async def _managed_bot(
    conn, *, bot_id: int, username: str, owner_user_id: int, owner_telegram_id: int
):
    secret = f"managed_secret_{bot_id}_" + "y" * 24
    await conn.execute(
        "INSERT INTO bot_registry (bot_id, kind, username, owner_telegram_id, owner_user_id, "
        "token_encrypted, token_fingerprint, webhook_secret_encrypted, webhook_secret_hash, status) "
        "VALUES (%s, 'managed', %s, %s, %s, %s, %s, %s, %s, 'active')",
        (
            bot_id,
            username,
            owner_telegram_id,
            owner_user_id,
            encrypt_secret(f"{bot_id}:synthetic_token"),
            fingerprint(f"{bot_id}:synthetic_token"),
            encrypt_secret(secret),
            fingerprint(secret),
        ),
    )


async def test_main_start_offers_jogar_with_prefilled_name(main_registry):
    user = await _user(830000401)
    async with get_conn() as conn:
        message = await _managed_message(conn, user=user, bot=main_registry, template="start")
    button = message["reply_markup"]["keyboard"][0][0]
    assert button["text"] == "Jogar"
    request = button["request_managed_bot"]
    # Имя и username подставляет бот: игрок только подтверждает.
    assert request["suggested_username"] == f"windrop_{user['telegram_id']}_bot"
    assert request["suggested_name"]
    assert isinstance(request["request_id"], int)
    assert "Jogar" in message["text"] and "/support" in message["text"]


async def test_main_start_points_to_existing_personal_bot(main_registry):
    user = await _user(830000402)
    async with get_conn() as conn, conn.transaction():
        await _managed_bot(
            conn,
            bot_id=830000402,
            username="windrop_owner_two_bot",
            owner_user_id=user["id"],
            owner_telegram_id=user["telegram_id"],
        )
    async with get_conn() as conn:
        message = await _managed_message(conn, user=user, bot=main_registry, template="start")
    assert "windrop_owner_two_bot" in message["text"]
    button = message["reply_markup"]["inline_keyboard"][0][0]
    assert button["url"] == "https://t.me/windrop_owner_two_bot"
    # Повторное создание не предлагается
    assert "keyboard" not in message["reply_markup"]


async def test_personal_bot_start_opens_miniapp_of_that_bot(main_registry):
    user = await _user(830000403)
    async with get_conn() as conn, conn.transaction():
        await _managed_bot(
            conn,
            bot_id=830000403,
            username="windrop_owner_three_bot",
            owner_user_id=user["id"],
            owner_telegram_id=user["telegram_id"],
        )
    async with get_conn() as conn:
        personal = dict(await get_bot(conn, 830000403))
        message = await _managed_message(conn, user=user, bot=personal, template="start")
    button = message["reply_markup"]["inline_keyboard"][0][0]
    assert button["text"] == "Abrir WINDROP"
    # Ссылка должна нести auth_bot_id личного бота
    assert "auth_bot_id=830000403" in button["web_app"]["url"]


async def test_personal_bot_welcome_after_creation(main_registry):
    user = await _user(830000404)
    async with get_conn() as conn, conn.transaction():
        await _managed_bot(
            conn,
            bot_id=830000404,
            username="windrop_owner_four_bot",
            owner_user_id=user["id"],
            owner_telegram_id=user["telegram_id"],
        )
    async with get_conn() as conn:
        personal = dict(await get_bot(conn, 830000404))
        message = await _managed_message(conn, user=user, bot=personal, template="managed_ready")
    assert "pronto" in message["text"]
    assert (
        "auth_bot_id=830000404"
        in message["reply_markup"]["inline_keyboard"][0][0]["web_app"]["url"]
    )


async def test_main_bot_after_creation_only_links_to_personal_bot(main_registry):
    user = await _user(830000405)
    async with get_conn() as conn, conn.transaction():
        await _managed_bot(
            conn,
            bot_id=830000405,
            username="windrop_owner_five_bot",
            owner_user_id=user["id"],
            owner_telegram_id=user["telegram_id"],
        )
    async with get_conn() as conn:
        message = await _managed_message(
            conn, user=user, bot=main_registry, template="managed_ready"
        )
    button = message["reply_markup"]["inline_keyboard"][0][0]
    assert button["url"] == "https://t.me/windrop_owner_five_bot"
    assert "web_app" not in button


def _web_app_urls(markup):
    found = []
    for row in (markup or {}).get("inline_keyboard", []):
        for button in row:
            if "web_app" in button:
                found.append(button["web_app"].get("url"))
    for row in (markup or {}).get("keyboard", []):
        for button in row:
            if "web_app" in button:
                found.append(button["web_app"].get("url"))
    return found


async def test_main_bot_never_offers_a_miniapp(main_registry):
    """Mini App живёт только в личном боте: главный бот его не предлагает вовсе."""
    user = await _user(830000406)
    async with get_conn() as conn:
        for template in ("start", "menu", "balance", "withdraw", "mycards", "support", "deposit"):
            message, _protected = await _command_message(
                conn,
                job={"payload": {"template": template, "credential_version": 1}},
                user=user,
                bot=main_registry,
            )
            assert _web_app_urls(message.get("reply_markup")) == [], template
            assert "web_app" not in str(message.get("reply_markup", {})), template


async def test_deposit_in_main_bot_is_honest_when_payments_disabled(main_registry):
    """Оплата выключена — бот не рисует кнопки, а честно сообщает."""
    user = await _user(830000407)
    async with get_conn() as conn:
        message, _protected = await _command_message(
            conn,
            job={"payload": {"template": "deposit", "credential_version": 1}},
            user=user,
            bot=main_registry,
        )
    assert "desativad" in message["text"]
    assert "inline_keyboard" not in message.get("reply_markup", {})


async def test_deposit_in_personal_bot_redirects_to_main_bot(main_registry):
    user = await _user(830000408)
    async with get_conn() as conn, conn.transaction():
        await _managed_bot(
            conn,
            bot_id=830000408,
            username="windrop_owner_eight_bot",
            owner_user_id=user["id"],
            owner_telegram_id=user["telegram_id"],
        )
    async with get_conn() as conn:
        personal = dict(await get_bot(conn, 830000408))
        message, _protected = await _command_message(
            conn,
            job={"payload": {"template": "deposit", "credential_version": 1}},
            user=user,
            bot=personal,
        )
    assert "bot principal" in message["text"]
    button = message["reply_markup"]["inline_keyboard"][0][0]
    assert button["url"].startswith("https://t.me/windrop_test_bot")


async def test_balance_in_main_bot_offers_deposit_deep_link(main_registry):
    user = await _user(830000409)
    async with get_conn() as conn:
        message, protected = await _command_message(
            conn,
            job={"payload": {"template": "balance", "credential_version": 1}},
            user=user,
            bot=main_registry,
        )
    assert protected is False
    button = message["reply_markup"]["inline_keyboard"][0][0]
    assert button["text"] == "Adicionar Coins"
    assert button["url"] == "https://t.me/windrop_test_bot?start=deposit"
