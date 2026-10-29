import hashlib
import hmac
import json
import time
import urllib.parse

import pytest

from app.auth.telegram import AuthError, validate_init_data

BOT_TOKEN = "test_token_123"


def make_init_data(bot_token=BOT_TOKEN, auth_date=None, tamper=False, bad_hash=False):
    if auth_date is None:
        auth_date = int(time.time())
    user = {"id": 42, "first_name": "Test", "username": "tester"}
    data = {
        "auth_date": str(auth_date),
        "query_id": "abc",
        "user": json.dumps(user),
    }
    items = sorted(data.items())
    data_check_string = "\n".join(f"{k}={v}" for k, v in items)
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calc_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if bad_hash:
        calc_hash = "0" * len(calc_hash)
    if tamper:
        data["user"] = json.dumps({"id": 99, "first_name": "X"})
    data["hash"] = calc_hash
    return urllib.parse.urlencode(data)


def test_happy_path():
    init_data = make_init_data()
    u = validate_init_data(init_data, BOT_TOKEN)
    assert u.id == 42


def test_bad_hash():
    init_data = make_init_data(bad_hash=True)
    with pytest.raises(AuthError):
        validate_init_data(init_data, BOT_TOKEN)


def test_expired_auth_date():
    init_data = make_init_data(auth_date=int(time.time()) - 1000)
    with pytest.raises(AuthError):
        validate_init_data(init_data, BOT_TOKEN)


def test_tampered():
    init_data = make_init_data(tamper=True)
    with pytest.raises(AuthError):
        validate_init_data(init_data, BOT_TOKEN)


def test_pkce_challenge():
    from app.auth.roblox_oauth import generate_pkce

    verifier, challenge = generate_pkce()
    assert len(verifier) > 20
    import base64
    import hashlib

    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    assert challenge == expected
