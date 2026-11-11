"""Подарки требуют подтверждённого владения и операторской оценки, не скриншота."""

from core.contracts.payment import PaymentError, VerifiedPayment
from core.payments.apply import settlement_service
from core.payments.events import authenticate_event, ingest, record_verified_event
from core.payments.intents import get_intent
from core.payments.policy import ensure_enabled, primary_bot_id, runtime_settings


async def _require_operator(owner: dict) -> None:
    settings = runtime_settings()
    if (
        owner.get("auth_scope") != "primary"
        or owner.get("is_guest")
        or owner.get("auth_bot_id") != primary_bot_id()
        or owner.get("telegram_id") not in getattr(settings, "admin_ids", set())
    ):
        raise PaymentError("gift_operator_required", status_code=403)


async def _gift_intent(conn, *, user_id: int, intent_id: str):
    intent = await get_intent(intent_id, conn=conn, lock=True)
    if (
        intent is None
        or intent.user_id != user_id
        or intent.method != "gift"
        or intent.rail != "gift"
        or intent.mode != "live"
        or not intent.quote_id
    ):
        raise PaymentError("gift_intent_not_found", status_code=404)
    await ensure_enabled(conn, "gift", "live")
    return intent


async def record_business_gift(
    conn,
    *,
    user_id: int,
    intent_id: str,
    gift_id: str,
    business_connection_id: str,
    update_id: int,
    merchant_bot_id: int,
) -> int:
    """Только после аутентифицированного main-bot business update, не public HTTP."""
    if merchant_bot_id != primary_bot_id() or not business_connection_id:
        raise PaymentError("gift_merchant_mismatch", status_code=403)
    if type(update_id) is not int or update_id < 0 or not gift_id:
        raise PaymentError("gift_source_invalid")
    intent = await _gift_intent(conn, user_id=user_id, intent_id=intent_id)
    event_id = await ingest(
        "gift",
        f"receipt:{gift_id}",
        {
            "user_id": user_id,
            "gift_id": gift_id,
            "source": "business",
            "business_connection_id": business_connection_id,
            "update_id": update_id,
            "merchant_bot_id": merchant_bot_id,
        },
        intent.id,
        mode="live",
        event_kind="gift_receipt",
        conn=conn,
    )
    await authenticate_event(conn, event_id, source="telegram_main", reference=intent.id)
    return event_id


async def record_manual_gift_receipt(
    conn, *, intent_id: str, owner: dict, gift_id: str, custody_reference: str
) -> int:
    """Ручная аттестация оператора, проверившего реальное получение подарка.

    custody_reference — ID проверенного актива/записи инвентаря, не URL квитанции.
    Этот trust boundary требует контролируемого доступа к операторскому аккаунту.
    """
    await _require_operator(owner)
    if (
        not gift_id
        or len(gift_id) > 160
        or not custody_reference
        or len(custody_reference) > 256
        or "://" in custody_reference
    ):
        raise PaymentError(
            "gift_custody_reference_required", "Confirme o recebimento do presente.", 422
        )
    intent = await get_intent(intent_id, conn=conn, lock=True)
    if intent is None:
        raise PaymentError("gift_intent_not_found", status_code=404)
    await _gift_intent(conn, user_id=intent.user_id, intent_id=intent_id)
    event_id = await ingest(
        "gift",
        f"receipt:{gift_id}",
        {
            "user_id": intent.user_id,
            "gift_id": gift_id,
            "source": "manual_custody",
            "custody_reference": custody_reference,
            "operator_user_id": owner["id"],
        },
        intent.id,
        mode="live",
        event_kind="gift_receipt",
        conn=conn,
    )
    await authenticate_event(conn, event_id, source="gift_review", reference=intent.id)
    return event_id


async def review_gift(
    conn, *, intent_id: str, receipt_event_id: int, valued_brl_minor: int, owner: dict
):
    await _require_operator(owner)
    intent = await get_intent(intent_id, conn=conn, lock=True)
    if intent is None:
        raise PaymentError("gift_intent_not_found", status_code=404)
    await _gift_intent(conn, user_id=intent.user_id, intent_id=intent_id)
    receipt = await (
        await conn.execute(
            "SELECT * FROM payment_events WHERE id=%s FOR UPDATE", (receipt_event_id,)
        )
    ).fetchone()
    if (
        not receipt
        or receipt["event_kind"] != "gift_receipt"
        or not receipt["authenticated"]
        or receipt["reference_id"] != intent.id
        or receipt["mode"] != "live"
        or receipt["verification_source"] not in ("telegram_main", "gift_review")
    ):
        raise PaymentError("gift_source_unverified")
    if type(valued_brl_minor) is not int or valued_brl_minor != intent.provider_amount_atomic:
        raise PaymentError("gift_valuation_quote_mismatch", "A avaliação exige uma nova cotação.")
    raw = receipt["raw_payload"]
    if not isinstance(raw, dict) or raw.get("source") not in ("business", "manual_custody"):
        raise PaymentError("gift_source_unverified")
    if raw.get("user_id") != intent.user_id:
        raise PaymentError("gift_owner_mismatch")
    evidence = VerifiedPayment(
        reference=intent.id,
        rail="gift",
        mode="live",
        provider_event_id=f"review:{receipt_event_id}",
        status="succeeded",
        amount_atomic=valued_brl_minor,
        currency="BRL",
        source="gift_review",
        user_id=intent.user_id,
        charge_id=f"gift:{raw['gift_id']}",
        receipt_event_id=receipt_event_id,
        operator_user_id=owner["id"],
    )
    event_id = await record_verified_event(conn, evidence)
    return await settlement_service(conn, evidence, event_id=event_id)


async def handle_gift(conn, user_id: int, gift_id: str):
    """Legacy заявка только на review: price_rub и screenshot никогда не кредитуют coins."""
    if not isinstance(gift_id, str) or not gift_id or len(gift_id) > 160:
        raise PaymentError("gift_source_invalid")
    event_id = await ingest(
        "gift",
        f"request:{user_id}:{gift_id}",
        {"user_id": user_id, "gift_id": gift_id},
        mode="disabled",
        event_kind="gift_request",
        conn=conn,
    )
    return {"status": "pending_review", "id": event_id, "credited": False}
