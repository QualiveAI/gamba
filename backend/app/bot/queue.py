"""Lease + bounded retry для inbox/outbox; сообщения не исчезают при падении worker."""

import uuid

from app.bot.client import retry_delay
from app.bot.security import LEASE_SECONDS, MAX_ATTEMPTS

_TABLES = frozenset({"bot_inbox", "bot_outbox"})


def _table(value: str) -> str:
    if value not in _TABLES:
        raise ValueError("unknown_bot_queue")
    return value


async def claim(conn, table: str):
    table = _table(table)
    await conn.execute(
        f"UPDATE {table} SET status = 'dead', last_error_code = 'retry_exhausted', "
        "finished_at = now(), lease_until = NULL, claim_token = NULL "
        "WHERE status IN ('pending', 'processing') AND attempts >= %s "
        "AND (lease_until IS NULL OR lease_until < now())",
        (MAX_ATTEMPTS,),
    )
    ordered = ""
    if table == "bot_inbox":
        ordered = (
            "AND NOT EXISTS (SELECT 1 FROM bot_inbox older WHERE older.bot_id = q.bot_id "
            "AND older.id < q.id AND older.status IN ('pending', 'processing')) "
        )
    return await (
        await conn.execute(
            f"WITH ready AS (SELECT q.id FROM {table} q WHERE q.attempts < %s AND "
            "((q.status = 'pending' AND q.available_at <= now()) OR "
            "(q.status = 'processing' AND q.lease_until < now())) "
            + ordered
            + "ORDER BY q.id LIMIT 1 FOR UPDATE SKIP LOCKED) "
            f"UPDATE {table} q SET status = 'processing', attempts = q.attempts + 1, "
            "lease_until = now() + %s * interval '1 second', claim_token = %s "
            "FROM ready WHERE q.id = ready.id RETURNING q.*",
            (MAX_ATTEMPTS, LEASE_SECONDS, uuid.uuid4()),
        )
    ).fetchone()


async def finish(conn, table: str, job: dict, *, dropped: bool = False):
    table = _table(table)
    await conn.execute(
        f"UPDATE {table} SET status = %s, finished_at = now(), lease_until = NULL, "
        "claim_token = NULL, last_error_code = NULL WHERE id = %s AND claim_token = %s",
        ("dropped" if dropped else "done", job["id"], job["claim_token"]),
    )


async def fail(
    conn, table: str, job: dict, *, code: str, retryable: bool, retry_after: int | None = None
):
    table = _table(table)
    pending = retryable and job["attempts"] < MAX_ATTEMPTS
    await conn.execute(
        f"UPDATE {table} SET status = %s, available_at = now() + %s * interval '1 second', "
        "last_error_code = %s, lease_until = NULL, claim_token = NULL, "
        "finished_at = CASE WHEN %s THEN NULL ELSE now() END "
        "WHERE id = %s AND claim_token = %s",
        (
            "pending" if pending else "dead",
            retry_delay(job["attempts"], retry_after),
            code,
            pending,
            job["id"],
            job["claim_token"],
        ),
    )
