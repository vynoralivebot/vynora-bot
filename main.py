import os
import asyncio
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEB_APP_URL = os.getenv("WEB_APP_URL")

app = FastAPI()

# Mount Static Folder (CSS, JS, Images ke liye)
app.mount("/static", StaticFiles(directory="static"), name="static")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Bot Start Command Handler
@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    markup = types.InlineKeyboardMarkup(
        inline_keyboard=[[
            types.InlineKeyboardButton(text="🚀 Open Vynora App", web_app=types.WebAppInfo(url=WEB_APP_URL))
        ]]
    )
    await message.answer("Vynora Live me aapka swagat hai!", reply_markup=markup)

# Telegram Webhook Endpoint
@app.post("/webhook")
async def webhook(request: Request):
    update = types.Update.model_validate(await request.json(), context={"bot": bot})
    await dp.feed_update(bot, update)
    return {"status": "ok"}

# Frontend UI Root Endpoint
@app.get("/")
async def root():
    return FileResponse("static/index.html")

# Startup Event for Webhook Setup
@app.on_event("startup")
async def on_startup():
    if WEB_APP_URL:
        webhook_url = f"{WEB_APP_URL.rstrip('/')}/webhook"
        await bot.set_webhook(webhook_url)

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
