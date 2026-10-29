from datetime import UTC


async def schedule_verify(conn, code_id: int):
    # record verify attempt; real check via partner API or admin
    await conn.execute(
        "UPDATE gift_codes SET verify_attempts = verify_attempts + 0 WHERE id = %s", (code_id,)
    )
    await conn.commit()


async def run_verification(conn, code_id: int):
    row = await (
        await conn.execute(
            "SELECT id, code, status, issued_at FROM gift_codes WHERE id = %s", (code_id,)
        )
    ).fetchone()
    if row is None:
        return
    # if not activated within 24h, return to pool
    from datetime import datetime, timedelta

    if (
        row["status"] == "issued"
        and row["issued_at"]
        and (datetime.now(UTC) - row["issued_at"]) > timedelta(hours=24)
    ):  # noqa: E501
        await conn.execute(
            "UPDATE gift_codes SET status = 'available', reserved_by = NULL, reserved_at = NULL WHERE id = %s",  # noqa: E501
            (code_id,),
        )
        await conn.commit()
