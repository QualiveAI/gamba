"""Небольшой raw-клиент Bot API; новые Update не зависят от версии aiogram."""

import json
from typing import Any

import httpx

from app.bot.security import main_bot_id, suppress_transport_logs, token_bot_id
from app.config import settings

# Только документированные методы; имя метода не приходит из update или очереди.
_METHODS = frozenset(
    {
        "getMe",
        "getUpdates",
        "getWebhookInfo",
        "setWebhook",
        "deleteWebhook",
        "sendMessage",
        "answerPreCheckoutQuery",
        "setMyCommands",
        "setMyDescription",
        "setMyShortDescription",
        "setChatMenuButton",
        "getManagedBotToken",
        "setManagedBotAccessSettings",
        "createInvoiceLink",
        "refundStarPayment",
    }
)


class TelegramAPIError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False, retry_after: int | None = None):
        # Исключение не содержит request/response/URL и не сохраняет исходное исключение.
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.retry_after = retry_after


def retry_delay(attempt: int, retry_after: int | None = None) -> int:
    return max(1, retry_after) if retry_after is not None else min(300, 2 ** min(attempt, 8))


class TelegramClient:
    def __init__(self, session: httpx.AsyncClient | None = None):
        suppress_transport_logs()
        self._owns_session = session is None
        self._session = session or httpx.AsyncClient(
            timeout=httpx.Timeout(45, connect=10),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            follow_redirects=False,
            trust_env=False,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        await self.aclose()

    async def aclose(self):
        if self._owns_session:
            await self._session.aclose()

    async def call(self, token: str, method: str, **params: Any) -> Any:
        token_bot_id(token)
        if method not in _METHODS:
            raise TelegramAPIError("method_not_allowed")
        failure = None
        data = None
        status = 0
        try:
            # Telegram требует token в HTTPS пути; он никогда не записывается в БД/логи/очередь.
            async with self._session.stream(
                "POST", f"https://api.telegram.org/bot{token}/{method}", json=params
            ) as response:
                status = response.status_code
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(raw) + len(chunk) > 1024 * 1024:
                        failure = TelegramAPIError("response_too_large", retryable=True)
                        break
                    raw.extend(chunk)
                if failure is None:
                    try:
                        data = json.loads(raw)
                    except (ValueError, UnicodeError):
                        failure = TelegramAPIError("invalid_response", retryable=status >= 500)
        except httpx.HTTPError:
            failure = TelegramAPIError("transport_error", retryable=True)
        if status == 429 or (isinstance(data, dict) and data.get("error_code") == 429):
            parameters = data.get("parameters", {}) if isinstance(data, dict) else {}
            delay = parameters.get("retry_after", 30) if isinstance(parameters, dict) else 30
            delay = delay if type(delay) is int and 0 < delay <= 604800 else 604800
            raise TelegramAPIError("rate_limited", retryable=True, retry_after=delay)
        if status == 401 or (isinstance(data, dict) and data.get("error_code") == 401):
            raise TelegramAPIError("auth_failed")
        if status == 403 or (isinstance(data, dict) and data.get("error_code") == 403):
            raise TelegramAPIError("forbidden")
        if status >= 500:
            raise TelegramAPIError("telegram_unavailable", retryable=True)
        if (
            isinstance(data, dict)
            and type(data.get("error_code")) is int
            and data["error_code"] >= 500
        ):
            raise TelegramAPIError("telegram_unavailable", retryable=True)
        if failure is not None:
            raise failure from None
        if not isinstance(data, dict) or status != 200 or data.get("ok") is not True:
            raise TelegramAPIError("telegram_rejected")
        return data.get("result")


class MainStarsTransport:
    """API lifespan создаёт transport без запросов; только основной merchant token."""

    def __init__(self, client: TelegramClient | None = None):
        self.merchant_bot_id = main_bot_id()
        self._client = client or TelegramClient()
        self._owns_client = client is None

    def _token(self) -> str:
        if (
            getattr(settings, "bot_mode", "disabled") == "disabled"
            or main_bot_id() != self.merchant_bot_id
        ):
            raise TelegramAPIError("merchant_transport_disabled")
        return settings.bot_token

    async def create_invoice(
        self, *, title: str, description: str, payload: str, currency: str, total_amount: int
    ) -> str:
        from urllib.parse import urlsplit

        if currency != "XTR" or type(total_amount) is not int or total_amount <= 0:
            raise TelegramAPIError("stars_invoice_invalid")
        result = await self._client.call(
            self._token(),
            "createInvoiceLink",
            title=title,
            description=description,
            payload=payload,
            provider_token="",
            currency="XTR",
            prices=[{"label": title, "amount": total_amount}],
        )
        parsed = urlsplit(result) if isinstance(result, str) else None
        if (
            not parsed
            or parsed.scheme != "https"
            or parsed.hostname != "t.me"
            or parsed.username
            or parsed.password
        ):
            raise TelegramAPIError("invoice_link_invalid")
        return result

    async def refund(self, *, telegram_id: int, charge_id: str) -> bool:
        return (
            await self._client.call(
                self._token(),
                "refundStarPayment",
                user_id=telegram_id,
                telegram_payment_charge_id=charge_id,
            )
            is True
        )

    async def aclose(self):
        if self._owns_client:
            await self._client.aclose()
