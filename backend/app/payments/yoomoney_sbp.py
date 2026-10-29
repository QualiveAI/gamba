import hashlib
import hmac

import httpx
from psycopg.types.json import Json

from app.config import settings
from app.db import get_conn
from core.engine.ledger.ledger import post_entry

YOOMONEY_API = "https://api.yoomoney.ru/v3"


async def create_payment(conn, user_id: int, amount_rub: float):
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{YOOMONEY_API}/payments",
            json={
                "amount": {"value": f"{amount_rub:.2f}", "currency": "RUB"},
                "payment_method": {"type": "sbp"},
                "confirmation": {"type": "qr"},
                "metadata": {"user_id": user_id},
                "capture": True,
            },
            headers={"Idempotence-Key": f"pay-{user_id}-{amount_rub}"},
        )
    resp.raise_for_status()
    data = resp.json()
    external_id = data["id"]
    qr_url = data.get("confirmation", {}).get("confirmation_url") or data.get(
        "confirmation", {}
    ).get("qr")
    cur = await conn.execute(
        "INSERT INTO payment_polling (user_id, provider, external_id, amount_rub, status, metadata) "  # noqa: E501
        "VALUES (%s, %s, %s, %s, 'pending', %s) RETURNING id",
        (user_id, "yoomoney", external_id, amount_rub, Json({"qr": qr_url})),
    )
    pid = (await cur.fetchone())["id"]
    await conn.commit()
    return {"payment_id": pid, "external_id": external_id, "qr_url": qr_url, "status": "pending"}


def verify_webhook(payload: bytes, signature: str) -> bool:
    calc = hmac.new(settings.yoomoney_webhook_secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(calc, signature)


async def handle_webhook(conn, payload: dict):
    event = payload.get("event")
    obj = payload.get("object", {})
    external_id = obj.get("id")
    if not external_id:
        return {"ok": False}
    row = await (
        await conn.execute(
            "SELECT id, user_id, amount_rub, amount_units, status FROM payment_polling WHERE provider = 'yoomoney' AND external_id = %s FOR UPDATE",  # noqa: E501
            (external_id,),
        )
    ).fetchone()
    if row is None:
        return {"ok": False}
    if row["status"] in ("completed", "succeeded"):
        return {"ok": True}
    if event == "payment.succeeded" or obj.get("status") == "succeeded":
        from decimal import Decimal

        amount_rub = int(Decimal(str(obj.get("amount", {}).get("value", row["amount_rub"]))))
        units = int(amount_rub)  # 1 RUB -> 1 unit
        await post_entry(conn, row["user_id"], "units", units, "deposit_yoomoney", external_id)
        await conn.execute(
            "UPDATE payment_polling SET status = 'completed', amount_units = %s, updated_at = now() WHERE id = %s",  # noqa: E501
            (units, row["id"]),
        )
        from app.analytics.events import track

        await track(conn, row["user_id"], "deposit", {"provider": "yoomoney", "units": units})
        await conn.commit()
    return {"ok": True}


async def poll_status(conn, payment_id: int):
    row = await (
        await conn.execute(
            "SELECT id, external_id, user_id, amount_rub, status FROM payment_polling WHERE id = %s",  # noqa: E501
            (payment_id,),
        )
    ).fetchone()
    if row is None or row["status"] in ("completed", "succeeded", "failed"):
        return row
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{YOOMONEY_API}/payments/{row['external_id']}")
    if resp.status_code != 200:
        return row
    data = resp.json()
    status = data.get("status")
    if status == "succeeded":
        from decimal import Decimal

        amount_rub = int(Decimal(str(data.get("amount", {}).get("value", row["amount_rub"]))))
        units = int(amount_rub)
        await post_entry(
            conn, row["user_id"], "units", units, "deposit_yoomoney", row["external_id"]
        )
        await conn.execute(
            "UPDATE payment_polling SET status = 'completed', amount_units = %s, updated_at = now() WHERE id = %s",  # noqa: E501
            (units, payment_id),
        )
        from app.analytics.events import track

        await track(conn, row["user_id"], "deposit", {"provider": "yoomoney", "units": units})
        await conn.commit()
    elif status in ("canceled", "failed"):
        await conn.execute(
            "UPDATE payment_polling SET status = 'failed', updated_at = now() WHERE id = %s",
            (payment_id,),
        )
        await conn.commit()
    return await (
        await conn.execute(
            "SELECT id, external_id, user_id, amount_rub, status FROM payment_polling WHERE id = %s",  # noqa: E501
            (payment_id,),
        )
    ).fetchone()


async def manual_claim(conn, payment_id: int, receipt_url: str):
    await conn.execute(
        "UPDATE payment_polling SET status = 'manual_review', receipt_url = %s, updated_at = now() WHERE id = %s",  # noqa: E501
        (receipt_url, payment_id),
    )
    await conn.commit()
    return {"status": "manual_review"}


async def run_polling_loop():
    import asyncio

    while True:
        try:
            async with get_conn() as conn:
                rows = await (
                    await conn.execute(
                        "SELECT id FROM payment_polling WHERE status = 'pending' AND provider = 'yoomoney'"  # noqa: E501
                    )
                ).fetchall()
                for r in rows:
                    await poll_status(conn, r["id"])
        except Exception:
            pass
        await asyncio.sleep(10)
