import contextlib

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

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

    @property
    def admin_ids(self) -> set[int]:
        out: set[int] = set()
        for part in self.admin_telegram_ids.split(","):
            part = part.strip()
            if part:
                with contextlib.suppress(ValueError):
                    out.add(int(part))
        return out


settings = Settings()
