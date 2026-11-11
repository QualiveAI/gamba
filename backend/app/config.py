import contextlib
import os
from decimal import Decimal
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", hide_input_in_errors=True
    )

    database_url: str = "postgresql://caseplatform:caseplatform@localhost:5432/caseplatform"
    redis_url: str = "redis://localhost:6379/0"
    bot_token: str = ""
    jwt_secret: str = "change_me"
    jwt_ttl_seconds: int = 86400
    roblox_client_id: str = ""
    roblox_client_secret: str = ""
    roblox_redirect_uri: str = ""
    yoomoney_client_id: str = ""
    yoomoney_client_secret: str = ""
    yoomoney_redirect_uri: str = ""
    yoomoney_webhook_secret: str = ""
    admin_telegram_ids: str = ""
    fernet_key: str = ""
    env: str = "dev"
    log_level: str = "INFO"
    withdrawal_min_units: int = 150
    withdrawal_fee_percent: int = 20
    withdrawal_hold_days: int = 1
    predictor_low_bet_threshold: int = 10
    predictor_high_bet_threshold: int = 100
    predictor_sub_rtp_bonus: float = 0.02
    bot_pool_csv: str = ""
    healthcheck_bot_token: str = ""
    healthcheck_target_chat_id: str = ""

    # По умолчанию код не подключается к ботам и не принимает настоящие деньги.
    allow_guest_auth: bool = False
    bot_mode: Literal["disabled", "polling", "webhook"] = "disabled"
    bot_username: str = ""
    webapp_url: str = "http://localhost:8090/app/"
    public_base_url: str = ""
    support_username: str = ""
    telegram_webhook_secret: str = ""
    managed_bots_enabled: bool = False
    payments_mode: Literal["disabled", "sandbox", "live"] = "disabled"
    payment_web_enabled: bool = False
    paymento_api_key: str = ""
    paymento_secret_key: str = ""
    stars_enabled: bool = False
    gifts_enabled: bool = False
    stars_refunds_enabled: bool = False
    payments_max_coins: int = Field(default=1_000_000, ge=100, le=1_000_000_000)
    coin_usd_price: Decimal = Field(default=Decimal("0.015"), gt=0)
    usd_brl_rate: Decimal = Field(default=Decimal("5.4"), gt=0)
    payment_fee_percent: Decimal = Field(default=Decimal("20"), ge=0, le=100)
    stars_usd_price: Decimal = Field(default=Decimal("0.02"), gt=0)
    quote_ttl_seconds: int = Field(default=900, ge=30, le=3600)
    treasury_asset: str = ""
    treasury_network: str = ""
    treasury_address: str = ""
    giftcard_redemption_enabled: bool = False
    giftcard_mode: Literal["disabled", "sandbox", "live"] = "disabled"
    giftcard_fernet_key: str = ""
    giftcard_fingerprint_key: str = ""
    db_connect_timeout_seconds: int = Field(default=3, ge=1, le=30)
    db_pool_timeout_seconds: int = Field(default=3, ge=1, le=30)
    readiness_timeout_seconds: int = Field(default=2, ge=1, le=30)
    expected_schema_version: str = "0018_giftcard_redemption.sql"
    media_storage_mode: Literal["local", "object"] = "local"

    @model_validator(mode="after")
    def validate_runtime(self):
        production = self.env.lower() in {"prod", "production"}
        if self.allow_guest_auth and self.env.lower() not in {"dev", "test"}:
            raise ValueError("Гостевой вход допускается только в dev/test")
        if self.media_storage_mode == "object":
            raise ValueError(
                "Object storage пока не подключён: используйте защищённый media volume"
            )
        if production:
            if self.payments_mode == "sandbox" or self.giftcard_mode == "sandbox":
                raise ValueError("Production не может работать в sandbox режиме")
            lowered_secret = self.jwt_secret.lower()
            if len(self.jwt_secret) < 32 or any(
                marker in lowered_secret
                for marker in ("change_me", "replace_with", "example", "test")
            ):
                raise ValueError(
                    "Для production нужен отдельный случайный JWT_SECRET от 32 символов"
                )
            from cryptography.fernet import Fernet

            for key in (self.fernet_key, self.giftcard_fernet_key):
                if key:
                    try:
                        Fernet(key.encode("ascii"))
                    except (ValueError, UnicodeEncodeError) as exc:
                        raise ValueError("Недопустимый ключ шифрования production") from exc
            if self.giftcard_fingerprint_key:
                import base64

                try:
                    fingerprint_key = base64.b64decode(
                        self.giftcard_fingerprint_key, altchars=b"-_", validate=True
                    )
                except (ValueError, UnicodeEncodeError) as exc:
                    raise ValueError("Недопустимый ключ fingerprint production") from exc
                if len(fingerprint_key) != 32:
                    raise ValueError("Ключ fingerprint должен содержать 32 случайных байта")
            if self.allow_guest_auth or self.bot_mode == "polling":
                raise ValueError("Production запрещает гостевой вход и polling ботов")
            if self.bot_mode != "disabled" or self.managed_bots_enabled:
                if any(
                    urlsplit(url).scheme != "https" or not urlsplit(url).hostname
                    for url in (self.webapp_url, self.public_base_url)
                ):
                    raise ValueError(
                        "Для production-ботов нужны WEBAPP_URL/PUBLIC_BASE_URL на HTTPS"
                    )
                if not self.fernet_key or not self.telegram_webhook_secret:
                    raise ValueError("Для production-ботов нужны ключ шифрования и webhook secret")
            if (
                self.giftcard_redemption_enabled
                and self.giftcard_mode == "live"
                and (not self.giftcard_fernet_key or not self.giftcard_fingerprint_key)
            ):
                raise ValueError(
                    "Для настоящих кодов нужны отдельные ключи шифрования и fingerprint"
                )
        return self

    @property
    def admin_ids(self) -> set[int]:
        out: set[int] = set()
        for part in self.admin_telegram_ids.split(","):
            part = part.strip()
            if part:
                with contextlib.suppress(ValueError):
                    out.add(int(part))
        return out


settings = Settings(_env_file=None) if os.getenv("WINDROP_TESTING") == "1" else Settings()
