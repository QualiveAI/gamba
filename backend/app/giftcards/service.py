import csv
from datetime import UTC, datetime, timedelta


async def import_csv(conn, path: str) -> int:
    inserted = 0
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = (row.get("code") or "").strip()
            region = (row.get("region") or "").strip()
            nominal = int(row.get("nominal_units") or 0)
            if not code or not region:
                continue
            cur = await conn.execute(
                "INSERT INTO gift_codes (code, region, nominal_units) VALUES (%s, %s, %s) ON CONFLICT (code) DO NOTHING",  # noqa: E501
                (code, region, nominal),
            )
            if cur.rowcount and cur.rowcount > 0:
                inserted += 1
    await conn.commit()
    return inserted


async def reserve(conn, user_id: int, region: str, nominal_units: int) -> int:
    row = await (
        await conn.execute(
            "SELECT id FROM gift_codes WHERE status = 'available' AND region = %s AND nominal_units = %s ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1",  # noqa: E501
            (region, nominal_units),
        )
    ).fetchone()
    if row is None:
        raise ValueError("no available code")  # noqa: B904
    code_id = int(row["id"])
    await conn.execute(
        "UPDATE gift_codes SET status = 'reserved', reserved_by = %s, reserved_at = %s WHERE id = %s",  # noqa: E501
        (user_id, datetime.now(UTC), code_id),
    )
    await conn.commit()
    return code_id


async def issue(conn, reservation_id: int) -> str:
    row = await (
        await conn.execute(
            "SELECT code, status FROM gift_codes WHERE id = %s FOR UPDATE", (reservation_id,)
        )
    ).fetchone()
    if row is None:
        raise ValueError("reservation not found")  # noqa: B904
    if row["status"] != "reserved":
        raise ValueError("not reserved")  # noqa: B904
    await conn.execute(
        "UPDATE gift_codes SET status = 'issued', issued_at = %s WHERE id = %s",
        (datetime.now(UTC), reservation_id),
    )
    await conn.commit()
    return row["code"]


async def mark_activated(conn, code: str) -> None:
    await conn.execute(
        "UPDATE gift_codes SET status = 'activated', activated_at = %s WHERE code = %s",
        (datetime.now(UTC), code),
    )
    await conn.commit()


async def release_expired(conn) -> int:
    cutoff = datetime.now(UTC) - timedelta(minutes=15)
    cur = await conn.execute(
        "UPDATE gift_codes SET status = 'available', reserved_by = NULL, reserved_at = NULL "
        "WHERE status = 'reserved' AND reserved_at IS NOT NULL AND reserved_at < %s",
        (cutoff,),
    )
    await conn.commit()
    return cur.rowcount or 0


async def schedule_verify(conn, code_id: int):
    # record a pending verification; background job will check after 24h
    await conn.execute(
        "UPDATE gift_codes SET verify_attempts = verify_attempts + 0 WHERE id = %s", (code_id,)
    )
    await conn.commit()
