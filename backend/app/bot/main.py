import asyncio
import os
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from app.config import settings
from app.db import close_pool, get_conn, init_pool

bot = Bot(token=settings.bot_token)
dp = Dispatcher()

WEBAPP_URL = os.getenv("WEBAPP_URL", "https://localhost")


@dp.message(Command("start"))
async def cmd_start(message):
    # handle ref payload
    text = message.text or ""
    if "ref_" in text:
        try:
            referrer_id = int(text.split("ref_")[1].split()[0])
            from app.referrals.service import handle_referral

            async with get_conn() as conn:
                await handle_referral(conn, message.from_user.id, referrer_id)
        except Exception:
            pass
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Open App", web_app=WebAppInfo(url=WEBAPP_URL))]
        ]
    )
    await message.answer("Welcome", reply_markup=kb)


@dp.message(Command("balance"))
async def cmd_balance(message):
    async with get_conn() as conn:
        row = await (
            await conn.execute(
                "SELECT balance_units FROM users WHERE telegram_id = %s", (message.from_user.id,)
            )
        ).fetchone()
    bal = row["balance_units"] if row else 0
    await message.answer(f"Balance: {bal}")


@dp.message(Command("withdraw"))
async def cmd_withdraw(message):
    url = WEBAPP_URL + "?screen=withdraw"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Withdraw", web_app=WebAppInfo(url=url))]]
    )
    await message.answer("Withdraw", reply_markup=kb)


@dp.message(Command("support"))
async def cmd_support(message):
    await message.answer("Support: @support")


async def main():
    await init_pool()
    try:
        await dp.start_polling(bot)
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
