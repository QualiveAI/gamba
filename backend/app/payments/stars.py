import httpx

from app.config import settings
from core.engine.ledger.ledger import post_entry


async def create_invoice_link(title: str, description: str, payload: str, amount_stars: int) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://api.telegram.org/bot{settings.bot_token}/createInvoiceLink",
            json={
                "title": title,
                "description": description,
                "payload": payload,
                "currency": "XTR",
                "prices": [{"label": title, "amount": amount_stars}],
            },
        )
    resp.raise_for_status()
    data = resp.json()
    return data["result"]


async def handle_successful_payment(conn, user_id: int, amount_units: int, payload: str):
    await post_entry(conn, user_id, "units", amount_units, "deposit_stars", payload)
    from app.analytics.events import track

    await track(conn, user_id, "deposit", {"provider": "stars", "units": amount_units})
    await conn.commit()
