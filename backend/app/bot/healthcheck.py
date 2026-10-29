import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import httpx

from app.config import settings
from app.db import close_pool, get_conn, init_pool


async def run_healthcheck():
    await init_pool()
    try:
        while True:
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        f"https://api.telegram.org/bot{settings.bot_token}/getMe"
                    )
                ok = resp.status_code == 200
            except Exception:
                ok = False
            async with get_conn() as conn:
                await conn.execute(
                    "INSERT INTO bot_health (bot_token_hash, status, details) VALUES (%s, %s, %s)",
                    ("main", "ok" if ok else "fail", resp.text if "resp" in locals() else ""),
                )
                await conn.commit()
            if not ok and settings.healthcheck_bot_token and settings.healthcheck_target_chat_id:
                async with httpx.AsyncClient() as client:
                    await client.post(
                        f"https://api.telegram.org/bot{settings.healthcheck_bot_token}/sendMessage",
                        json={"chat_id": settings.healthcheck_target_chat_id, "text": "Bot down"},
                    )
            await asyncio.sleep(300)
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(run_healthcheck())
