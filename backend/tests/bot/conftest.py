"""Только синтетические credentials и fake Telegram transport, никаких сетевых запросов."""

import pytest
from cryptography.fernet import Fernet

from app.bot.pool import register_main
from app.config import settings
from app.db import get_conn

MAIN_TOKEN = "800000101:synthetic_main_token_not_for_telegram"
MANAGED_TOKEN = "800000201:synthetic_managed_token_not_for_telegram"
OWNER_ID = 800000301


@pytest.fixture
async def main_registry(monkeypatch):
    monkeypatch.setattr(settings, "env", "test")
    monkeypatch.setattr(settings, "bot_mode", "webhook")
    monkeypatch.setattr(settings, "bot_token", MAIN_TOKEN)
    monkeypatch.setattr(settings, "telegram_webhook_secret", "synthetic_webhook_secret_" + "x" * 40)
    monkeypatch.setattr(settings, "fernet_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "managed_bots_enabled", True)
    monkeypatch.setattr(settings, "bot_username", "windrop_test_bot")
    monkeypatch.setattr(settings, "webapp_url", "https://app.example.test/app/")
    monkeypatch.setattr(settings, "public_base_url", "https://app.example.test")
    async with get_conn() as conn, conn.transaction():
        bot = await register_main(
            conn, {"id": 800000101, "is_bot": True, "username": "windrop_test_bot"}
        )
    return dict(bot)
