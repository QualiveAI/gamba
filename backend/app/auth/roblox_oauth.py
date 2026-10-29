import base64
import hashlib
import secrets
import urllib.parse

import httpx
from cryptography.fernet import Fernet

from app.config import settings

ROBLOX_AUTH_URL = "https://apis.roblox.com/oauth/v1/authorize"
ROBLOX_TOKEN_URL = "https://apis.roblox.com/oauth/v1/token"
ROBLOX_USERINFO_URL = "https://apis.roblox.com/oauth/v1/userinfo"


def _fernet() -> Fernet:
    key = settings.fernet_key
    if not key:
        key = Fernet.generate_key().decode()
        settings.fernet_key = key
    return Fernet(key.encode() if isinstance(key, str) else key)


def generate_pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    return verifier, challenge


def build_auth_url(state: str, code_challenge: str) -> str:
    params = {
        "client_id": settings.roblox_client_id,
        "redirect_uri": settings.roblox_redirect_uri,
        "scope": "openid profile",
        "response_type": "code",
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    return ROBLOX_AUTH_URL + "?" + urllib.parse.urlencode(params)


async def exchange_code(code: str, code_verifier: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            ROBLOX_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.roblox_redirect_uri,
                "client_id": settings.roblox_client_id,
                "client_secret": settings.roblox_client_secret,
                "code_verifier": code_verifier,
            },
        )
    resp.raise_for_status()
    data = resp.json()
    # encrypt tokens
    f = _fernet()
    if "access_token" in data:
        data["access_token_enc"] = f.encrypt(data["access_token"].encode()).decode()
    if "refresh_token" in data:
        data["refresh_token_enc"] = f.encrypt(data["refresh_token"].encode()).decode()
    return data


async def get_user_info(access_token: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            ROBLOX_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    resp.raise_for_status()
    return resp.json()


def decrypt_token(enc: str) -> str:
    f = _fernet()
    return f.decrypt(enc.encode()).decode()
