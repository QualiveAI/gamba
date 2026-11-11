"""Проверки и шифрование gift cards без вывода секретов в исключения."""

import base64
import binascii
import hashlib
import hmac
import re
from dataclasses import dataclass, field

from cryptography.fernet import Fernet, InvalidToken
from psycopg.pq import TransactionStatus

from app.config import settings

MAX_SAFE_INTEGER = 9_007_199_254_740_991
MAX_IMPORT_BYTES = 1_048_576
MAX_IMPORT_ROWS = 2_000
SANDBOX_PREFIX = "TEST-ONLY-"

_MESSAGES = {
    "disabled": "Обмен gift cards отключён или ещё не настроен.",
    "storage_not_configured": "Защищённое хранилище gift cards не настроено.",
    "invalid_request": "Некорректные параметры обмена.",
    "telegram_required": "Для обмена нужен подтверждённый аккаунт Telegram.",
    "owner_mismatch": "Доступ к этой gift card запрещён.",
    "not_found": "Gift card или заказ не найден.",
    "sku_unavailable": "Этот SKU недоступен в текущем режиме.",
    "no_inventory": "Карты этого SKU закончились. Монеты не списаны.",
    "insufficient_balance": "Недостаточно целых монет для обмена.",
    "idempotency_conflict": "Ключ запроса уже использован для другого SKU.",
    "invalid_csv": "Некорректный CSV. Нужен один столбец code без пустых строк.",
    "import_too_large": "Превышен лимит размера или числа кодов в импорте.",
    "invalid_code": "В импорте есть некорректный код или неверная sandbox-маркировка.",
    "duplicate_code": "Импорт отменён: обнаружен повторяющийся код.",
    "duplicate_batch": "Импорт отменён: эта партия уже зарегистрирована.",
    "duplicate_sku": "Такой идентификатор SKU уже зарегистрирован.",
    "provenance_required": "Нужны сведения о закупке и правах на распространение карт.",
    "manual_review_required": "Нужна ручная проверка. Автоматический возврат запрещён.",
    "legacy_read_only": "Старые заявки доступны только для просмотра и ручной проверки.",
    "transaction_required": "Операция требует явной транзакции вызывающего кода.",
    "storage_error": "Не удалось безопасно обработать gift card. Нужна ручная проверка.",
    "ledger_error": "Обмен остановлен: требуется проверка учёта монет.",
}


class GiftCardError(ValueError):
    def __init__(self, code: str, status_code: int = 400):
        self.code = code if code in _MESSAGES else "storage_error"
        self.status_code = status_code
        super().__init__(_MESSAGES[self.code])


def require_transaction(conn) -> None:
    """Вызывающий код обязан завершить транзакцию ДО отправки в Telegram."""
    if conn.info.transaction_status != TransactionStatus.INTRANS:
        raise GiftCardError("transaction_required", 500)


def positive_integer(value) -> int:
    if type(value) is not int or not 1 <= value <= MAX_SAFE_INTEGER:
        raise GiftCardError("invalid_request")
    return value


def request_key(value) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", value):
        raise GiftCardError("invalid_request")
    return value


def reference(value, maximum: int) -> str:
    if not isinstance(value, str):
        raise GiftCardError("provenance_required")
    value = value.strip()
    if not value or len(value) > maximum or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise GiftCardError("provenance_required")
    return value


def authenticated_user(user: dict) -> tuple[int, int, str, int | None]:
    """Принимает только проверенный контекст deps, а не поля тела запроса."""
    if not isinstance(user, dict) or user.get("is_guest") is not False:
        raise GiftCardError("telegram_required", 403)
    user_id = positive_integer(user.get("id"))
    telegram_id = positive_integer(user.get("telegram_id"))
    scope = user.get("auth_scope")
    if scope not in ("primary", "managed"):
        raise GiftCardError("telegram_required", 403)
    bot_id = user.get("auth_bot_id")
    if scope == "managed":
        bot_id = positive_integer(bot_id)
        if user.get("auth_owner_telegram_id") != telegram_id:
            raise GiftCardError("owner_mismatch", 403)
    elif bot_id is not None:
        from app.bot.security import BotSecurityError, main_bot_id

        bot_id = positive_integer(bot_id)
        try:
            trusted_id = main_bot_id()
        except BotSecurityError:
            raise GiftCardError("owner_mismatch", 403) from None
        if bot_id != trusted_id:
            raise GiftCardError("owner_mismatch", 403)
    return user_id, telegram_id, scope, bot_id


def normalized_code(value: str, *, sandbox: bool) -> str:
    if not isinstance(value, str):
        raise GiftCardError("invalid_code")
    code = value.strip().upper()
    if not 8 <= len(code) <= 256 or not re.fullmatch(r"[A-Z0-9]+(?:-[A-Z0-9]+)*", code):
        raise GiftCardError("invalid_code")
    canonical = code.replace("-", "")
    if sandbox:
        if not code.startswith(SANDBOX_PREFIX):
            raise GiftCardError("invalid_code")
    elif canonical.startswith(("TEST", "SANDBOX", "DEMO")):
        raise GiftCardError("invalid_code")
    return code


def _secret_value(name: str) -> str:
    value = getattr(settings, name, "")
    if hasattr(value, "get_secret_value"):
        value = value.get_secret_value()
    return value if isinstance(value, str) else ""


def _key_bytes(value: str) -> bytes:
    try:
        decoded = base64.b64decode(value.encode("ascii"), altchars=b"-_", validate=True)
    except (ValueError, UnicodeError, binascii.Error):
        raise GiftCardError("storage_not_configured", 503) from None
    if len(decoded) != 32:
        raise GiftCardError("storage_not_configured", 503)
    return decoded


@dataclass(frozen=True)
class CodeVault:
    fernet: Fernet = field(repr=False)
    fingerprint_key: bytes = field(repr=False)

    def fingerprint(self, code: str) -> str:
        normalized = code.replace("-", "").upper().encode("ascii")
        return hmac.new(
            self.fingerprint_key, b"giftcard-code:v1:" + normalized, hashlib.sha256
        ).hexdigest()

    def encrypt(self, code: str) -> str:
        return self.fernet.encrypt(code.encode("ascii")).decode("ascii")

    def decrypt(self, ciphertext: str, fingerprint: str, *, sandbox: bool) -> str:
        try:
            code = self.fernet.decrypt(ciphertext.encode("ascii")).decode("ascii")
            code = normalized_code(code, sandbox=sandbox)
            valid = hmac.compare_digest(self.fingerprint(code), fingerprint)
        except (InvalidToken, ValueError, TypeError, UnicodeError):
            raise GiftCardError("storage_error", 503) from None
        if not valid:
            raise GiftCardError("storage_error", 503)
        return code


def vault() -> CodeVault:
    encryption_key = _secret_value("giftcard_fernet_key")
    fingerprint_key = _key_bytes(_secret_value("giftcard_fingerprint_key"))
    if hmac.compare_digest(_key_bytes(encryption_key), fingerprint_key):
        raise GiftCardError("storage_not_configured", 503)
    try:
        return CodeVault(Fernet(encryption_key.encode("ascii")), fingerprint_key)
    except (ValueError, TypeError, UnicodeError):
        raise GiftCardError("storage_not_configured", 503) from None


def enabled_mode() -> str:
    mode = getattr(settings, "giftcard_mode", "disabled")
    if getattr(settings, "giftcard_redemption_enabled", False) is not True:
        raise GiftCardError("disabled", 503)
    if mode not in ("sandbox", "live"):
        raise GiftCardError("disabled", 503)
    vault()
    return mode
