import base64
import hashlib
import hmac
import json
import time

from app.config import settings


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def issue_token(user_id: int) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = {"sub": str(user_id), "iat": now, "exp": now + settings.jwt_ttl_seconds}
    h = _b64url_encode(json.dumps(header, separators=(",", ":")).encode())
    p = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{h}.{p}".encode()
    sig = hmac.new(settings.jwt_secret.encode(), signing_input, hashlib.sha256).digest()
    s = _b64url_encode(sig)
    return f"{h}.{p}.{s}"


class JWTError(Exception):
    pass


def verify_token(token: str) -> int:
    try:
        h, p, s = token.split(".")
    except ValueError:
        raise JWTError("malformed")  # noqa: B904
    signing_input = f"{h}.{p}".encode()
    expected = hmac.new(settings.jwt_secret.encode(), signing_input, hashlib.sha256).digest()
    if not hmac.compare_digest(_b64url_decode(s), expected):
        raise JWTError("bad signature")  # noqa: B904
    try:
        payload = json.loads(_b64url_decode(p))
    except Exception:
        raise JWTError("bad payload")  # noqa: B904
    if int(payload.get("exp", 0)) < int(time.time()):
        raise JWTError("expired")  # noqa: B904
    sub = payload.get("sub")
    if sub is None:
        raise JWTError("missing sub")  # noqa: B904
    return int(sub)
