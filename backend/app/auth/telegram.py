import hashlib
import hmac
import json
import re
import time
import urllib.parse
from dataclasses import dataclass

from app.bot.security import positive_id


class AuthError(Exception):
    pass


@dataclass(frozen=True)
class TelegramUser:
    id: int
    first_name: str = ""
    last_name: str = ""
    username: str = ""
    language_code: str = ""


def validate_init_data(
    init_data: str, bot_token: str, ttl: int = 300, *, expected_owner_id: int | None = None
) -> TelegramUser:
    if not init_data or not bot_token or len(init_data.encode("utf-8")) > 16384:
        raise AuthError("invalid_init_data")
    try:
        parsed = urllib.parse.parse_qsl(
            init_data, keep_blank_values=True, strict_parsing=True, max_num_fields=32
        )
    except ValueError:
        raise AuthError("invalid_init_data") from None
    data = dict(parsed)
    if len(data) != len(parsed):
        raise AuthError("duplicate_init_data_field")
    received_hash = data.pop("hash", "")
    if not re.fullmatch(r"[0-9a-f]{64}", received_hash):
        raise AuthError("invalid_hash")
    try:
        auth_date = int(data.get("auth_date", ""))
    except ValueError:
        raise AuthError("invalid_auth_date") from None
    if auth_date > time.time() + 30 or time.time() - auth_date > ttl:
        raise AuthError("expired_auth_date")
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calculated = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated, received_hash):
        raise AuthError("invalid_hash")
    try:
        user = json.loads(data.get("user", ""))
    except (ValueError, TypeError):
        raise AuthError("invalid_user") from None
    if not isinstance(user, dict) or not positive_id(user.get("id")) or user.get("is_bot") is True:
        raise AuthError("invalid_user")
    # Владелец managed token способен подписать initData любого Telegram ID.
    # Подпись поэтому НЕ даёт права входить от имени кого-либо кроме registry.owner.
    if expected_owner_id is not None and user["id"] != expected_owner_id:
        raise AuthError("managed_owner_mismatch")
    text_fields = ("first_name", "last_name", "username", "language_code")
    if any(not isinstance(user.get(key, ""), str) for key in text_fields):
        raise AuthError("invalid_user")
    return TelegramUser(id=user["id"], **{key: user.get(key, "")[:128] for key in text_fields})
