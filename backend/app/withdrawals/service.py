from datetime import UTC, datetime, timedelta

from app.antifraud.rules import evaluate
from app.giftcards import service as giftcard_service
from app.giftcards.verify import schedule_verify
from core.engine.ledger.ledger import post_entry

WITHDRAWAL_MIN_UNITS = 100000
DAILY_LIMIT = 1000000
WEEKLY_LIMIT = 200000


async def _recent_sum(conn, user_id, days):
    row = await (
        await conn.execute(
            "SELECT COALESCE(SUM(amount_units),0) AS s FROM withdrawals "
            "WHERE user_id = %s AND status IN ('pending','approved','frozen') AND created_at > now() - make_interval(days => %s)",  # noqa: E501
            (user_id, days),
        )
    ).fetchone()
    return int(row["s"]) if row else 0


async def _should_freeze(conn, user, amount, region):
    user_id = user["id"] if isinstance(user, dict) else user.id
    # withdrawal within 1h of deposit
    row = await (
        await conn.execute(
            "SELECT created_at FROM events WHERE user_id = %s AND event_type = 'deposit' ORDER BY created_at DESC LIMIT 1",  # noqa: E501
            (user_id,),
        )
    ).fetchone()
    if row and (datetime.now(UTC) - row["created_at"]).total_seconds() < 3600:
        return "withdrawal within 1h of deposit"
    # region mismatch
    user_region = user.get("region") if isinstance(user, dict) else getattr(user, "region", None)
    if user_region and user_region != region:
        return "region mismatch"
    return None


async def request(conn, user, amount, region):
    user_id = user["id"] if isinstance(user, dict) else user.id
    created = (
        user.get("created_at") if isinstance(user, dict) else getattr(user, "created_at", None)
    )  # noqa: E501
    if created is not None:
        if isinstance(created, str):
            created = datetime.fromisoformat(created.replace("Z", "+00:00"))
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        if (datetime.now(UTC) - created).total_seconds() < 86400:
            raise ValueError("account too new")  # noqa: B904
    if amount < WITHDRAWAL_MIN_UNITS:
        raise ValueError("below minimum")  # noqa: B904
    daily = await _recent_sum(conn, user_id, 1)
    if daily + amount > DAILY_LIMIT:
        raise ValueError("daily limit exceeded")  # noqa: B904
    weekly = await _recent_sum(conn, user_id, 7)
    if weekly + amount > WEEKLY_LIMIT:
        raise ValueError("weekly limit exceeded")  # noqa: B904
    user_units = (
        user.get("balance_units") if isinstance(user, dict) else getattr(user, "balance_units", 0)
    )
    user_freebets = (
        user.get("balance_freebets")
        if isinstance(user, dict)
        else getattr(user, "balance_freebets", 0)
    )
    if (user_units or 0) == 0 and (user_freebets or 0) > 0:
        raise ValueError("risk blocked")  # noqa: B904
    risk = await evaluate(conn, user, region)
    if risk.level == "high":
        raise ValueError("high risk")  # noqa: B904
    freeze_reason = await _should_freeze(conn, user, amount, region)
    try:
        code_id = await giftcard_service.reserve(conn, user_id, region, amount)
    except ValueError as e:
        raise ValueError(str(e))  # noqa: B904
    await post_entry(conn, user_id, "units", -int(amount), "withdrawal_request", "withdrawal")
    status = "frozen" if freeze_reason else "pending"
    cur = await conn.execute(
        "INSERT INTO withdrawals (user_id, amount_units, region, status, code_id, antifraud_score, hold_until) "  # noqa: E501
        "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (
            user_id,
            amount,
            region,
            status,
            code_id,
            risk.level,
            datetime.now(UTC) + timedelta(days=1),
        ),  # noqa: E501
    )
    wid = (await cur.fetchone())["id"]
    if freeze_reason:
        await conn.execute(
            "INSERT INTO withdrawal_freezes (withdrawal_id, reason) VALUES (%s, %s)",
            (wid, freeze_reason),  # noqa: E501
        )
    await conn.commit()
    return wid


async def approve(conn, withdrawal_id):
    row = await (
        await conn.execute(
            "SELECT id, user_id, code_id, amount_units, status FROM withdrawals WHERE id = %s FOR UPDATE",  # noqa: E501
            (withdrawal_id,),  # noqa: E501
        )
    ).fetchone()
    if row is None:
        raise ValueError("withdrawal not found")  # noqa: B904
    if row["status"] not in ("pending", "frozen"):
        raise ValueError("not approvable")  # noqa: B904
    # unfreeze if frozen
    await conn.execute(
        "UPDATE withdrawals SET status = 'approved', decided_at = now() WHERE id = %s",
        (withdrawal_id,),  # noqa: E501
    )
    code = await giftcard_service.issue(conn, row["code_id"])
    fee = int(row["amount_units"] * 0.20)
    await conn.execute("UPDATE withdrawals SET fee_units = %s WHERE id = %s", (fee, withdrawal_id))
    await schedule_verify(conn, row["code_id"])
    await conn.commit()
    return code


async def reject(conn, withdrawal_id, reason):
    row = await (
        await conn.execute(
            "SELECT id, user_id, amount_units, code_id, status FROM withdrawals WHERE id = %s FOR UPDATE",  # noqa: E501
            (withdrawal_id,),  # noqa: E501
        )
    ).fetchone()
    if row is None:
        raise ValueError("withdrawal not found")  # noqa: B904
    if row["status"] not in ("pending", "frozen"):
        raise ValueError("not rejectable")  # noqa: B904
    await conn.execute(
        "UPDATE gift_codes SET status = 'available', reserved_by = NULL, reserved_at = NULL WHERE id = %s",  # noqa: E501
        (row["code_id"],),
    )
    await post_entry(
        conn,
        row["user_id"],
        int(row["amount_units"]),
        "withdrawal_reject_refund",
        f"withdrawal:{withdrawal_id}",
    )  # noqa: E501
    await conn.execute(
        "UPDATE withdrawals SET status = 'rejected', reason = %s, decided_at = now() WHERE id = %s",
        (reason, withdrawal_id),
    )
    await conn.commit()
    return True


async def unfreeze(conn, withdrawal_id):
    await conn.execute(
        "UPDATE withdrawal_freezes SET unfrozen_at = now() WHERE withdrawal_id = %s",
        (withdrawal_id,),  # noqa: E501
    )
    await conn.execute("UPDATE withdrawals SET status = 'pending' WHERE id = %s", (withdrawal_id,))
    await conn.commit()
    return True


async def finalize(conn, withdrawal_id):
    import asyncio

    from core.delivery.router import DeliveryDeferred, SettlementMismatch, verify_delivery

    row = await (
        await conn.execute(
            "SELECT id, code_id, amount_units, fee_units, status, idempotency_key FROM withdrawals WHERE id = %s FOR UPDATE",  # noqa: E501
            (withdrawal_id,),
        )
    ).fetchone()
    if row is None:
        raise ValueError("withdrawal not found")  # noqa: B904
    if row["status"] == "issued":
        return {"status": "issued"}
    if row["status"] not in ("approved", "pending"):
        raise ValueError("not finalizable")  # noqa: B904
    idem = row.get("idempotency_key") if isinstance(row, dict) else None
    if not idem:
        idem = f"wd:{withdrawal_id}"
        await conn.execute(
            "UPDATE withdrawals SET idempotency_key = %s WHERE id = %s", (idem, withdrawal_id)
        )
        await conn.commit()
    try:
        result = await asyncio.wait_for(verify_delivery(row["code_id"]), timeout=15)
    except TimeoutError:
        await conn.execute(
            "UPDATE withdrawals SET status = 'manual_review' WHERE id = %s", (withdrawal_id,)
        )
        await conn.commit()
        return {"status": "manual_review"}
    except (SettlementMismatch, DeliveryDeferred) as e:
        if isinstance(e, SettlementMismatch):
            await conn.execute(
                "UPDATE withdrawals SET status = 'manual_review' WHERE id = %s", (withdrawal_id,)
            )
            await conn.commit()
            return {"status": "manual_review"}
        await conn.execute(
            "UPDATE withdrawals SET status = 'pending_supplier' WHERE id = %s", (withdrawal_id,)
        )
        await conn.commit()
        return {"status": "pending_supplier"}
    code = await (
        await conn.execute("SELECT nominal_units FROM gift_codes WHERE id = %s", (row["code_id"],))
    ).fetchone()
    fee = int(row.get("fee_units", 0) or 0)
    expected_nominal = int(row["amount_units"]) - fee
    if code and int(code["nominal_units"]) != expected_nominal:
        await conn.execute(
            "UPDATE withdrawals SET status = 'manual_review' WHERE id = %s", (withdrawal_id,)
        )
        await conn.commit()
        return {"status": "manual_review"}
    verified = getattr(result, "verified", None)
    amount_match = getattr(result, "amount_match", None)
    if verified is None and isinstance(result, dict):
        verified = result.get("verified")
        amount_match = result.get("amount_match")
    if not (verified and amount_match):
        await conn.execute(
            "UPDATE withdrawals SET status = 'manual_review' WHERE id = %s", (withdrawal_id,)
        )
        await conn.commit()
        return {"status": "manual_review"}
    await conn.execute(
        "UPDATE withdrawals SET status = 'issued', decided_at = now() WHERE id = %s",
        (withdrawal_id,),
    )
    await conn.commit()
    return {"status": "issued"}
