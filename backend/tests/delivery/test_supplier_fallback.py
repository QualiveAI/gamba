import pytest

from core.delivery.errors import DeliveryDeferred
from core.delivery.supplier_client import (
    purchase_with_fallback,
    SupplierDown,
    DeliveryCheck,
)
from core.registry.registry import registry


class FakeSupplier:
    def __init__(self, result=None, exc=None):
        self.result = result
        self.exc = exc
        self.calls = 0

    def check_code(self, code, brand, region):
        self.calls += 1
        if self.exc:
            raise self.exc
        return self.result


@pytest.mark.asyncio
async def test_fallback_to_second_supplier():
    registry._items.clear()
    bad = FakeSupplier(exc=SupplierDown())
    bad.MANIFEST = {"key": "primary", "type": "supplier", "geo": None, "version": "1", "enabled_env": None}
    good = FakeSupplier(result=type("R", (), {"status": "activated", "delivered_units": 42})())
    good.MANIFEST = {"key": "fallback", "type": "supplier", "geo": None, "version": "1", "enabled_env": None}
    registry.register(bad)
    registry.register(good)

    res = await purchase_with_fallback(suppliers=[bad, good], code="X", brand="default", region="US")
    assert isinstance(res, DeliveryCheck)
    assert res.status == "activated"
    assert res.delivered_units == 42
    assert bad.calls == 1
    assert good.calls == 1
    assert res.status != "not_activated"


@pytest.mark.asyncio
async def test_all_suppliers_down_raises_deferred():
    registry._items.clear()
    bad1 = FakeSupplier(exc=SupplierDown())
    bad1.MANIFEST = {"key": "s1", "type": "supplier", "geo": None, "version": "1", "enabled_env": None}
    bad2 = FakeSupplier(exc=SupplierDown())
    bad2.MANIFEST = {"key": "s2", "type": "supplier", "geo": None, "version": "1", "enabled_env": None}
    registry.register(bad1)
    registry.register(bad2)

    with pytest.raises(DeliveryDeferred):
        await purchase_with_fallback(suppliers=[bad1, bad2], code="X", brand="default", region="US")


@pytest.mark.asyncio
async def test_unexpected_error_does_not_fallback():
    registry._items.clear()
    bad = FakeSupplier(exc=KeyError("boom"))
    bad.MANIFEST = {"key": "s1", "type": "supplier", "geo": None, "version": "1", "enabled_env": None}
    good = FakeSupplier(result=type("R", (), {"status": "activated", "delivered_units": 1})())
    good.MANIFEST = {"key": "s2", "type": "supplier", "geo": None, "version": "1", "enabled_env": None}
    registry.register(bad)
    registry.register(good)

    with pytest.raises(KeyError):
        await purchase_with_fallback(suppliers=[bad, good], code="X", brand="default", region="US")