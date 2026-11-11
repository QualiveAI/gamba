"""Единая политика доступности; ошибка конфигурации не включает платежи."""

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from core.contracts.payment import MethodAvailability, PaymentError

METHODS = {
    "stars": ("Telegram Stars", "stars"),
    "gift": ("Presentes do Telegram", "gift"),
    "card": ("Cartão", "paygate"),
    "crypto": ("Criptomoedas", "paymento"),
}


def runtime_settings():
    from app.config import settings

    return settings


def decimal_setting(value: Any, *, positive: bool = True) -> Decimal:
    # float не допускается: настройки и расчёты должны оставаться десятичными.
    if isinstance(value, (bool, float)):
        raise PaymentError("invalid_payment_config")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PaymentError("invalid_payment_config") from exc
    if not result.is_finite() or result < 0 or (positive and result == 0):
        raise PaymentError("invalid_payment_config")
    if len(result.as_tuple().digits) > 24 or abs(result.as_tuple().exponent) > 18:
        raise PaymentError("invalid_payment_config")
    return result


def primary_bot_id(settings=None) -> int | None:
    settings = settings or runtime_settings()
    # ID извлекается локально; сам токен никогда не сохраняется в quote/outbox.
    token = str(getattr(settings, "bot_token", "") or "")
    prefix, separator, _ = token.partition(":")
    return int(prefix) if separator and prefix.isdigit() and int(prefix) > 0 else None


@dataclass(frozen=True)
class PricingConfig:
    mode: str
    coin_usd_price: Decimal
    usd_brl_rate: Decimal
    fee_percent: Decimal
    stars_usd_price: Decimal
    ttl_seconds: int
    max_coins: int

    @classmethod
    def load(cls, settings=None):
        settings = settings or runtime_settings()
        mode = getattr(settings, "payments_mode", "disabled")
        if mode not in ("disabled", "sandbox", "live"):
            raise PaymentError("invalid_payment_mode")
        ttl = getattr(settings, "quote_ttl_seconds", 900)
        maximum = getattr(settings, "payments_max_coins", 1000000)
        if type(ttl) is not int or not 30 <= ttl <= 86400:
            raise PaymentError("invalid_payment_config")
        if type(maximum) is not int or not 1 <= maximum <= 100000000:
            raise PaymentError("invalid_payment_config")
        fee = decimal_setting(getattr(settings, "payment_fee_percent", "20"), positive=False)
        if fee > 100:
            raise PaymentError("invalid_payment_config")
        return cls(
            mode,
            decimal_setting(getattr(settings, "coin_usd_price", "0.015")),
            decimal_setting(getattr(settings, "usd_brl_rate", "5.4")),
            fee,
            decimal_setting(getattr(settings, "stars_usd_price", "0.02")),
            ttl,
            maximum,
        )

    def snapshot(self) -> dict:
        return {
            "pricing_schema": "coins-brl-v1",
            "wallet_unit": "coin",
            "coin_usd_price": str(self.coin_usd_price),
            "usd_brl_rate": str(self.usd_brl_rate),
            "payment_fee_percent": str(self.fee_percent),
            "stars_usd_price": str(self.stars_usd_price),
            "quote_ttl_seconds": self.ttl_seconds,
            "mode": self.mode,
        }

    @property
    def version(self) -> str:
        raw = json.dumps(self.snapshot(), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(raw).hexdigest()


def validate_actor(user: dict, mode: str) -> None:
    if type(user.get("id")) is not int or user["id"] <= 0:
        raise PaymentError("invalid_actor", status_code=403)
    scope = user.get("auth_scope")
    if scope not in ("primary", "managed", "guest", "roblox"):
        raise PaymentError("invalid_auth_scope", status_code=403)
    guest = user.get("is_guest") is True or scope == "guest"
    if guest and mode != "sandbox":
        raise PaymentError("guest_live_forbidden", "Entre pelo Telegram para pagar.", 403)
    if scope == "managed" and not user.get("auth_bot_id"):
        raise PaymentError("invalid_managed_identity", status_code=403)


def flag_enabled(value: Any) -> bool:
    # Совместимо с core.ops.flags.set_flag и ручным {enabled: bool}.
    if isinstance(value, dict):
        value = value.get("value", value.get("enabled"))
    return value is True


async def payment_flags(conn, method: str, *, refund: bool = False) -> bool:
    keys = ["deposits_enabled", f"payments_{method}_enabled"]
    if refund:
        keys.append("payments_stars_refunds_enabled")
    rows = await (
        await conn.execute(
            "SELECT key, value FROM system_config WHERE key = ANY(%s) ORDER BY key FOR SHARE",
            (keys,),
        )
    ).fetchall()
    values = {r["key"]: flag_enabled(r["value"]) for r in rows}
    return all(values.get(key, False) for key in keys)


def configured_reason(method: str, mode: str, settings=None) -> str | None:
    settings = settings or runtime_settings()
    if mode == "disabled":
        return "Pagamentos desativados."
    if mode not in ("sandbox", "live"):
        return "Configuração de pagamentos inválida."
    if mode == "sandbox":
        return None
    if method == "paygate" or method == "card":
        return "Cartão indisponível: confirmação segura do provedor não configurada."
    if method in ("paymento", "crypto"):
        return "Cripto indisponível: transporte e destino verificados não configurados."
    if method == "stars":
        if not getattr(settings, "stars_enabled", False) or not primary_bot_id(settings):
            return "Telegram Stars não configurado."
        from app.payments.stars import invoice_transport_ready

        if not invoice_transport_ready():
            return "Emissão de fatura indisponível."
    if method == "gift" and not getattr(settings, "gifts_enabled", False):
        return "Avaliação de presentes indisponível."
    return None


async def ensure_enabled(
    conn, method: str, mode: str, *, creation: bool = False, channel: str = "telegram"
) -> None:
    settings = runtime_settings()
    current = getattr(settings, "payments_mode", "disabled")
    if mode not in ("sandbox", "live") or current != mode:
        raise PaymentError("payments_disabled", "Pagamentos desativados.", 503)
    if method not in METHODS:
        raise PaymentError("unknown_method", status_code=422)
    if mode == "live" and method in ("stars", "gift"):
        key = "stars_enabled" if method == "stars" else "gifts_enabled"
        if getattr(settings, key, False) is not True:
            raise PaymentError("payment_not_configured", status_code=503)
    if mode == "live" and method in ("card", "crypto"):
        # Достоверного production transport пока нет даже для ранее созданного
        # intent. Смена статуса/worker не должна обходить запрет live adapter.
        raise PaymentError("provider_live_not_configured", status_code=503)
    if creation and channel == "web" and not getattr(settings, "payment_web_enabled", False):
        raise PaymentError("payment_web_disabled", "Pagamentos pela web indisponíveis.", 403)
    if not await payment_flags(conn, method):
        raise PaymentError(
            "payment_kill_switch", "Método de pagamento temporariamente indisponível.", 503
        )
    # Уже подтверждённый Stars разрешён при недоступном invoice transport;
    # выключатель метода и глобальный mode всё равно обязательны.
    if creation:
        reason = configured_reason(method, mode, settings)
        if reason:
            raise PaymentError("payment_not_configured", reason, 503)


async def available_methods(conn, user: dict | None = None, *, channel: str = "telegram"):
    settings = runtime_settings()
    mode = getattr(settings, "payments_mode", "disabled")
    if mode not in ("disabled", "sandbox", "live"):
        mode = "disabled"
    out = []
    for method, (label, rail) in METHODS.items():
        reason = configured_reason(method, mode, settings)
        try:
            PricingConfig.load(settings)
            if user is not None:
                validate_actor(user, mode)
            if (
                reason is None
                and channel == "web"
                and not getattr(settings, "payment_web_enabled", False)
            ):
                reason = "Pagamentos pela web indisponíveis."
            if reason is None and not await payment_flags(conn, method):
                reason = "Método de pagamento temporariamente indisponível."
        except PaymentError as exc:
            reason = exc.message
        out.append(MethodAvailability(method, label, rail, reason is None, reason, mode))
    return out
