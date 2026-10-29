import json
from dataclasses import dataclass, field
from typing import Any

from app.db import get_conn
from core.payments.apply import apply_event, ApplyResult
from core.payments.intents import create_intent, get_intent, PaymentIntent


@dataclass
class PaymentEvent:
    id: int
    rail: str
    provider_event_id: str
    intent_id: str | None
    raw_payload: dict[str, Any]
    outcome: str | None
    received_at: Any
    processed_at: Any


async def ingest(
    rail: str,
    provider_event_id: str,
    raw_payload: Any,
    intent_id: str | None = None,
) -> int:
    """Store a raw provider webhook event. Idempotent on (rail, provider_event_id)."""
    if not isinstance(raw_payload, dict):
        raise ValueError("raw_payload must be a dict")
    async with get_conn() as conn:
        existing = await (
            await conn.execute(
                "SELECT id FROM payment_events WHERE rail = %s AND provider_event_id = %s",
                (rail, provider_event_id),
            )
        ).fetchone()
        if existing:
            return int(existing["id"])
        await conn.execute(
            "INSERT INTO payment_events (rail, provider_event_id, intent_id, raw_payload) "
            "VALUES (%s, %s, %s, %s)",
            (rail, provider_event_id, intent_id, json.dumps(raw_payload)),
        )
        await conn.commit()
        row = await (
            await conn.execute(
                "SELECT id FROM payment_events WHERE rail = %s AND provider_event_id = %s",
                (rail, provider_event_id),
            )
        ).fetchone()
        return int(row["id"])


async def link_intent(event_id: int, intent_id: str) -> None:
    async with get_conn() as conn:
        await conn.execute(
            "UPDATE payment_events SET intent_id = %s WHERE id = %s",
            (intent_id, event_id),
        )
        await conn.commit()


async def process_pending(limit: int = 100) -> list[dict[str, Any]]:
    """Process unprocessed payment_events that have a resolvable intent."""
    results: list[dict[str, Any]] = []
    async with get_conn() as conn:
        rows = await (
            await conn.execute(
                "SELECT id, rail, provider_event_id, intent_id, raw_payload "
                "FROM payment_events WHERE processed_at IS NULL "
                "ORDER BY received_at ASC LIMIT %s",
                (limit,),
            )
        ).fetchall()
        for row in rows:
            event_id = int(row["id"])
            intent_id = row["intent_id"]
            if intent_id is None:
                payload = row["raw_payload"] or {}
                if isinstance(payload, str):
                    try:
                        payload = json.loads(payload)
                    except Exception:
                        payload = {}
                intent_id = payload.get("intent_id")
            intent = await get_intent(intent_id) if intent_id else None
            if intent is None:
                results.append({"id": event_id, "status": "skipped_no_intent", "credited": False})
                continue
            event = {
                "rail": row["rail"],
                "provider_event_id": row["provider_event_id"],
                "user_id": intent.user_id,
                "amount_minor": intent.amount_minor,
                "currency": intent.currency,
                "intent_id": intent.id,
            }
            result: ApplyResult = await apply_event(conn, event)
            if result.status == "processed":
                await conn.execute(
                    "UPDATE payment_intents SET status = 'succeeded', settled_at = now() WHERE id = %s",
                    (intent.id,),
                )
            elif result.status == "duplicate":
                await conn.execute(
                    "UPDATE payment_intents SET status = 'succeeded' WHERE id = %s AND status = 'pending'",
                    (intent.id,),
                )
            await conn.execute(
                "UPDATE payment_events SET outcome = %s, processed_at = now(), intent_id = %s WHERE id = %s",
                (result.status, intent.id, event_id),
            )
            await conn.commit()
            results.append(
                {"id": event_id, "status": result.status, "credited": result.credited}
            )
        return results


# Re-export for callers that expect events module to own intent creation.
create_intent = create_intent
get_intent = get_intent
PaymentIntent = PaymentIntent