"""Durable inbox: raw данные не получают доверие при чтении worker."""

import hashlib
import inspect
import json
from dataclasses import asdict
from datetime import datetime
from typing import Any

from core.contracts.payment import PaymentError, VerifiedPayment
from core.payments.intents import PaymentIntent, create_intent, get_intent  # noqa: F401

MAX_BODY_BYTES = 65536


def evidence_payload(evidence: VerifiedPayment) -> dict:
    payload = asdict(evidence)
    if evidence.paid_at is not None:
        payload["paid_at"] = evidence.paid_at.isoformat()
    return payload


def evidence_from_payload(payload: Any) -> VerifiedPayment:
    if not isinstance(payload, dict):
        raise PaymentError("unverified_payment")
    values = dict(payload)
    if values.get("paid_at"):
        values["paid_at"] = datetime.fromisoformat(values["paid_at"])
    try:
        return VerifiedPayment(**values)
    except (ValueError, TypeError, KeyError) as exc:
        raise PaymentError("invalid_stored_evidence") from exc


def encode_payload(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


async def ingest(
    rail: str,
    provider_event_id: str,
    raw_payload: Any,
    intent_id: str | None = None,
    *,
    mode: str = "disabled",
    raw_body: bytes | None = None,
    event_kind: str = "payment",
    conn=None,
) -> int:
    """Сохранить НЕПРОВЕРЕННОЕ событие. Автономный вызов завершает только inbox-транзакцию."""
    if not isinstance(raw_payload, dict):
        raise PaymentError("invalid_event_payload", status_code=422)
    if mode not in ("disabled", "sandbox", "live"):
        raise PaymentError("invalid_evidence_mode")
    if not provider_event_id or len(provider_event_id) > 256 or len(rail) > 64:
        raise PaymentError("invalid_event_id")
    body = raw_body if raw_body is not None else encode_payload(raw_payload)
    if type(body) is not bytes or len(body) > MAX_BODY_BYTES:
        raise PaymentError("webhook_too_large", status_code=413)
    if conn is None:
        from app.db import get_conn

        async with get_conn() as owned_conn, owned_conn.transaction():
            return await ingest(
                rail,
                provider_event_id,
                raw_payload,
                intent_id,
                mode=mode,
                raw_body=body,
                event_kind=event_kind,
                conn=owned_conn,
            )
    digest = hashlib.sha256(body).hexdigest()
    row = await (
        await conn.execute(
            "INSERT INTO payment_events (rail,provider_event_id,reference_id,raw_payload,"
            "mode,raw_body,payload_hash,event_kind) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (rail,mode,provider_event_id) DO NOTHING RETURNING id",
            (
                rail,
                provider_event_id,
                intent_id,
                json.dumps(raw_payload),
                mode,
                body,
                digest,
                event_kind,
            ),
        )
    ).fetchone()
    if row:
        return int(row["id"])
    row = await (
        await conn.execute(
            "SELECT id,payload_hash,event_kind,reference_id FROM payment_events "
            "WHERE rail=%s AND mode=%s AND provider_event_id=%s FOR UPDATE",
            (rail, mode, provider_event_id),
        )
    ).fetchone()
    if not row or row["payload_hash"] != digest or row["event_kind"] != event_kind:
        raise PaymentError("event_payload_conflict")
    if intent_id and row["reference_id"] not in (None, intent_id):
        raise PaymentError("event_reference_conflict")
    return int(row["id"])


async def authenticate_event(
    conn,
    event_id: int,
    *,
    source: str,
    reference: str | None = None,
    evidence: VerifiedPayment | None = None,
) -> None:
    """Вызывается verifier после проверки raw-body подписи/merchant source."""
    row = await (
        await conn.execute("SELECT * FROM payment_events WHERE id=%s FOR UPDATE", (event_id,))
    ).fetchone()
    if row is None:
        raise PaymentError("inbox_event_not_found")
    if evidence is not None:
        if row["rail"] != evidence.rail or row["mode"] != evidence.mode:
            raise PaymentError("event_rail_mode_mismatch")
        if source != evidence.source:
            raise PaymentError("event_source_mismatch")
        reference = evidence.reference
    if row["reference_id"] not in (None, reference):
        raise PaymentError("event_reference_conflict")
    if source not in (
        "signed_webhook",
        "provider_poll",
        "sandbox_fixture",
        "telegram_main",
        "gift_review",
    ):
        raise PaymentError("unverified_payment")
    if row["verification_state"] == "verified":
        if evidence and row["verified_payload"] != evidence_payload(evidence):
            raise PaymentError("event_evidence_conflict")
        return
    await conn.execute(
        "UPDATE payment_events SET authenticated=TRUE,verification_source=%s,"
        "verification_state=%s,verified_payload=%s,reference_id=%s,verification_error=NULL,"
        "processed_at=NULL,outcome=NULL WHERE id=%s",
        (
            source,
            "verified" if evidence else "authenticated",
            json.dumps(evidence_payload(evidence)) if evidence else None,
            reference,
            event_id,
        ),
    )


async def record_verified_event(
    conn, evidence: VerifiedPayment, *, event_kind: str = "payment"
) -> int:
    if not isinstance(evidence, VerifiedPayment):
        raise PaymentError("unverified_payment")
    # Во всех внутренних путях сначала intent, затем inbox: без инверсии locks.
    await get_intent(evidence.reference, conn=conn, lock=True)
    event_id = await ingest(
        evidence.rail,
        evidence.provider_event_id,
        evidence_payload(evidence),
        evidence.reference,
        mode=evidence.mode,
        event_kind=event_kind,
        conn=conn,
    )
    await authenticate_event(conn, event_id, source=evidence.source, evidence=evidence)
    return event_id


async def link_intent(event_id: int, intent_id: str) -> None:
    """Связь не повышает уровень доверия и не заменяет reference в evidence."""
    from app.db import get_conn

    async with get_conn() as conn, conn.transaction():
        row = await (
            await conn.execute("SELECT * FROM payment_events WHERE id=%s FOR UPDATE", (event_id,))
        ).fetchone()
        if not row or row["reference_id"] != intent_id:
            raise PaymentError("event_reference_mismatch")
        intent = await get_intent(intent_id, conn=conn)
        if intent is None or intent.rail != row["rail"] or intent.mode != row["mode"]:
            raise PaymentError("event_rail_mode_mismatch")
        await conn.execute(
            "UPDATE payment_events SET intent_id=%s WHERE id=%s", (intent_id, event_id)
        )


async def process_event(conn, event_id: int):
    from core.payments.apply import ApplyResult, settlement_service
    from core.registry.registry import registry

    # Сначала intent, потом event: единый порядок row locks для webhook/poll/bot.
    row = await (
        await conn.execute("SELECT * FROM payment_events WHERE id=%s", (event_id,))
    ).fetchone()
    if not row or row["event_kind"] != "payment":
        return ApplyResult("skipped_event_kind")
    if row["processed_at"] is not None:
        return ApplyResult(row["outcome"] or "duplicate")
    if not row["authenticated"] or row["verification_state"] == "unverified":
        await conn.execute(
            "UPDATE payment_events SET outcome='rejected_unverified',processed_at=now(),"
            "verification_error='unverified_payment',verification_state='rejected' WHERE id=%s",
            (event_id,),
        )
        return ApplyResult("rejected_unverified")
    reference = row["reference_id"]
    # Verify сериализуется отдельной advisory-блокировкой, БЕЗ row lock wallet,
    # ledger или intent на время внешнего transport. Paymento Verify идемпотентен.
    await conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        (f"payment-verify:{row['rail']}:{row['mode']}:{reference}",),
    )
    intent = await get_intent(reference, conn=conn) if reference else None
    if intent is None:
        return ApplyResult("skipped_no_intent")
    row = await (
        await conn.execute("SELECT * FROM payment_events WHERE id=%s", (event_id,))
    ).fetchone()
    if row["processed_at"] is not None:
        return ApplyResult(row["outcome"] or "duplicate")
    if row["verification_state"] == "authenticated":
        from core.payments.policy import ensure_enabled

        try:
            await ensure_enabled(conn, intent.method, intent.mode)
        except PaymentError as exc:
            return ApplyResult(exc.code)
        plugin = registry.get("payment", row["rail"])
        reconcile = getattr(plugin, "reconcile_event", None)
        if reconcile is None:
            return ApplyResult("verification_unavailable")
        try:
            # Inbox уже durable; Verify сериализован advisory lock, не wallet lock.
            evidence = reconcile(dict(row), intent)
            if inspect.isawaitable(evidence):
                evidence = await evidence
            if not isinstance(evidence, VerifiedPayment):
                raise PaymentError("unverified_payment")
            # Транспорт уже завершён; далее порядок блокировок intent -> event.
            await get_intent(reference, conn=conn, lock=True)
            await authenticate_event(conn, event_id, source=evidence.source, evidence=evidence)
        except PaymentError as exc:
            await conn.execute(
                "UPDATE payment_events SET attempts=attempts+1,verification_error=%s WHERE id=%s",
                (exc.code, event_id),
            )
            return ApplyResult(exc.code)
    else:
        try:
            evidence = evidence_from_payload(row["verified_payload"])
        except PaymentError as exc:
            return ApplyResult(exc.code)
    return await settlement_service(conn, evidence, event_id=event_id)


async def process_pending(limit: int = 100, *, max_attempts: int = 12) -> list[dict]:
    from app.db import get_conn
    from core.payments.policy import runtime_settings

    if getattr(runtime_settings(), "payments_mode", "disabled") not in ("sandbox", "live"):
        return []
    if type(limit) is not int or not 1 <= limit <= 1000 or not 1 <= max_attempts <= 100:
        raise PaymentError("invalid_worker_limit")
    async with get_conn() as conn:
        rows = await (
            await conn.execute(
                "SELECT id FROM payment_events WHERE processed_at IS NULL AND event_kind='payment' "
                "AND attempts < %s AND next_attempt_at <= now() "
                "ORDER BY received_at,id LIMIT %s",
                (max_attempts, limit),
            )
        ).fetchall()
    results = []
    for row in rows:
        async with get_conn() as conn, conn.transaction():
            before = await (
                await conn.execute("SELECT attempts FROM payment_events WHERE id=%s", (row["id"],))
            ).fetchone()
            result = await process_event(conn, int(row["id"]))
            await conn.execute(
                "UPDATE payment_events SET attempts=GREATEST(attempts,%s),"
                "next_attempt_at=now() + make_interval(secs => "
                "LEAST(3600, 5 * power(2, LEAST(attempts,10)))::double precision) "
                "WHERE id=%s AND processed_at IS NULL",
                (int(before["attempts"]) + 1, row["id"]),
            )
            results.append(
                {"id": int(row["id"]), "status": result.status, "credited": result.credited}
            )
    return results
