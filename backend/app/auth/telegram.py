import hashlib
import hmac
import json
import time
import urllib.parse
from dataclasses import dataclass


class AuthError(Exception):
    pass


@dataclass
class TelegramUser:
    id: int
    first_name: str = ""
    last_name: str = ""
    username: str = ""
    language_code: str = ""


def validate_init_data(init_data: str, bot_token: str, ttl: int = 300) -> TelegramUser:
    if not init_data:
        raise AuthError("empty init_data")  # noqa: B904
    parsed = urllib.parse.parse_qsl(init_data, keep_blank_values=True)
    data = {k: v for k, v in parsed}
    received_hash = data.pop("hash", None)
    if not received_hash:
        raise AuthError("missing hash")  # noqa: B904
    auth_date_raw = data.get("auth_date")
    if not auth_date_raw:
        raise AuthError("missing auth_date")  # noqa: B904
    try:
        auth_date = int(auth_date_raw)
    except ValueError:
        raise AuthError("bad auth_date")  # noqa: B904
    if abs(time.time() - auth_date) > ttl:
        raise AuthError("expired auth_date")  # noqa: B904
    items = sorted(data.items())
    data_check_string = "\n".join(f"{k}={v}" for k, v in items)
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calc_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc_hash, received_hash):
        raise AuthError("bad hash")  # noqa: B904
    user_raw = data.get("user")
    if not user_raw:
        raise AuthError("missing user")  # noqa: B904
    try:
        user_obj = json.loads(user_raw)
    except json.JSONDecodeError:
        raise AuthError("bad user json")  # noqa: B904
    return TelegramUser(
        id=int(user_obj["id"]),
        first_name=user_obj.get("first_name", "") or "",
        last_name=user_obj.get("last_name", "") or "",
        username=user_obj.get("username", "") or "",
        language_code=user_obj.get("language_code", "") or "",
    )
