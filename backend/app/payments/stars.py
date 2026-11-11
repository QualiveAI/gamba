"""Stars: серверная котировка, основной merchant и единый settlement.

Функции validate/settle вызываются только обработчиком основного бота ПОСЛЕ
проверки источника Telegram update. Пользовательский JWT, managed bot update и
HTTP JSON не являются основанием вызова settle_stars_payment.
"""

import json
from datetime import UTC, datetime
from typing import Protocol

from core.contracts.payment import PaymentError, VerifiedPayment
from core.payments.apply import settlement_service
from core.payments.events import record_verified_event
from core.payments.intents import get_intent
from core.payments.policy import ensure_enabled, payment_flags, primary_bot_id, runtime_settings


class StarsTransport(Protocol):
    merchant_bot_id: int

    async def create_invoice(
        self, *, title: str, description: str, payload: str, currency: str, total_amount: int
    ) -> str: ...

    async def refund(self, *, telegram_id: int, charge_id: str) -> bool: ...


_transport: StarsTransport | None = None


def configure_main_bot_transport(transport: StarsTransport | None) -> None:
    """Инъекция transport владельцем основного бота; сама функция не вызывает сеть."""
    global _transport
    if transport is not None and transport.merchant_bot_id != primary_bot_id():
        raise PaymentError("stars_merchant_mismatch", status_code=403)
    _transport = transport


def invoice_transport_ready() -> bool:
    return _transport is not None and _transport.merchant_bot_id == primary_bot_id()


def _intent_id(invoice_payload: str) -> str:
    if not isinstance(invoice_payload, str) or not invoice_payload.startswith("deposit:"):
        raise PaymentError("invalid_invoice_payload")
    intent_id = invoice_payload.removeprefix("deposit:")
    if len(intent_id) != 32 or any(char not in "0123456789abcdef" for char in intent_id):
        raise PaymentError("invalid_invoice_payload")
    return intent_id


async def _validate_invoice(
    conn, *, user_id: int, invoice_payload: str, currency: str, total_amount: int, precheckout: bool
):
    intent = await get_intent(_intent_id(invoice_payload), conn=conn, lock=True)
    if intent is None or intent.user_id != user_id:
        raise PaymentError("invoice_not_found", status_code=404)
    if (
        intent.method != "stars"
        or intent.rail != "stars"
        or intent.mode != "live"
        or not intent.quote_id
        or intent.provider_currency != "XTR"
    ):
        raise PaymentError("invalid_stars_intent")
    if (
        currency != "XTR"
        or type(total_amount) is not int
        or total_amount != intent.provider_amount_atomic
    ):
        raise PaymentError("stars_amount_currency_mismatch")
    if not intent.merchant_bot_id or intent.merchant_bot_id != primary_bot_id():
        raise PaymentError("stars_merchant_mismatch")
    owner = await (
        await conn.execute("SELECT id,is_guest,telegram_id FROM users WHERE id=%s", (user_id,))
    ).fetchone()
    if not owner or owner["is_guest"] or not owner["telegram_id"]:
        raise PaymentError("stars_owner_invalid", status_code=403)
    if precheckout:
        if intent.status != "pending":
            raise PaymentError("invoice_not_pending")
        if intent.expires_at is None or intent.expires_at <= datetime.now(UTC):
            raise PaymentError("quote_expired")
        await ensure_enabled(conn, "stars", "live")
    return intent


async def validate_stars_precheckout(
    conn, *, user_id: int, invoice_payload: str, currency: str, total_amount: int
) -> bool:
    try:
        await _validate_invoice(
            conn,
            user_id=user_id,
            invoice_payload=invoice_payload,
            currency=currency,
            total_amount=total_amount,
            precheckout=True,
        )
    except PaymentError:
        return False
    return True


async def settle_stars_payment(
    conn, *, user_id: int, invoice_payload: str, currency: str, total_amount: int, charge_id: str
):
    if not isinstance(charge_id, str) or not charge_id or len(charge_id) > 256:
        raise PaymentError("invalid_stars_charge")
    intent = await _validate_invoice(
        conn,
        user_id=user_id,
        invoice_payload=invoice_payload,
        currency=currency,
        total_amount=total_amount,
        precheckout=False,
    )
    if intent.charge_id is not None and intent.charge_id != charge_id:
        raise PaymentError("stars_charge_conflict")
    evidence = VerifiedPayment(
        reference=intent.id,
        rail="stars",
        mode="live",
        provider_event_id=charge_id,
        status="succeeded",
        amount_atomic=total_amount,
        currency=currency,
        source="telegram_main",
        charge_id=charge_id,
        user_id=user_id,
        merchant_bot_id=intent.merchant_bot_id,
    )
    event_id = await record_verified_event(conn, evidence)
    return await settlement_service(conn, evidence, event_id=event_id)


async def create_invoice_for_intent(conn, *, user: dict, intent_id: str) -> dict:
    intent = await get_intent(intent_id, conn=conn, lock=True)
    if intent is None or intent.user_id != user["id"]:
        raise PaymentError("intent_not_found", "Depósito não encontrado.", 404)
    if intent.method != "stars" or intent.status != "pending" or not intent.quote_id:
        raise PaymentError("invalid_stars_intent")
    if intent.expires_at is None or intent.expires_at <= datetime.now(UTC):
        raise PaymentError("quote_expired", "A cotação expirou.")
    await ensure_enabled(conn, "stars", intent.mode, creation=True)
    if intent.mode == "sandbox":
        return {
            "intent_id": intent.id,
            "mode": "sandbox",
            "invoice_link": None,
            "action": "sandbox",
        }
    await _validate_invoice(
        conn,
        user_id=user["id"],
        invoice_payload=f"deposit:{intent.id}",
        currency="XTR",
        total_amount=intent.provider_amount_atomic,
        precheckout=True,
    )
    if not invoice_transport_ready():
        raise PaymentError("stars_transport_unavailable", status_code=503)
    stored = intent.client_payload.get("invoice_link")
    if stored:
        return {"intent_id": intent.id, "mode": "live", "invoice_link": stored}
    title = f"{intent.coins} moedas"
    link = await _transport.create_invoice(
        title=title,
        description="Adicionar moedas à carteira",
        payload=f"deposit:{intent.id}",
        currency="XTR",
        total_amount=intent.provider_amount_atomic,
    )
    if not isinstance(link, str) or not link.startswith("https://t.me/"):
        raise PaymentError("invalid_invoice_link")
    payload = dict(intent.client_payload, invoice_link=link, action="open_invoice")
    await conn.execute(
        "UPDATE payment_intents SET client_payload=%s WHERE id=%s",
        (json.dumps(payload), intent.id),
    )
    return {"intent_id": intent.id, "mode": "live", "invoice_link": link}


async def create_invoice_link(title: str, description: str, payload: str, amount_stars: int) -> str:
    raise PaymentError("legacy_invoice_forbidden", "Use uma cotação criada pelo servidor.", 422)


async def handle_successful_payment(conn, user_id: int, amount_units: int, payload: str):
    raise PaymentError("legacy_stars_payment_forbidden")


async def _require_refund_owner(conn, owner: dict) -> None:
    settings = runtime_settings()
    if (
        owner.get("auth_scope") != "primary"
        or owner.get("is_guest")
        or owner.get("auth_bot_id") != primary_bot_id()
        or owner.get("telegram_id") not in getattr(settings, "admin_ids", set())
    ):
        raise PaymentError("stars_refund_owner_required", status_code=403)
    if not getattr(settings, "stars_refunds_enabled", False):
        raise PaymentError("stars_refunds_disabled", status_code=503)
    await ensure_enabled(conn, "stars", "live")
    if not await payment_flags(conn, "stars", refund=True):
        raise PaymentError("stars_refunds_disabled", status_code=503)


async def request_stars_refund(conn, *, intent_id: str, owner: dict) -> dict:
    """Запрос возвращает coins в hold; сетевого вызова здесь нет, commit у владельца."""
    from core.engine.ledger.ledger import post_entry

    await _require_refund_owner(conn, owner)
    async with conn.transaction():
        intent = await get_intent(intent_id, conn=conn, lock=True)
        if (
            intent is None
            or intent.method != "stars"
            or intent.mode != "live"
            or not intent.charge_id
            or intent.merchant_bot_id != primary_bot_id()
        ):
            raise PaymentError("stars_refund_invalid_intent")
        if intent.refund_status != "none":
            return {"intent_id": intent.id, "refund_status": intent.refund_status}
        if intent.status != "succeeded":
            raise PaymentError("stars_refund_not_paid")
        try:
            await post_entry(
                conn,
                intent.user_id,
                "units",
                -intent.coins,
                "stars_refund_hold",
                f"stars-refund:{intent.id}",
            )
        except Exception as exc:
            raise PaymentError("refund_ledger_rejected") from exc
        await conn.execute(
            "UPDATE payment_intents SET refund_status='requested',refund_requested_by=%s,"
            "refund_requested_at=now() WHERE id=%s",
            (owner["id"], intent.id),
        )
        return {"intent_id": intent.id, "refund_status": "requested"}


async def execute_stars_refund(*, intent_id: str, owner: dict) -> dict:
    """Main owner flow: processing фиксируется ДО transport, unknown не повторяется вслепую.

    Ошибка/неопределённость не возвращает hold автоматически: нужен owner review.
    Transport по умолчанию отсутствует, поэтому реальный refund не отправляется.
    """
    from app.db import get_conn

    async with get_conn() as conn, conn.transaction():
        await _require_refund_owner(conn, owner)
        intent = await get_intent(intent_id, conn=conn, lock=True)
        if (
            intent is None
            or intent.mode != "live"
            or intent.method != "stars"
            or intent.merchant_bot_id != primary_bot_id()
            or not intent.charge_id
        ):
            raise PaymentError("stars_refund_invalid_intent")
        if intent.refund_status != "requested":
            return {"intent_id": intent.id, "refund_status": intent.refund_status}
        if not invoice_transport_ready():
            await conn.execute(
                "UPDATE payment_intents SET refund_error='transport_unavailable' WHERE id=%s",
                (intent.id,),
            )
            return {
                "intent_id": intent.id,
                "refund_status": "requested",
                "error": "transport_unavailable",
            }
        user = await (
            await conn.execute("SELECT telegram_id FROM users WHERE id=%s", (intent.user_id,))
        ).fetchone()
        await conn.execute(
            "UPDATE payment_intents SET refund_status='processing',refund_error=NULL WHERE id=%s",
            (intent.id,),
        )
    try:
        accepted = await _transport.refund(
            telegram_id=user["telegram_id"], charge_id=intent.charge_id
        )
        status = "refunded" if accepted is True else "failed"
    except Exception:
        status = "unknown"
    async with get_conn() as conn, conn.transaction():
        current = await get_intent(intent_id, conn=conn, lock=True)
        if current.refund_status == "processing":
            await conn.execute(
                "UPDATE payment_intents SET refund_status=%s,"
                "status=CASE WHEN %s='refunded' THEN 'refunded' ELSE status END,"
                "refunded_at=CASE WHEN %s='refunded' THEN now() ELSE NULL END,"
                "refund_error=CASE WHEN %s='refunded' THEN NULL ELSE %s END WHERE id=%s",
                (status, status, status, status, status, intent_id),
            )
    return {"intent_id": intent_id, "refund_status": status}
