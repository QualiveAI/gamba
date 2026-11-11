"""Единственная транзакционная точка settlement для webhook, poll, Stars и gift."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from core.contracts.payment import PaymentError, VerifiedPayment
from core.engine.ledger.ledger import post_entry
from core.payments.intents import get_intent
from core.payments.policy import ensure_enabled, primary_bot_id
from core.payments.quotes import get_quote


@dataclass(frozen=True)
class ApplyResult:
    status: str
    credited: bool = False
    intent_id: str | None = None
    sandbox: bool = False


async def _finish_event(conn, event_id: int, intent_id: str, outcome: str, *, retry: bool = False):
    await conn.execute(
        "UPDATE payment_events SET intent_id=%s,outcome=%s,attempts=attempts+1,"
        "processed_at=CASE WHEN %s THEN NULL ELSE now() END WHERE id=%s",
        (intent_id, outcome, retry, event_id),
    )


def validate_evidence(intent, quote, evidence: VerifiedPayment) -> None:
    if not intent.quote_id or not intent.coins or quote is None:
        raise PaymentError("legacy_intent_unsafe")
    if (intent.id, intent.rail, intent.mode) != (evidence.reference, evidence.rail, evidence.mode):
        raise PaymentError("payment_reference_mismatch")
    if (quote.id, quote.user_id, quote.coins, quote.rail, quote.mode, quote.method) != (
        intent.quote_id,
        intent.user_id,
        intent.coins,
        intent.rail,
        intent.mode,
        intent.method,
    ):
        raise PaymentError("quote_intent_mismatch")
    if (intent.provider_amount_atomic, intent.provider_currency) != (
        evidence.amount_atomic,
        evidence.currency,
    ):
        raise PaymentError("payment_amount_currency_mismatch")
    if (quote.provider_amount_atomic, quote.provider_currency) != (
        evidence.amount_atomic,
        evidence.currency,
    ):
        raise PaymentError("quote_amount_currency_mismatch")
    if evidence.user_id is not None and evidence.user_id != intent.user_id:
        raise PaymentError("payment_owner_mismatch")
    if intent.mode == "sandbox":
        if evidence.source != "sandbox_fixture":
            raise PaymentError("sandbox_source_mismatch")
    else:
        if quote.is_guest or quote.auth_scope == "guest":
            raise PaymentError("guest_live_forbidden")
        if intent.method == "stars":
            if (
                evidence.source != "telegram_main"
                or not evidence.charge_id
                or not evidence.merchant_bot_id
                or evidence.merchant_bot_id != intent.merchant_bot_id
                or evidence.merchant_bot_id != primary_bot_id()
            ):
                raise PaymentError("stars_merchant_mismatch")
        elif intent.method == "gift":
            if (
                evidence.source != "gift_review"
                or not evidence.receipt_event_id
                or not evidence.operator_user_id
            ):
                raise PaymentError("gift_review_required")
        elif evidence.source not in ("signed_webhook", "provider_poll"):
            raise PaymentError("unverified_payment")
    if intent.method == "crypto":
        if not all((intent.chain, intent.token, intent.address)):
            raise PaymentError("crypto_destination_missing")
        if (intent.chain, intent.token, intent.address) != (
            evidence.chain,
            evidence.token,
            evidence.address,
        ):
            raise PaymentError("crypto_destination_mismatch")
        if (quote.chain, quote.token, quote.address) != (
            evidence.chain,
            evidence.token,
            evidence.address,
        ):
            raise PaymentError("crypto_quote_mismatch")


async def settlement_service(
    conn, evidence: VerifiedPayment, *, event_id: int | None = None
) -> ApplyResult:
    """Никаких commit: ledger + статус + inbox + outbox принадлежат вызывающей транзакции.

    Savepoint гарантирует откат ВСЕХ финансовых изменений при ошибке post_entry,
    даже если вызывающий код решит зафиксировать нормализованный отказ.
    """
    if not isinstance(evidence, VerifiedPayment) or event_id is None:
        return ApplyResult("rejected_unverified")
    from core.payments.events import evidence_from_payload

    retry_codes = {
        "payments_disabled",
        "payment_kill_switch",
        "payment_not_configured",
        "provider_live_not_configured",
        "settlement_failed",
        "ledger_rejected",
    }
    try:
        async with conn.transaction():
            intent = await get_intent(evidence.reference, conn=conn, lock=True)
            if intent is None:
                return ApplyResult("skipped_no_intent")
            event = await (
                await conn.execute(
                    "SELECT * FROM payment_events WHERE id=%s FOR UPDATE", (event_id,)
                )
            ).fetchone()
            if (
                not event
                or not event["authenticated"]
                or event["verification_state"] != "verified"
                or event["rail"] != evidence.rail
                or event["mode"] != evidence.mode
                or event["reference_id"] != evidence.reference
                or event["event_kind"] != "payment"
            ):
                raise PaymentError("rejected_unverified")
            if evidence_from_payload(event["verified_payload"]) != evidence:
                raise PaymentError("stored_evidence_mismatch")
            quote = await get_quote(conn, intent.quote_id) if intent.quote_id else None
            validate_evidence(intent, quote, evidence)
            ref = f"deposit:{intent.id}"
            already = await (
                await conn.execute(
                    "SELECT id,event_type,payload FROM events WHERE idempotency_key=%s", (ref,)
                )
            ).fetchone()
            if already:
                expected_type = "sandbox_wallet_deposit" if intent.mode == "sandbox" else "deposit"
                if already["event_type"] != expected_type:
                    raise PaymentError("deposit_reference_conflict")
                if intent.status not in ("succeeded", "sandbox_succeeded", "refunded"):
                    raise PaymentError("settlement_state_inconsistent")
                await _finish_event(conn, event_id, intent.id, "duplicate")
                return ApplyResult(
                    "duplicate", intent_id=intent.id, sandbox=intent.mode == "sandbox"
                )
            if intent.status in ("succeeded", "sandbox_succeeded", "refunded"):
                raise PaymentError("settlement_state_inconsistent")
            if evidence.status != "succeeded":
                # Pending, failed и expired не превращаются в оплату даже в worker.
                if evidence.status in ("failed", "expired"):
                    await conn.execute(
                        "UPDATE payment_intents SET status=%s WHERE id=%s AND status='pending'",
                        (evidence.status, intent.id),
                    )
                await _finish_event(conn, event_id, intent.id, evidence.status)
                return ApplyResult(evidence.status, intent_id=intent.id)
            await ensure_enabled(conn, intent.method, intent.mode)
            # Истечение запрещает новый checkout/precheckout. Полученный позже, но
            # оплаченный вовремя proof принимается; неподтверждённый late требует review.
            if (
                intent.expires_at
                and intent.expires_at <= datetime.now(UTC)
                and (evidence.paid_at is None or evidence.paid_at > intent.expires_at)
            ):
                raise PaymentError("late_payment_review_required")
            if intent.status in ("failed", "expired"):
                raise PaymentError("terminal_payment_review_required")
            owner = await (
                await conn.execute(
                    "SELECT id,is_guest FROM users WHERE id=%s FOR UPDATE", (intent.user_id,)
                )
            ).fetchone()
            if not owner or intent.mode == "live" and owner["is_guest"]:
                raise PaymentError("guest_live_forbidden")
            if intent.method == "gift" and intent.mode == "live":
                receipt = await (
                    await conn.execute(
                        "SELECT * FROM payment_events WHERE id=%s FOR UPDATE",
                        (evidence.receipt_event_id,),
                    )
                ).fetchone()
                if (
                    not receipt
                    or receipt["event_kind"] != "gift_receipt"
                    or not receipt["authenticated"]
                    or receipt["mode"] != "live"
                    or receipt["reference_id"] != intent.id
                ):
                    raise PaymentError("gift_source_unverified")
            if intent.mode == "sandbox":
                # Изолированный журнал не расходуется играми и не может быть выведен.
                # Даже НЕгостевые sandbox платежи никогда не меняют живой wallet.
                event_type, new_status = "sandbox_wallet_deposit", "sandbox_succeeded"
            else:
                try:
                    await post_entry(
                        conn, intent.user_id, "units", intent.coins, "deposit_units", ref
                    )
                except Exception as exc:
                    raise PaymentError("ledger_rejected") from exc
                event_type, new_status = "deposit", "succeeded"
                from app.payments.notify import enqueue_deposit

                await enqueue_deposit(
                    conn,
                    user_id=intent.user_id,
                    coins=intent.coins,
                    rail=intent.rail,
                    intent_id=intent.id,
                )
            await conn.execute(
                "INSERT INTO events (user_id,event_type,payload,idempotency_key) "
                "VALUES (%s,%s,%s,%s)",
                (
                    intent.user_id,
                    event_type,
                    json.dumps(
                        {
                            "coins": intent.coins,
                            "wallet_unit": "coin",
                            "rail": intent.rail,
                            "intent_id": intent.id,
                            "mode": intent.mode,
                        }
                    ),
                    ref,
                ),
            )
            await conn.execute(
                "UPDATE payment_intents SET status=%s,settled_at=now(),charge_id=%s WHERE id=%s",
                (new_status, evidence.charge_id, intent.id),
            )
            await _finish_event(
                conn,
                event_id,
                intent.id,
                "sandbox_processed" if intent.mode == "sandbox" else "processed",
            )
            return ApplyResult(
                "sandbox_processed" if intent.mode == "sandbox" else "processed",
                credited=intent.mode == "live",
                intent_id=intent.id,
                sandbox=intent.mode == "sandbox",
            )
    except PaymentError as exc:
        # Финансовый savepoint уже откатан. Inbox остаётся доступным для повторения.
        await conn.execute(
            "UPDATE payment_events SET outcome=%s,verification_error=%s,attempts=attempts+1,"
            "processed_at=CASE WHEN %s THEN NULL ELSE now() END WHERE id=%s",
            (exc.code, exc.code, exc.code in retry_codes, event_id),
        )
        return ApplyResult(exc.code, intent_id=evidence.reference)
    except Exception:
        # Ошибка outbox/БД не маскируется как succeeded и не оставляет частичный ledger.
        await conn.execute(
            "UPDATE payment_events SET outcome='settlement_failed',"
            "verification_error='settlement_failed',attempts=attempts+1 WHERE id=%s",
            (event_id,),
        )
        return ApplyResult("settlement_failed", intent_id=evidence.reference)


async def apply_event(conn, event) -> ApplyResult:
    """Совместимое имя без старого обхода: dict amount/user_id не является оплатой."""
    if not isinstance(event, VerifiedPayment):
        return ApplyResult("rejected_unverified")
    from core.payments.events import record_verified_event

    event_id = await record_verified_event(conn, event)
    return await settlement_service(conn, event, event_id=event_id)
