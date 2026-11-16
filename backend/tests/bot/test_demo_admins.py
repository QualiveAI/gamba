"""Демо-доступ для записи роликов: /grant, /revoke, /topup.

Только корневые админы (settings.admin_ids) выдают доступ; накрутка идёт через
обычный ledger, поэтому инвариант балансов сохраняется.
"""

from app.bot.demo_admins import demo_admin_ids
from app.bot.dispatcher import _admin_command
from app.bot.users import ensure_telegram_user
from app.config import settings
from app.db import get_conn

OWNER_TG = 850000001
DEMO_TG = 850000002


async def _user(telegram_id: int):
    async with get_conn() as conn, conn.transaction():
        return dict(await ensure_telegram_user(conn, telegram_id=telegram_id, username="tester"))


def _allow(monkeypatch, tg: int):
    monkeypatch.setattr(settings, "admin_telegram_ids", str(tg))


async def _balances(conn, user_id: int) -> tuple[int, int]:
    row = await (
        await conn.execute(
            "SELECT balance_units, balance_freebets FROM users WHERE id = %s", (user_id,)
        )
    ).fetchone()
    return int(row["balance_units"]), int(row["balance_freebets"])


async def test_topup_denied_for_strangers(monkeypatch):
    _allow(monkeypatch, OWNER_TG)
    user = await _user(DEMO_TG)
    async with get_conn() as conn, conn.transaction():
        template, extra = await _admin_command(
            conn, command="topup", arg="5000", user=user, sender_telegram_id=DEMO_TG
        )
    assert template == "admin_topup" and extra == {"action": "denied"}
    async with get_conn() as conn:
        # Стартовый баланс нового пользователя: 50 freebets приветственных.
        assert await _balances(conn, user["id"]) == (0, 50)


async def test_root_admin_can_topup_via_ledger(monkeypatch):
    _allow(monkeypatch, 850000011)
    user = await _user(850000011)
    async with get_conn() as conn, conn.transaction():
        template, extra = await _admin_command(
            conn, command="topup", arg="5000", user=user, sender_telegram_id=850000011
        )
    assert template == "admin_topup"
    assert extra == {"action": "credited", "amount": 5000, "currency": "units"}
    async with get_conn() as conn:
        units, freebets = await _balances(conn, user["id"])
        assert units == 5000 and freebets == 50
        # Зачисление прошло через ledger: причина и сумма видны в записи.
        row = await (
            await conn.execute(
                "SELECT reason, delta FROM ledger_entries WHERE user_id = %s AND reason = 'demo_topup'",
                (user["id"],),
            )
        ).fetchone()
        assert dict(row) == {"reason": "demo_topup", "delta": 5000}


async def test_topup_cobre_credits_freebets(monkeypatch):
    _allow(monkeypatch, 850000012)
    user = await _user(850000012)
    async with get_conn() as conn, conn.transaction():
        _, extra = await _admin_command(
            conn, command="topup", arg="500 cobre", user=user, sender_telegram_id=850000012
        )
    assert extra == {"action": "credited", "amount": 500, "currency": "freebets"}
    async with get_conn() as conn:
        units, freebets = await _balances(conn, user["id"])
        assert units == 0 and freebets == 550


async def test_invalid_amount_denied(monkeypatch):
    _allow(monkeypatch, 850000013)
    user = await _user(850000013)
    async with get_conn() as conn, conn.transaction():
        for arg in ("0", "-1", "99999999999", "abc"):
            _, extra = await _admin_command(
                conn, command="topup", arg=arg, user=user, sender_telegram_id=850000013
            )
            assert extra == {"action": "denied"}, arg
    async with get_conn() as conn:
        assert await _balances(conn, user["id"]) == (0, 50)


async def test_grant_then_topup_then_revoke(monkeypatch):
    _allow(monkeypatch, OWNER_TG)
    owner = await _user(OWNER_TG)
    demo = await _user(DEMO_TG)
    async with get_conn() as conn, conn.transaction():
        # stranger denied
        _, extra = await _admin_command(
            conn, command="topup", arg="100", user=demo, sender_telegram_id=DEMO_TG
        )
        assert extra == {"action": "denied"}
        # root grants
        _, extra = await _admin_command(
            conn, command="grant", arg=str(DEMO_TG), user=owner, sender_telegram_id=OWNER_TG
        )
        assert extra == {"action": "granted", "target": str(DEMO_TG)}
    # granted user may top up himself
    async with get_conn() as conn:
        assert DEMO_TG in await demo_admin_ids(conn)
    async with get_conn() as conn, conn.transaction():
        _, extra = await _admin_command(
            conn, command="topup", arg="100", user=demo, sender_telegram_id=DEMO_TG
        )
        assert extra == {"action": "credited", "amount": 100, "currency": "units"}
    async with get_conn() as conn, conn.transaction():
        _, extra = await _admin_command(
            conn, command="revoke", arg=str(DEMO_TG), user=owner, sender_telegram_id=OWNER_TG
        )
        assert extra == {"action": "revoked", "target": str(DEMO_TG)}
    async with get_conn() as conn:
        assert DEMO_TG not in await demo_admin_ids(conn)
    async with get_conn() as conn, conn.transaction():
        _, extra = await _admin_command(
            conn, command="topup", arg="100", user=demo, sender_telegram_id=DEMO_TG
        )
        assert extra == {"action": "denied"}


async def test_grant_requires_root(monkeypatch):
    _allow(monkeypatch, OWNER_TG)
    stranger = await _user(850000003)
    async with get_conn() as conn, conn.transaction():
        _, extra = await _admin_command(
            conn, command="grant", arg=str(DEMO_TG), user=stranger, sender_telegram_id=850000003
        )
    assert extra == {"action": "denied"}
