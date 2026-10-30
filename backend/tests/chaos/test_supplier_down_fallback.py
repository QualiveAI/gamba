import pytest
from unittest.mock import MagicMock

from core.delivery.supplier_client import purchase_with_fallback, SupplierDown
from core.delivery.errors import DeliveryDeferred


class MockSupplier:
    def __init__(self, key, behavior):
        self.key = key
        self.behavior = behavior
        self.called = 0

    def check_code(self, code, brand, region):
        self.called += 1
        if self.behavior == "down":
            raise SupplierDown("down")
        return {"status": "activated", "delivered_units": 100}


@pytest.mark.asyncio
async def test_supplier_down_fallback():
    primary = MockSupplier("primary", "down")
    fallback = MockSupplier("fallback", "ok")
    result = await purchase_with_fallback(suppliers=[primary, fallback], code="CODE", brand="b", region="US")
    assert result.status == "activated"
    assert primary.called == 1
    assert fallback.called == 1
    assert primary.called != 0
    assert fallback.called != 0


@pytest.mark.asyncio
async def test_both_suppliers_down():
    s1 = MockSupplier("s1", "down")
    s2 = MockSupplier("s2", "down")
    with pytest.raises(DeliveryDeferred):
        await purchase_with_fallback(suppliers=[s1, s2], code="CODE", brand="b", region="US")
    assert s1.called == 1
    assert s2.called == 1