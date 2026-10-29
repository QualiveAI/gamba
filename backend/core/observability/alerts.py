async def send_alert(message: str):
    import os

    import httpx

    token = os.getenv("HEALTHCHECK_BOT_TOKEN", "")
    chat = os.getenv("HEALTHCHECK_TARGET_CHAT_ID", "")
    if not token or not chat:
        return
    async with httpx.AsyncClient() as client:
        await client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": message},
        )
