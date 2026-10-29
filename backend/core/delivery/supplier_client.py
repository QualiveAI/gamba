import asyncio
import time
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


_CIRCUIT: dict[str, dict] = {}
_CIRCUIT_THRESHOLD = 3
_CIRCUIT_RESET_SECONDS = 60


def _supplier_key(supplier) -> str:
    return getattr(supplier, "key", None) or str(id(supplier))


def _circuit_open(supplier) -> bool:
    state = _CIRCUIT.get(_supplier_key(supplier))
    if not state:
        return False
    if state["failures"] < _CIRCUIT_THRESHOLD:
        return False
    if time.time() - state["opened_at"] >= _CIRCUIT_RESET_SECONDS:
        _CIRCUIT.pop(_supplier_key(supplier), None)
        return False
    return True


def _record_failure(supplier) -> None:
    key = _supplier_key(supplier)
    state = _CIRCUIT.setdefault(key, {"failures": 0, "opened_at": time.time()})
    state["failures"] += 1
    state["opened_at"] = time.time()


def _record_success(supplier) -> None:
    _CIRCUIT.pop(_supplier_key(supplier), None)


def _candidate_suppliers(region):
    items = []
    if region is not None:
        primary = registry.get("supplier", region)
        if primary is not None:
            items.append(primary)
    for (t, k, _g), obj in getattr(registry, "_items", {}).items():
        if t == "supplier" and obj not in items:
            items.append(obj)
    mock = registry.get("supplier", "mock")
    if mock is not None and mock not in items:
        items.append(mock)
    seen = set()
    out = []
    for s in items:
        if id(s) in seen:
            continue
        seen.add(id(s))
        out.append(s)
    return out


async def _run_supplier(supplier, code, brand, region):
    if _circuit_open(supplier):
        raise SupplierDown("circuit_open")
    check_code = getattr(supplier, "check_code", None)
    if check_code is None:
        raise DeliveryDeferred(getattr(supplier, "key", "unknown"), "no_check_code")
    try:
        result = check_code(code, brand, region)
        if asyncio.iscoroutine(result):
            result = await result
    except (SupplierDown, TimeoutError) as e:
        _record_failure(supplier)
        raise
    except Exception:
        _record_failure(supplier)
        raise
    _record_success(supplier)
    status = getattr(result, "status", None) or (
        result.get("status") if isinstance(result, dict) else "unknown"
    )
    delivered = getattr(result, "delivered_units", None)
    if delivered is None:
        delivered = result.get("delivered_units", 0) if isinstance(result, dict) else 0
    if status not in ("activated", "not_activated", "unknown"):
        status = "unknown"
    return DeliveryCheck(status=status, delivered_units=int(delivered))


async def purchase_with_fallback(*args, **kwargs):
    delivery_id = kwargs.get("delivery_id")
    if delivery_id is None and args and not isinstance(args[0], (list, tuple, dict)):
        delivery_id = args[0]
    suppliers = kwargs.get("suppliers")
    code = kwargs.get("code")
    brand = kwargs.get("brand", "default")
    region = kwargs.get("region")

    if delivery_id is not None and code is None:
        async with get_conn() as conn:
            row = await (
                await conn.execute(
                    "SELECT code, region, nominal_units FROM gift_codes WHERE id = %s",
                    (delivery_id,),
                )
            ).fetchone()
        if row is None:
            raise DeliveryDeferred(delivery_id, "not_found")
        code = row["code"]
        region = row["region"]

    if suppliers is None:
        suppliers = _candidate_suppliers(region)

    last_error = None
    for supplier in suppliers or []:
        try:
            return await _run_supplier(supplier, code, brand, region)
        except (SupplierDown, TimeoutError) as e:
            last_error = e
            continue
        except DeliveryDeferred:
            raise
    raise DeliveryDeferred(delivery_id, "supplier_down" if last_error is None else str(last_error))


async def check_delivery(delivery_id):
    return await purchase_with_fallback(delivery_id=delivery_id)