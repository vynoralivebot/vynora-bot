import os
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

# Debugging ke liye token check print
if TOKEN:
    print(f"DEBUG: Token successfully loaded (Length: {len(TOKEN)})")
else:
    print("CRITICAL ERROR: BOT_TOKEN is missing or empty in Render environment!")

if not TOKEN:
    exit(1)

bot = Bot(token=TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("Hello! Your bot is successfully connected.")

async def main():
    logging.basicConfig(level=logging.INFO)
    print("Bot polling started...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
