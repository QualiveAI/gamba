import asyncio
import contextlib

from app.db import get_conn
from app.withdrawals import service


class FakeSupplier:
    def __init__(self, result=None, exc=None, sleep=0):
        self.result = result
        self.exc = exc
        self.sleep = sleep
        self.calls = 0

    def check_code(self, code, brand, region):
        self.calls += 1
        if self.sleep:
            import time

            time.sleep(self.sleep)
        if self.exc:
            raise self.exc  # noqa: B904
        return self.result


async def _setup(conn):
    from core.registry.registry import registry

    registry._items.clear()
    from core.registry.registry import registry

    registry._items.clear()
    await conn.execute(
        "DELETE FROM withdrawals WHERE user_id IN (SELECT id FROM users WHERE telegram_id = %s)",
        (999030,),
    )
    await conn.execute("DELETE FROM gift_codes WHERE code = %s", ("VERIFY1",))
    await conn.execute("DELETE FROM users WHERE telegram_id = %s", (999030,))
    cur = await conn.execute(
        "INSERT INTO users (telegram_id, balance_units, region, created_at) VALUES (%s, %s, %s, now() - interval '2 days') RETURNING id",  # noqa: E501
        (999030, 100000, "US"),
    )
    uid = (await cur.fetchone())["id"]
    await conn.execute(
        "INSERT INTO gift_codes (code, region, nominal_units, status) VALUES (%s, %s, %s, 'reserved')",  # noqa: E501
        ("VERIFY1", "US", 100000),
    )
    code_row = await (
        await conn.execute("SELECT id FROM gift_codes WHERE code = %s", ("VERIFY1",))
    ).fetchone()
    code_id = code_row["id"]
    cur = await conn.execute(
        "INSERT INTO withdrawals (user_id, amount_units, region, status, code_id) VALUES (%s, %s, %s, 'approved', %s) RETURNING id",  # noqa: E501
        (uid, 100000, "US", code_id),
    )
    wid = (await cur.fetchone())["id"]
    await conn.commit()
    return uid, wid, code_id

async def test_happy_issued():
    async with get_conn() as conn:
        uid, wid, code_id = await _setup(conn)
        sup = FakeSupplier(
            result=type("R", (), {"status": "activated", "delivered_units": 100000})()
        )
        sup.MANIFEST = {
            "key": "US",
            "type": "supplier",
            "geo": None,
            "version": "1",
            "enabled_env": None,
        }
        registry = __import__("core.registry.registry", fromlist=["registry"]).registry
        registry._items.clear()
        registry.register(sup)
        res = await service.finalize(conn, wid)
        assert res["status"] == "issued"
        row = await (
            await conn.execute("SELECT status FROM withdrawals WHERE id = %s", (wid,))
        ).fetchone()
        assert row["status"] == "issued"
        assert row["status"] != "manual_review"
        assert sup.calls == 1

async def test_mismatch_manual_review():
    async with get_conn() as conn:
        uid, wid, code_id = await _setup(conn)
        await conn.execute("UPDATE gift_codes SET nominal_units = 99999 WHERE id = %s", (code_id,))
        await conn.commit()
        sup = FakeSupplier(
            result=type("R", (), {"status": "activated", "delivered_units": 99999})()
        )
        sup.MANIFEST = {
            "key": "US",
            "type": "supplier",
            "geo": None,
            "version": "1",
            "enabled_env": None,
        }
        registry = __import__("core.registry.registry", fromlist=["registry"]).registry
        registry._items.clear()
        registry.register(sup)
        res = await service.finalize(conn, wid)
        assert res["status"] == "manual_review"
        row = await (
            await conn.execute("SELECT status FROM withdrawals WHERE id = %s", (wid,))
        ).fetchone()
        assert row["status"] == "manual_review"
        assert row["status"] != "issued"

async def test_deferred_pending_supplier():
    async with get_conn() as conn:
        uid, wid, code_id = await _setup(conn)

        from core.delivery.supplier_client import SupplierDown

        sup = FakeSupplier(exc=SupplierDown())
        sup.MANIFEST = {
            "key": "US",
            "type": "supplier",
            "geo": None,
            "version": "1",
            "enabled_env": None,
        }
        registry = __import__("core.registry.registry", fromlist=["registry"]).registry
        registry._items.clear()
        registry.register(sup)
        res = await service.finalize(conn, wid)
        assert res["status"] == "pending_supplier"
        row = await (
            await conn.execute("SELECT status FROM withdrawals WHERE id = %s", (wid,))
        ).fetchone()
        assert row["status"] == "pending_supplier"
        assert row["status"] != "issued"

async def test_not_activated_deferred():
    async with get_conn() as conn:
        uid, wid, code_id = await _setup(conn)
        sup = FakeSupplier(
            result=type("R", (), {"status": "not_activated", "delivered_units": 0})()
        )
        sup.MANIFEST = {
            "key": "US",
            "type": "supplier",
            "geo": None,
            "version": "1",
            "enabled_env": None,
        }
        registry = __import__("core.registry.registry", fromlist=["registry"]).registry
        registry._items.clear()
        registry.register(sup)
        with contextlib.suppress(Exception):
            await service.finalize(conn, wid)
        row = await (
            await conn.execute("SELECT status FROM withdrawals WHERE id = %s", (wid,))
        ).fetchone()
        assert row["status"] != "issued"

async def test_timeout_manual_review():
    async with get_conn() as conn:
        uid, wid, code_id = await _setup(conn)

        class SlowSupplier(FakeSupplier):
            async def check_code(self, code, brand, region):
                await asyncio.sleep(20)
                return type("R", (), {"status": "activated", "delivered_units": 100000})()

        sup = SlowSupplier()
        sup.MANIFEST = {
            "key": "US",
            "type": "supplier",
            "geo": None,
            "version": "1",
            "enabled_env": None,
        }
        registry = __import__("core.registry.registry", fromlist=["registry"]).registry
        registry._items.clear()
        registry.register(sup)
        res = await service.finalize(conn, wid)
        assert res["status"] == "manual_review"
        row = await (
            await conn.execute("SELECT status FROM withdrawals WHERE id = %s", (wid,))
        ).fetchone()
        assert row["status"] == "manual_review"
        assert row["status"] != "issued"


def test_no_stub_guard():
    import inspect

    import core.delivery.settlement as s

    src = inspect.getsource(s.verify_delivery)
    assert 'return {"verified": True' not in src
    assert "raise SettlementMismatch" in src or "SettlementMismatch(" in src  # noqa: B904

async def test_fee_semantics_happy():
    async with get_conn() as conn:
        await conn.execute(
            "DELETE FROM withdrawals WHERE user_id IN (SELECT id FROM users WHERE telegram_id = %s)",  # noqa: E501
            (999031,),
        )
        await conn.execute("DELETE FROM gift_codes WHERE code = %s", ("VERIFY2",))
        await conn.execute("DELETE FROM users WHERE telegram_id = %s", (999031,))
        cur = await conn.execute(
            "INSERT INTO users (telegram_id, balance_units, region, created_at) VALUES (%s, %s, %s, now() - interval '2 days') RETURNING id",  # noqa: E501
            (999031, 100000, "US"),
        )
        uid = (await cur.fetchone())["id"]
        await conn.execute(
            "INSERT INTO gift_codes (code, region, nominal_units, status) VALUES (%s, %s, %s, 'reserved')",  # noqa: E501
            ("VERIFY2", "US", 800),
        )
        code_row = await (
            await conn.execute("SELECT id FROM gift_codes WHERE code = %s", ("VERIFY2",))
        ).fetchone()
        code_id = code_row["id"]
        cur = await conn.execute(
            "INSERT INTO withdrawals (user_id, amount_units, region, status, code_id, fee_units) VALUES (%s, %s, %s, 'approved', %s, %s) RETURNING id",  # noqa: E501
            (uid, 1000, "US", code_id, 200),
        )
        wid = (await cur.fetchone())["id"]
        await conn.commit()

        sup = FakeSupplier(result=type("R", (), {"status": "activated", "delivered_units": 800})())
        sup.MANIFEST = {
            "key": "US",
            "type": "supplier",
            "geo": None,
            "version": "1",
            "enabled_env": None,
        }
        registry = __import__("core.registry.registry", fromlist=["registry"]).registry
        registry._items.clear()
        registry.register(sup)
        res = await service.finalize(conn, wid)
        assert res["status"] == "issued"
        row = await (
            await conn.execute("SELECT status FROM withdrawals WHERE id = %s", (wid,))
        ).fetchone()
        assert row["status"] == "issued"
        assert row["status"] != "manual_review"

        # negative: delivered 1000 (wrong)
        await conn.execute("DELETE FROM withdrawals WHERE id = %s", (wid,))
        cur = await conn.execute(
            "INSERT INTO withdrawals (user_id, amount_units, region, status, code_id, fee_units) VALUES (%s, %s, %s, 'approved', %s, %s) RETURNING id",  # noqa: E501
            (uid, 1000, "US", code_id, 200),
        )
        wid2 = (await cur.fetchone())["id"]
        await conn.commit()
        sup2 = FakeSupplier(
            result=type("R", (), {"status": "activated", "delivered_units": 1000})()
        )
        sup2.MANIFEST = {
            "key": "US",
            "type": "supplier",
            "geo": None,
            "version": "1",
            "enabled_env": None,
        }
        registry.register(sup2)
        res2 = await service.finalize(conn, wid2)
        assert res2["status"] == "manual_review"
        row2 = await (
            await conn.execute("SELECT status FROM withdrawals WHERE id = %s", (wid2,))
        ).fetchone()
        assert row2["status"] == "manual_review"
        assert row2["status"] != "issued"

async def test_supplier_down_deferred():
    async with get_conn() as conn:
        uid, wid, code_id = await _setup(conn)
        from core.delivery.router import DeliveryDeferred, verify_delivery
        from core.delivery.supplier_client import SupplierDown

        sup = FakeSupplier(exc=SupplierDown())
        sup.MANIFEST = {
            "key": "US",
            "type": "supplier",
            "geo": None,
            "version": "1",
            "enabled_env": None,
        }
        registry = __import__("core.registry.registry", fromlist=["registry"]).registry
        registry._items.clear()
        registry.register(sup)

        raised = None
        try:
            await verify_delivery(code_id)
        except Exception as e:  # noqa: BLE001
            raised = e
        assert type(raised) is DeliveryDeferred
        assert getattr(raised, "reason", None) == "supplier_down"

        res = await service.finalize(conn, wid)
        assert res["status"] == "pending_supplier"
        row = await (
            await conn.execute("SELECT status FROM withdrawals WHERE id = %s", (wid,))
        ).fetchone()
        assert row["status"] == "pending_supplier"
        assert row["status"] != "issued"


async def test_supplier_bug_propagates():
    async with get_conn() as conn:
        uid, wid, code_id = await _setup(conn)

        sup = FakeSupplier(exc=KeyError("missing_field"))
        sup.MANIFEST = {
            "key": "US",
            "type": "supplier",
            "geo": None,
            "version": "1",
            "enabled_env": None,
        }
        registry = __import__("core.registry.registry", fromlist=["registry"]).registry
        registry._items.clear()
        registry.register(sup)

        raised = None
        try:
            await service.finalize(conn, wid)
        except KeyError as e:
            raised = e
        assert type(raised) is KeyError
        assert raised.args == ("missing_field",)

        row = await (
            await conn.execute("SELECT status FROM withdrawals WHERE id = %s", (wid,))
        ).fetchone()
        assert row["status"] == "approved"
        assert row["status"] != "pending_supplier"
        assert row["status"] != "issued"

