import inspect

from core.engine.ledger.ledger import post_entry


class DirectLedgerForbidden(Exception):
    pass


class ApplyResult:
    def __init__(self, status: str, credited: bool = False):
        self.status = status
        self.credited = credited


DEPOSIT_REASONS = {"deposit_units", "deposit_freebets"}


def _caller_is_apply() -> bool:
    for frame in inspect.stack():
        if frame.filename.endswith("core/payments/apply.py") or frame.filename.endswith(
            "core\\payments\\apply.py"
        ):
            return True
    return False


async def apply_event(conn, event: dict) -> ApplyResult:
    rail = event.get("rail")
    provider_event_id = event.get("provider_event_id")
    user_id = event.get("user_id")
    amount_minor = int(event.get("amount_minor", 0))
    currency = event.get("currency", "units")
    idempotency_key = f"{rail}:{provider_event_id}"
    # idempotency
    row = await (
        await conn.execute("SELECT id FROM events WHERE idempotency_key = %s", (idempotency_key,))
    ).fetchone()
    if row:
        return ApplyResult("duplicate", False)
    await post_entry(conn, user_id, currency, amount_minor, "deposit_units", idempotency_key)
    await conn.execute(
        "INSERT INTO events (user_id, event_type, payload, idempotency_key) VALUES (%s, %s, %s, %s)",  # noqa: E501
        (
            user_id,
            "deposit",
            {"rail": rail, "provider_event_id": provider_event_id},
            idempotency_key,
        ),
    )
    await conn.commit()
    return ApplyResult("processed", True)
