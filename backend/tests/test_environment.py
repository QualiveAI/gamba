"""Предохранители тестового стенда. Не читают рабочий .env и не открывают соединения."""

import os
from urllib.parse import urlsplit

from psycopg.conninfo import conninfo_to_dict


def validate_test_database_url(dsn: str) -> dict[str, str]:
    if not dsn:
        raise ValueError("Задайте TEST_DATABASE_URL для отдельной тестовой БД")
    try:
        config = conninfo_to_dict(dsn)
    except Exception as exc:
        raise ValueError("Неверный формат TEST_DATABASE_URL") from exc
    name = config.get("dbname", "")
    role = config.get("user", "")
    if not name.endswith("_test") or not role.endswith("_test"):
        raise ValueError("Имя тестовой БД и роль должны оканчиваться на _test")
    if any(key in config for key in ("service", "servicefile", "options")):
        raise ValueError("Скрытые service/options запрещены в тестовом DSN")
    return config


def configure_test_environment() -> str:
    dsn = os.getenv("TEST_DATABASE_URL", "")
    validate_test_database_url(dsn)
    redis_url = os.getenv("TEST_REDIS_URL", "")
    parsed = urlsplit(redis_url)
    if parsed.scheme not in {"redis", "rediss"} or not parsed.hostname:
        raise ValueError("Задайте TEST_REDIS_URL отдельного тестового Redis")
    if parsed.port == 6379 and parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Тестовый Redis не должен использовать рабочий localhost:6379")
    os.environ.update(
        {
            "WINDROP_TESTING": "1",
            "DATABASE_URL": dsn,
            "REDIS_URL": redis_url,
            "ENV": "test",
            "BOT_MODE": "disabled",
            "BOT_TOKEN": "123456789:UNIT_TEST_TOKEN_NOT_A_REAL_BOT",
            "BOT_USERNAME": "",
            "BOT_POOL_CSV": "",
            "HEALTHCHECK_BOT_TOKEN": "",
            "HEALTHCHECK_TARGET_CHAT_ID": "",
            "ALLOW_GUEST_AUTH": "false",
            "MANAGED_BOTS_ENABLED": "false",
            "JWT_SECRET": "windrop-tests-only-not-for-deployment-0000",
            "ADMIN_TELEGRAM_IDS": "",
            "FERNET_KEY": "",
            "TELEGRAM_WEBHOOK_SECRET": "",
            "PAYMENTS_MODE": "disabled",
            "PAYMENT_WEB_ENABLED": "false",
            "STARS_ENABLED": "false",
            "GIFTS_ENABLED": "false",
            "STARS_REFUNDS_ENABLED": "false",
            "GIFTCARD_REDEMPTION_ENABLED": "false",
            "GIFTCARD_MODE": "disabled",
            "GIFTCARD_FERNET_KEY": "",
            "GIFTCARD_FINGERPRINT_KEY": "",
            "PAYGATE_WALLET": "",
            "PAYGATE_CALLBACK_BASE": "",
            "COINSO_SECRET_KEY": "",
            "COINSO_PROJECT_ID": "",
            "PAYMENTO_API_KEY": "",
            "PAYMENTO_SECRET_KEY": "",
            "TREASURY_ADDRESS": "",
            "TREASURY_NETWORK": "",
            "TREASURY_ASSET": "",
            "WEBAPP_URL": "http://127.0.0.1:8123/",
            "PUBLIC_BASE_URL": "",
            "MEDIA_STORAGE_MODE": "local",
        }
    )
    return dsn
