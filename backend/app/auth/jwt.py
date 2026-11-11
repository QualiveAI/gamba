import base64
import binascii
import hashlib
import hmac
import json
import time
from dataclasses import dataclass

from app.bot.security import main_bot_id, positive_id
from app.config import settings

_SCOPES = frozenset({"primary", "managed", "guest", "roblox"})


class JWTError(Exception):
    pass


@dataclass(frozen=True)
class AuthClaims:
    user_id: int
    scope: str
    auth_bot_id: int | None = None
    owner_telegram_id: int | None = None
    credential_version: int | None = None


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    return base64.b64decode(data + "=" * (-len(data) % 4), altchars=b"-_", validate=True)


def issue_token(
    user_id: int,
    *,
    scope: str = "primary",
    auth_bot_id: int | None = None,
    owner_telegram_id: int | None = None,
    credential_version: int | None = None,
) -> str:
    if not positive_id(user_id) or scope not in _SCOPES:
        raise JWTError("invalid_claims")
    if scope == "primary" and auth_bot_id is None:
        auth_bot_id = main_bot_id()
    if scope in {"primary", "managed"} and not positive_id(auth_bot_id):
        raise JWTError("invalid_claims")
    if scope == "managed" and (
        not positive_id(owner_telegram_id) or not positive_id(credential_version)
    ):
        raise JWTError("invalid_claims")
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + settings.jwt_ttl_seconds,
        "scope": scope,
    }
    if scope in {"primary", "managed"}:
        payload["auth_bot_id"] = auth_bot_id
    if scope == "managed":
        payload.update(owner_telegram_id=owner_telegram_id, credential_version=credential_version)
    h = _b64url_encode(b'{"alg":"HS256","typ":"JWT"}')
    p = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(settings.jwt_secret.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest()
    return f"{h}.{p}.{_b64url_encode(sig)}"


def verify_claims(token: str) -> AuthClaims:
    if not isinstance(token, str) or len(token) > 8192:
        raise JWTError("malformed")
    try:
        h, p, s = token.split(".")
        expected = hmac.new(
            settings.jwt_secret.encode(), f"{h}.{p}".encode(), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(_b64url_decode(s), expected):
            raise JWTError("bad_signature")
        header = json.loads(_b64url_decode(h))
        payload = json.loads(_b64url_decode(p))
        if header != {"alg": "HS256", "typ": "JWT"} or not isinstance(payload, dict):
            raise JWTError("bad_payload")
        now = int(time.time())
        if type(payload.get("exp")) is not int or payload["exp"] <= now:
            raise JWTError("expired")
        if type(payload.get("iat")) is not int or payload["iat"] > now + 30:
            raise JWTError("bad_issued_at")
        sub = payload.get("sub")
        if not isinstance(sub, str) or not sub.isascii() or not sub.isdecimal():
            raise JWTError("missing_sub")
        user_id = int(sub)
        scope = payload.get("scope")
        if not positive_id(user_id) or not isinstance(scope, str) or scope not in _SCOPES:
            raise JWTError("bad_claims")
        bot_id = payload.get("auth_bot_id")
        owner = payload.get("owner_telegram_id")
        version = payload.get("credential_version")
        if scope in {"primary", "managed"} and not positive_id(bot_id):
            raise JWTError("bad_claims")
        if scope == "managed" and (not positive_id(owner) or not positive_id(version)):
            raise JWTError("bad_claims")
        if scope != "managed" and (owner is not None or version is not None):
            raise JWTError("bad_claims")
        return AuthClaims(user_id, scope, bot_id, owner, version)
    except (ValueError, TypeError, UnicodeError, binascii.Error, KeyError):
        raise JWTError("malformed") from None


def verify_token(token: str) -> int:
    """Совместимость для внутренних callers; HTTP deps обязаны проверять все claims."""
    return verify_claims(token).user_id
