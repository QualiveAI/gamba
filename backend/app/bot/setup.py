"""Настройка UX платформы без setMyName и без изменения выбранного имени бота."""

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.bot.security import BotSecurityError, decrypt_secret
from app.config import settings

COMMANDS = [
    {"command": "start", "description": "Abrir a WINDROP"},
    {"command": "menu", "description": "Ver o menu"},
    {"command": "balance", "description": "Consultar Coins e bônus"},
    {"command": "withdraw", "description": "Trocar Coins por gift cards"},
    {"command": "mycards", "description": "Ver meus gift cards"},
    {"command": "support", "description": "Falar com o suporte"},
    {"command": "paysupport", "description": "Ajuda com pagamentos"},
    {"command": "mybot", "description": "Gerenciar meu bot pessoal"},
    {"command": "createbot", "description": "Autorizar a criação oficial de um bot"},
    {"command": "reconnectbot", "description": "Autorizar a reconexão de um bot"},
    {"command": "revokebot", "description": "Revogar o acesso de um bot pessoal"},
]


def _https_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise BotSecurityError("bot_https_url_required")
    if "\n" in value or "\r" in value:
        raise BotSecurityError("bot_https_url_required")
    return value


def webapp_url(bot: dict, fragment: str = "") -> str:
    parsed = urlsplit(_https_url(getattr(settings, "webapp_url", "")))
    query = [(key, value) for key, value in parse_qsl(parsed.query) if key != "auth_bot_id"]
    if bot["kind"] == "managed":
        query.append(("auth_bot_id", str(bot["bot_id"])))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), fragment))


def main_bot_link(payload: str = "managed") -> str | None:
    username = getattr(settings, "bot_username", "").lstrip("@")
    if not re.fullmatch(r"[A-Za-z0-9_]{5,32}", username):
        return None
    return f"https://t.me/{username}?start={payload}"


def webapp_keyboard(bot: dict, fragment: str = "") -> dict:
    label = "Trocar por gift cards" if fragment == "withdraw" else "Abrir WINDROP"
    return {"inline_keyboard": [[{"text": label, "web_app": {"url": webapp_url(bot, fragment)}}]]}


async def configure_bot(client, *, bot: dict, token: str, webhook: bool = True):
    commands = (
        COMMANDS
        if bot["kind"] == "main"
        else [
            command
            for command in COMMANDS
            if command["command"] not in {"createbot", "reconnectbot", "revokebot"}
        ]
    )
    for language in ("", "pt"):
        await client.call(token, "setMyCommands", commands=commands, language_code=language)
        await client.call(
            token,
            "setMyDescription",
            language_code=language,
            description="WINDROP: abra o aplicativo, acompanhe seus Coins e troque por gift cards. "
            "Pagamentos e suporte são tratados pelo bot principal oficial.",
        )
        await client.call(
            token,
            "setMyShortDescription",
            language_code=language,
            short_description="WINDROP | Coins, recompensas e gift cards. Suporte: /support",
        )
    await client.call(
        token,
        "setChatMenuButton",
        menu_button={
            "type": "web_app",
            "text": "Abrir WINDROP",
            "web_app": {"url": webapp_url(bot)},
        },
    )
    if webhook:
        base = _https_url(getattr(settings, "public_base_url", "")).rstrip("/")
        parsed = urlsplit(base)
        if parsed.query or parsed.fragment:
            raise BotSecurityError("webhook_base_url_invalid")
        allowed = (
            ["message", "pre_checkout_query", "managed_bot"]
            if bot["kind"] == "main"
            else ["message"]
        )
        await client.call(
            token,
            "setWebhook",
            url=f"{base}/bot/webhook/{bot['bot_id']}",
            secret_token=decrypt_secret(bot["webhook_secret_encrypted"]),
            allowed_updates=allowed,
            max_connections=20,
            drop_pending_updates=False,
        )
