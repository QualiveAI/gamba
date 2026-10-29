from app.db import get_conn
from core.contracts.prize import VerificationResult
from core.delivery.errors import DeliveryDeferred, SettlementMismatch
from core.delivery.supplier_client import check_delivery


async def verify_delivery(delivery_id):
    check = await check_delivery(delivery_id)
    async with get_conn() as conn:
        row = await (
            await conn.execute(
                "SELECT w.amount_units, gc.nominal_units FROM withdrawals w JOIN gift_codes gc ON gc.id = w.code_id WHERE gc.id = %s",  # noqa: E501
                (delivery_id,),
            )
        ).fetchone()
    expected = int(row["nominal_units"]) if row else 0
    if check.status == "not_activated":
        raise DeliveryDeferred(delivery_id, "not_activated")  # noqa: B904
    if check.status == "unknown":
        raise DeliveryDeferred(delivery_id, "unknown_status")  # noqa: B904
    if check.delivered_units != expected:
        raise SettlementMismatch(expected, check.delivered_units)  # noqa: B904
    return VerificationResult(delivery_id, True, True, "ok")
