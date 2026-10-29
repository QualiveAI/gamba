import inspect


class CrossCurrencyForbidden(Exception):
    pass


class DirectLedgerForbidden(Exception):
    pass


DEPOSIT_REASONS = {"deposit_units", "deposit_freebets"}


def _caller_is_apply() -> bool:
    for frame in inspect.stack():
        if "payments" in frame.filename and frame.filename.endswith("apply.py"):
            return True
    return False


async def post_entry(
    conn,
    user_id: int,
    currency: str,
    delta: int,
    reason: str,
    ref_id: str | None = None,
    source_game_key=None,
):
    if reason in DEPOSIT_REASONS and not _caller_is_apply():
        raise DirectLedgerForbidden("direct deposit ledger write forbidden")  # noqa: B904
    if currency not in ("units", "freebets"):
        raise ValueError("invalid currency")  # noqa: B904
    if currency == "units" and source_game_key == "cases_freebet":
        raise CrossCurrencyForbidden("freebet game cannot credit units")  # noqa: B904
    if currency == "freebets" and reason in ("withdraw_units", "withdrawal_request"):
        raise CrossCurrencyForbidden("freebets cannot be withdrawn")  # noqa: B904
    col = "balance_units" if currency == "units" else "balance_freebets"
    row = await (
        await conn.execute(f"SELECT {col} FROM users WHERE id = %s FOR UPDATE", (user_id,))
    ).fetchone()
    if row is None:
        raise ValueError("user not found")  # noqa: B904
    new_balance = int(row[col]) + int(delta)
    if new_balance < 0:
        raise ValueError("insufficient balance")  # noqa: B904
    await conn.execute(f"UPDATE users SET {col} = %s WHERE id = %s", (new_balance, user_id))
    await conn.execute(
        "INSERT INTO ledger_entries (user_id, currency, delta, reason, ref_id, balance_after) VALUES (%s, %s, %s, %s, %s, %s)",  # noqa: E501
        (user_id, currency, delta, reason, ref_id, new_balance),
    )
    agg = await (
        await conn.execute(
            "SELECT COALESCE(SUM(delta), 0) AS s FROM ledger_entries WHERE user_id = %s AND currency = %s",  # noqa: E501
            (user_id, currency),
        )
    ).fetchone()
    if int(agg["s"]) != new_balance:
        raise RuntimeError("ledger invariant broken")  # noqa: B904


async def reconcile(conn):
    rows = await (
        await conn.execute(
            "SELECT u.id, u.balance_units, u.balance_freebets, "
            "COALESCE(SUM(l.delta) FILTER (WHERE l.currency='units'),0) AS su, "
            "COALESCE(SUM(l.delta) FILTER (WHERE l.currency='freebets'),0) AS sf "
            "FROM users u LEFT JOIN ledger_entries l ON l.user_id = u.id "
            "GROUP BY u.id, u.balance_units, u.balance_freebets"
        )
    ).fetchall()
    broken = []
    for r in rows:
        if int(r["su"]) != int(r["balance_units"]) or int(r["sf"]) != int(r["balance_freebets"]):
            broken.append(int(r["id"]))
    return broken
