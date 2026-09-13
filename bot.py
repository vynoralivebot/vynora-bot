import os
import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from dotenv import load_dotenv
from database import users_collection

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
WEBAPP_URL = os.getenv("WEBAPP_URL")
GROUP_2_ID = int(os.getenv("GROUP_2_ID", 0))

bot = Bot(token=TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    name = message.from_user.full_name
    
    existing_user = await users_collection.find_one({"telegram_id": user_id})
    if not existing_user:
        await users_collection.insert_one({
            "telegram_id": user_id,
            # Use raw string interpolation safely or fallback
            "name": name or "Unknown",
            "phone": None,
            "balance_minutes": 0
        })
        if GROUP_2_ID:
            await bot.send_message(
                GROUP_2_ID, 
                f"👤 **New User Registration**\nName: {name}\nID: `{user_id}`",
                parse_mode="Markdown"
            )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Open Hosts & Mini App", web_app=WebAppInfo(url=WEBAPP_URL))]
        ]
    )
    await message.answer(
        f"Welcome, {name}! Tap the button below to view available hosts and manage your sessions.",
        reply_markup=keyboard
    )

async def main():
    logging.basicConfig(level=logging.INFO)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
