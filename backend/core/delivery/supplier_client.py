import asyncio
from dataclasses import dataclass
from typing import Literal

from app.db import get_conn
from core.delivery.errors import DeliveryDeferred
from core.registry.registry import registry


@dataclass
class DeliveryCheck:
    status: Literal["activated", "not_activated", "unknown"]
    delivered_units: int
    provider_error: str | None = None


class SupplierDown(Exception):
    pass


async def check_delivery(delivery_id):
    async with get_conn() as conn:
        row = await (
            await conn.execute(
                "SELECT code, region, nominal_units FROM gift_codes WHERE id = %s", (delivery_id,)
            )
        ).fetchone()
    if row is None:
        raise DeliveryDeferred(delivery_id, "not_found")  # noqa: B904
    region = row["region"]
    supplier = registry.get("supplier", region) or registry.get("supplier", "default")
    if supplier is None:
        # allow mock supplier under key 'mock'
        supplier = registry.get("supplier", "mock")
    if supplier is None:
        raise DeliveryDeferred(delivery_id, "no_supplier")  # noqa: B904
    check_code = getattr(supplier, "check_code", None)
    if check_code is None:
        raise DeliveryDeferred(delivery_id, "no_check_code")  # noqa: B904
    try:
        result = check_code(row["code"], "default", region)
        if asyncio.iscoroutine(result):
            result = await result
    except (SupplierDown, TimeoutError) as e:
        raise DeliveryDeferred(delivery_id, "supplier_down") from e  # noqa: B904
    status = getattr(result, "status", None) or (
        result.get("status") if isinstance(result, dict) else "unknown"
    )
    delivered = getattr(result, "delivered_units", None) or (
        result.get("delivered_units", 0) if isinstance(result, dict) else 0
    )
    if status not in ("activated", "not_activated", "unknown"):
        status = "unknown"
    return DeliveryCheck(status=status, delivered_units=int(delivered))
