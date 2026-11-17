"""Прямые депозиты USDT TRC-20 на казну оператора — без кастодиальных посредников.

Игрок получает адрес и точную сумму, шлёт транзакцию, сканер проверяет её в
публичном API TronGrid и проводит settlement через общий verified/settlement
путь платежей (тот же, что Stars/Gifts). KYC/KYB ни для кого: монеты едут
прямо на кошелёк оператора.

Сумма каждого незакрытого депозита уникальна (хвост из id котировки), поэтому
одна общая адресная книга не путает плательщиков.
"""

import logging

import httpx

from core.contracts.payment import PaymentError, VerifiedPayment
from core.payments.apply import settlement_service
from core.payments.events import record_verified_event
from core.payments.policy import crypto_treasury_configured, runtime_settings

logger = logging.getLogger(__name__)

USDT_TRC20_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pLzotkSzYyi4j"
TRONGRID_BASE = "https://api.trongrid.io"
MAX_FETCH = 50


async def fetch_recent_usdt_transfers(address: str, *, timeout: float = 10.0) -> list[dict]:
    """Подтверждённые входящие USDT TRC-20 за последнее окно, новые первыми.

    Возвращает [{"txid", "value_atoms"}]. Сеть общедоступная, ключи не нужны.
    """
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(
            f"{TRONGRID_BASE}/v1/accounts/{address}/transactions/trc20",
            params={
                "contract_address": USDT_TRC20_CONTRACT,
                "only_confirmed": "true",
                "only_to": "true",
                "limit": MAX_FETCH,
                "order_by": "block_timestamp,desc",
            },
        )
        response.raise_for_status()
        data = response.json().get("data", [])
    transfers = []
    for item in data:
        if (
            not isinstance(item, dict)
            or item.get("to") != address
            or item.get("token_info", {}).get("symbol") != "USDT"
        ):
            continue
        txid = item.get("transaction_id")
        value = item.get("value")
        if not isinstance(txid, str) or not str(value).isdigit():
            continue
        transfers.append({"txid": txid, "value_atoms": int(value)})
    return transfers


async def scan_onchain_deposits() -> int:
    """Один проход: найти незакрытые crypto-интенты и провести по ним оплаты.

    Возвращает число зачисленных депозитов. Сетевые сбои поднимаются наружу —
    планировщик логирует тип ошибки и попробует снова.
    """
    settings = runtime_settings()
    if getattr(settings, "payments_mode", "disabled") != "live" or not crypto_treasury_configured():
        return 0
    address = settings.treasury_address.strip()
    from app.db import get_conn

    async with get_conn() as conn:
        pending = await (
            await conn.execute(
                "SELECT id, user_id, provider_amount_atomic FROM payment_intents "
                "WHERE method = 'crypto' AND status = 'pending' AND expires_at > now() "
                "ORDER BY created_at LIMIT 200",
            )
        ).fetchall()
    if not pending:
        return 0
    by_amount = {int(row["provider_amount_atomic"]): (row["id"], row["user_id"]) for row in pending}
    transfers = await fetch_recent_usdt_transfers(address)
    credited = 0
    for transfer in transfers:
        matched = by_amount.get(transfer["value_atoms"])
        if matched is None:
            continue
        intent_id, user_id = matched
        evidence = VerifiedPayment(
            reference=intent_id,
            rail="paymento",
            mode="live",
            provider_event_id=transfer["txid"],
            status="succeeded",
            amount_atomic=transfer["value_atoms"],
            currency="USDT",
            source="provider_poll",
            chain="tron",
            token="USDT",
            address=address,
            user_id=user_id,
        )
        try:
            from app.db import get_conn as _get_conn

            async with _get_conn() as conn, conn.transaction():
                event_id = await record_verified_event(conn, evidence)
                result = await settlement_service(conn, evidence, event_id=event_id)
                if result.credited or result.status in {"processed", "duplicate"}:
                    credited += 1
                    by_amount.pop(evidence.amount_atomic, None)
        except PaymentError as exc:
            # Повторный txid или интент уже закрыт — это не ошибка сканера.
            logger.info("onchain scan пропустил платёж (%s)", exc.code if hasattr(exc, "code") else type(exc).__name__)
            continue
    return credited


async def run_scan_job() -> None:
    """Обёртка для планировщика: сбой сети не роняет лидера писателя."""
    try:
        credited = await scan_onchain_deposits()
        if credited:
            logger.info("onchain scan: зачислено=%s", credited)
    except Exception:
        logger.exception("onchain scan недоступен")
