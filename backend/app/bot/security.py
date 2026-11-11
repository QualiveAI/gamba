"""Шифрование и безопасные ошибки: никаких случайных ключей при старте."""

import hashlib
import hmac
import json
import logging
import re
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

MAX_UPDATE_BYTES = 256 * 1024
MAX_ATTEMPTS = 8
LEASE_SECONDS = 180


class BotSecurityError(ValueError):
    pass


def _fernet() -> Fernet:
    key = getattr(settings, "fernet_key", "")
    if not key:
        raise BotSecurityError("bot_encryption_not_configured")
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeError):
        raise BotSecurityError("bot_encryption_key_invalid") from None


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeError):
        raise BotSecurityError("bot_secret_unreadable") from None


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def valid_webhook_secret(value: str) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[A-Za-z0-9_-]{32,256}", value))


def secret_matches(value: str, expected_hash: str) -> bool:
    return valid_webhook_secret(value) and hmac.compare_digest(fingerprint(value), expected_hash)


def positive_id(value: Any) -> bool:
    return type(value) is int and 0 < value < 2**63


def token_bot_id(token: str) -> int:
    if not isinstance(token, str) or not re.fullmatch(r"[1-9][0-9]*:[A-Za-z0-9_-]+", token):
        raise BotSecurityError("bot_token_invalid")
    value = int(token.split(":", 1)[0])
    if not positive_id(value):
        raise BotSecurityError("bot_token_invalid")
    return value


def main_bot_id() -> int:
    return token_bot_id(settings.bot_token)


def encode_update(update: dict) -> str:
    value = json.dumps(update, ensure_ascii=False, separators=(",", ":"))
    if len(value.encode("utf-8")) > MAX_UPDATE_BYTES:
        raise BotSecurityError("update_too_large")
    return encrypt_secret(value)


class _TelegramLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # httpx по умолчанию пишет полный URL. Bot API требует token в пути запроса.
        # Сетевые диагностические записи отключены: даже тело может содержать код карты.
        return False


def suppress_transport_logs() -> None:
    for name in (
        "httpx",
        "httpcore",
        "httpcore.connection",
        "httpcore.http11",
        "httpcore.http2",
        "httpcore.proxy",
        "httpcore.socks",
        "httpcore.trace",
    ):
        logger = logging.getLogger(name)
        if not any(isinstance(item, _TelegramLogFilter) for item in logger.filters):
            logger.addFilter(_TelegramLogFilter())
